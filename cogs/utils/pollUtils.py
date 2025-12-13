import asyncio
import asyncpg
import discord
import json
import os
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any
from discord import ui
from discord.ext import commands

from cogs.utils.emojis import MinoriEmojis, CustomEmojis

"""
pollUtils.py

Purpose
-------
Persistence and UI helpers for the bot's polling subsystem.

This module encapsulates:
- A small asyncpg-based persistence layer for polls (init, save, load, purge).
- A migration-safe initialization routine that will create the required polls table
  and attempt best-effort column migrations.
- Helper functions to save active polls and finalize/record results.
- PollView — an interactive discord.ui.View that represents a poll in memory and
  synchronizes state to the DB as users vote or the poll is updated.

Design & Operational Notes

- Database pool:
  - A module-level asyncpg Pool is lazily created with init_db_pool() from the
    DATABASE_URL environment variable (or an explicit DSN passed to init_db_pool).
  - The pool is cached in _POOL and closed by close_db_pool().
  - _DB_LOCK (asyncio.Lock) serializes schema changes and writes that must not run
    concurrently (e.g., migrations and normalization).

- Storage format:
  - options, votes, winners, counts are stored as TEXT in the DB (JSON-serialized).
    This keeps the schema portable and backward-compatible with the existing
    SQLite layout. Consumer code should json.loads or json.dumps when reading or
    writing these fields. The init_db function normalizes NULL options/votes to
    canonical JSON shapes (empty list / empty dict).
  - Timestamps:
    - end_time is stored as a DOUBLE PRECISION (UNIX epoch seconds) to preserve
      cross-language portability. Consumers may convert to datetime via datetime.fromtimestamp(..., timezone.utc).
    - created_at is TIMESTAMPTZ with a default of CURRENT_TIMESTAMP.

- Resiliency:
  - Most DB operations are best-effort: failures are printed but do not raise to
    prevent bot startup from failing. You can change this policy to raise
    exceptions if you prefer hard failures.

Usage
-----
- On bot startup:
    await pollUtils.init_db_pool()      # or call with explicit DSN
    await pollUtils.init_db()          # creates/migrates polls table and normalizes rows
    active = await pollUtils.load_active_polls()  # reload active polls into memory if needed

- When shutting down:
    await pollUtils.close_db_pool()

- Creating a poll (example in a command):
    view = PollInputModal(ctx, timeout_seconds=3600)
    await ctx.interaction.response.send_modal(view)
    # The modal handlers create PollView, send message, and call save_active_poll().

- The PollView stores votes in-memory as {option_text: set(user_id, ...)} and
  writes serialized state to the DB after votes and changes.

Schema (created by init_db)

CREATE TABLE polls (
    message_id BIGINT PRIMARY KEY,
    guild_id   BIGINT,
    channel_id BIGINT,
    author_id  BIGINT,
    question   TEXT,
    options    TEXT,
    votes      TEXT,
    end_time   DOUBLE PRECISION,
    ended      BOOLEAN DEFAULT FALSE,
    winners    TEXT,
    counts     TEXT,
    total_votes INTEGER,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
)
"""

_POOL: Optional[asyncpg.Pool] = None
_DB_LOCK = asyncio.Lock()
MODAL_PLACEHOLDER = "Leave empty if not needed"


#  DB Pool Helpers  #

async def init_db_pool(dsn: Optional[str] = None, *, min_size: int = 1, max_size: int = 10) -> None:
    """
    Lazily initialize the asyncpg connection pool.

    Parameters
    ----------
    dsn:
        Optional database DSN. If omitted the function reads DATABASE_URL from
        environment variables.
    min_size, max_size:
        Pool sizing parameters passed to asyncpg.create_pool.

    Raises
    ------
    RuntimeError
        If no DSN is provided and DATABASE_URL is not set in the environment.
    """
    global _POOL
    if _POOL is None:
        dsn = dsn or os.getenv("DATABASE_URL")
        if not dsn:
            raise RuntimeError("DATABASE_URL is not set")
        _POOL = await asyncpg.create_pool(dsn=dsn, min_size=min_size, max_size=max_size)


async def close_db_pool() -> None:
    """
    Close and clear the cached connection pool.

    Safe to call multiple times (no-op if the pool is already closed).
    """
    global _POOL
    if _POOL is not None:
        await _POOL.close()
        _POOL = None


async def get_pool() -> asyncpg.Pool:
    """
    Ensure the pool exists and return it.

    Convenience helper used throughout the module.
    """
    await init_db_pool()
    assert _POOL is not None
    return _POOL



async def init_db():
    """
    Initialize or migrate the polls table.

    Responsibilities:
    - Create the polls table if it doesn't exist.
    - Perform best-effort migrations (add missing columns).
    - Normalize NULL options/votes to canonical JSON shapes (options -> '[]', votes -> '{}').

    Concurrency:
    - Uses _DB_LOCK to serialize DDL and normalization operations to prevent
      interleaving with concurrent writes.
    """
    pool = await get_pool()
    async with _DB_LOCK:
        async with pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS polls (
                    message_id BIGINT PRIMARY KEY,
                    guild_id   BIGINT,
                    channel_id BIGINT,
                    author_id  BIGINT,
                    question   TEXT,
                    options    TEXT,
                    votes      TEXT,
                    end_time   DOUBLE PRECISION,
                    ended      BOOLEAN DEFAULT FALSE,
                    winners    TEXT,
                    counts     TEXT,
                    total_votes INTEGER,
                    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Check for missing columns (best-effort migration)
            cols = await conn.fetch("""
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'polls'
            """)
            col_names = {c["column_name"] for c in cols}
            if "author_id" not in col_names:
                try:
                    await conn.execute("ALTER TABLE polls ADD COLUMN author_id BIGINT")
                except Exception:
                    # Non-fatal if migration fails; we continue with normalization
                    pass

            # Normalize NULLs to canonical JSON shapes to simplify downstream logic
            try:
                await conn.execute("UPDATE polls SET options='[]' WHERE options IS NULL")
                await conn.execute("UPDATE polls SET votes='{}' WHERE votes IS NULL")
            except Exception:
                # Best-effort only
                pass


#  CRUD Helpers  #

def _json_dumps(value: Any) -> str:
    """Serialize Python objects to JSON text (ensure_ascii disabled for clarity)."""
    return json.dumps(value, ensure_ascii=False)


async def save_active_poll(message_id, guild_id, channel_id, author_id, question, options, votes, end_time):
    """
    Insert or update an active poll row into the database.

    The function serializes `options` and `votes` to JSON text for storage.

    Parameters
    ----------
    message_id:
        Discord message id (int or discord.Message.id) that identifies the poll message.
    guild_id, channel_id, author_id:
        Discord snowflakes for guild/channel/author.
    question:
        Poll question string.
    options:
        A Python list of option strings (will be json.dumps'ed).
    votes:
        A mapping of option -> set(user_id). This function converts sets to lists
        before serialization.
    end_time:
        Optional datetime (timezone-aware) indicating when the poll ends. Stored
        as an epoch float (seconds) or NULL if not provided.
    """
    pool = await get_pool()
    async with _DB_LOCK:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO polls (
                    message_id, guild_id, channel_id, author_id,
                    question, options, votes, end_time, ended
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, FALSE)
                ON CONFLICT (message_id) DO UPDATE SET
                    guild_id   = EXCLUDED.guild_id,
                    channel_id = EXCLUDED.channel_id,
                    author_id  = EXCLUDED.author_id,
                    question   = EXCLUDED.question,
                    options    = EXCLUDED.options,
                    votes      = EXCLUDED.votes,
                    end_time   = EXCLUDED.end_time,
                    ended      = FALSE
                """,
                message_id,
                guild_id,
                channel_id,
                author_id,
                question,
                _json_dumps(options),
                _json_dumps({k: list(v) for k, v in votes.items()}),
                end_time.timestamp() if end_time else None,
            )


async def record_poll_result(message_id, winners, counts, total_votes):
    """
    Mark a poll as ended and persist winners/counts/total_votes.

    Parameters
    ----------
    message_id:
        Discord message id (poll identifier).
    winners:
        Python object (list or dict) representing winners; will be JSON-serialized.
    counts:
        Python object representing counts per option; will be JSON-serialized.
    total_votes:
        Integer total vote count.
    """
    pool = await get_pool()
    async with _DB_LOCK:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE polls
                   SET winners = $1,
                       counts = $2,
                       total_votes = $3,
                       ended = TRUE
                 WHERE message_id = $4
                """,
                _json_dumps(winners),
                _json_dumps(counts),
                total_votes,
                message_id,
            )


async def load_active_polls():
    """
    Return a list of polls that are still active (ended = FALSE).

    Each returned item is a dict mapping column name -> stored value. Note:
    - options and votes are returned as stored (JSON strings); callers should
      json.loads and validate the types before using them.
    - end_time is returned as stored (epoch float) and should be converted by
      callers to a datetime if needed.
    """
    pool = await get_pool()
    query = """
        SELECT
            message_id,
            guild_id,
            channel_id,
            author_id,
            question,
            options,
            votes,
            end_time,
            ended
        FROM polls
        WHERE ended = FALSE
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(query)
        return [dict(r) for r in rows]


async def purge_finished_polls():
    """
    Delete polls that have ended (ended = TRUE).

    This is useful for periodic cleanup jobs to keep the active polls table small.
    """
    pool = await get_pool()
    async with _DB_LOCK:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM polls WHERE ended = TRUE")


#  Poll UI  #

class PollView(discord.ui.View):
    """
    Interactive in-memory representation of a poll.

    Behavior
    --------
    - Holds poll state in memory: question, options, votes (as sets of user ids).
    - Renders a Discord embed summarizing the poll and a select menu for voting.
    - Persists to DB (save_active_poll) on vote add/remove and when options change.
    - Supports an optional timeout: if timeout is provided the view will auto-end
      the poll and persist the final results when the timer expires.

    Attributes
    ----------
    question: str
        Poll question text.
    options: List[str]
        Option labels in order.
    votes: Dict[str, Set[int]]
        Mapping option -> set of voter IDs.
    author: discord.Member
        Creator of the poll (only author can add options and end the poll).
    message: Optional[discord.Message]
        The message instance representing the poll in Discord (populated after send).
    updater_task: Optional[asyncio.Task]
        Background task for auto-ending the poll when a timeout was set.
    end_time: Optional[datetime]
        The UTC timestamp when the poll should end (if timeout provided).
    ended: bool
        Whether the poll has been finalized.
    """
    def __init__(self, question: str, options: List[str], author: discord.Member, timeout: Optional[int] = None):
        super().__init__(timeout=timeout)
        self.question = question
        self.options = options
        # votes stored as option -> set(user_id)
        self.votes = {opt: set() for opt in options}
        self.author = author
        self.message: Optional[discord.Message] = None
        self.updater_task: Optional[asyncio.Task] = None
        self.ended = False
        self.end_time = (datetime.now(timezone.utc) + timedelta(seconds=timeout)) if timeout else None

        # UI components
        add_button = discord.ui.Button(label="Add Option", style=discord.ButtonStyle.green)
        add_button.callback = self.add_option
        self.add_item(add_button)

        select = discord.ui.Select(
            placeholder="Select one answer",
            options=[discord.SelectOption(label=opt, value=str(i)) for i, opt in enumerate(options)],
            min_values=1,
            max_values=1
        )
        select.callback = self.select_callback
        self.add_item(select)

        remove_button = discord.ui.Button(label="Remove Vote", style=discord.ButtonStyle.danger)
        remove_button.callback = self.remove_vote
        self.add_item(remove_button)

        end_button = discord.ui.Button(label="End Poll", style=discord.ButtonStyle.red)
        end_button.callback = self.end_poll
        self.add_item(end_button)

        if self.end_time:
            loop = asyncio.get_running_loop()
            self.updater_task = loop.create_task(self._auto_end())

    async def _auto_end(self):
        """
        Background coroutine that waits until end_time and then finalizes the poll.
        """
        if self.ended or not self.end_time:
            return

        remaining = (self.end_time - datetime.now(timezone.utc)).total_seconds()
        if remaining > 0:
            await asyncio.sleep(remaining)

        if not self.ended:
            await self.on_timeout()

    async def _ensure_poll_active(self, interaction: discord.Interaction) -> bool:
        """
        Helper to check whether the poll is still active and respond to the interaction
        if it is not. Returns True when the poll is active and the interaction may proceed.
        """
        if self.ended:
            try:
                await interaction.response.send_message("⚠️ Poll already closed.", ephemeral=True)
            except discord.errors.InteractionResponded:
                try:
                    await interaction.followup.send("⚠️ Poll already closed.", ephemeral=True)
                except Exception:
                    pass
            return False
        if self.end_time and datetime.now(timezone.utc) >= self.end_time:
            if self.updater_task and not self.updater_task.done():
                try:
                    self.updater_task.cancel()
                except Exception:
                    pass
            await self.on_timeout()
            try:
                await interaction.response.send_message("⚠️ Poll has already ended.", ephemeral=True)
            except discord.errors.InteractionResponded:
                try:
                    await interaction.followup.send("⚠️ Poll has already ended.", ephemeral=True)
                except Exception:
                    pass
            return False
        return True

    def _cancel_updater_if_needed(self):
        """
        Cancel the updater_task if it's running and it's not the current asyncio task.
        """
        try:
            current = asyncio.current_task()
        except Exception:
            current = None
        if self.updater_task and self.updater_task is not current and not self.updater_task.done():
            try:
                self.updater_task.cancel()
            except Exception:
                pass

    def _compute_results(self):
        """
        Compute result aggregates for the poll.

        Returns
        -------
        results: dict
            Mapping option -> vote count (integer).
        winners: list
            List of winning option strings (may be multiple on a tie).
        winner_text: str
            Friendly human-readable summary text for posting to the channel.
        """
        results = {opt: len(users) for opt, users in self.votes.items()}
        winners = []
        winner_text = ""
        if results:
            max_votes = max(results.values())
            winners = [opt for opt, count in results.items() if count == max_votes]
            if max_votes > 0:
                if len(winners) == 1:
                    winner_text = (
                        f"\n\n{MinoriEmojis['MinoriPray']} Polling for `{self.question}` ended. "
                        f"The highest vote goes to **{winners[0]}** with {max_votes} vote{'s' if max_votes!=1 else ''}."
                    )
                else:
                    winner_text = (
                        f"\n\n{MinoriEmojis['MinoriPray']} Polling for `{self.question}` ended. "
                        f"It's a tie between {', '.join(winners)} — each with {max_votes} votes."
                    )
            else:
                winner_text = (
                    f"\n\n{MinoriEmojis['MinoriWink']} Polling for `{self.question}` ended. "
                    "No votes were cast."
                )
        return results, winners, winner_text

    async def _persist_results(self, results, winners):
        """
        Persist final results to the DB using record_poll_result.
        """
        try:
            await record_poll_result(
                message_id=self.message.id if self.message else None,
                winners=winners,
                counts=results,
                total_votes=sum(results.values())
            )
        except Exception as e:
            print(f"[Poll DB Save Error] {e}")

    async def _finalize_view(self, winner_text: str):
        """
        Update the Discord message to a closed view and send the winner_text if present.
        """
        self.clear_items()
        if self.message:
            final_embed = self.make_poll_embed(closed=True)
            try:
                await self.message.edit(embed=final_embed, view=self)
            except Exception as e:
                print(f"[on_timeout] failed editing final embed: {e}")
            if winner_text:
                try:
                    await self.message.channel.send(winner_text)
                except Exception as e:
                    print(f"[on_timeout] failed sending winner_text: {e}")

    async def on_timeout(self):
        """
        Finalize a poll when it times out. This method is safe to call multiple times.
        """
        if self.ended:
            return
        self.ended = True
        self._cancel_updater_if_needed()
        results, winners, winner_text = self._compute_results()
        await self._persist_results(results, winners)
        await self._finalize_view(winner_text)

    async def select_callback(self, interaction: discord.Interaction):
        """
        Handler for a user selecting an option from the Select menu.

        - Validates the poll is active.
        - Converts the selected index to an option label.
        - Ensures each user has at most one vote (removes prior choices).
        - Persists the active poll state to the DB.
        - Updates the message with a short ephemeral confirmation.
        """
        if not await self._ensure_poll_active(interaction):
            return

        try:
            idx = int(interaction.data["values"][0])
        except Exception:
            return await interaction.response.send_message("⚠️ Invalid selection.", ephemeral=True)

        if idx < 0 or idx >= len(self.options):
            return await interaction.response.send_message("⚠️ Invalid choice.", ephemeral=True)

        choice_label = self.options[idx]

        for opt in self.votes:
            self.votes[opt].discard(interaction.user.id)
        self.votes[choice_label].add(interaction.user.id)

        if self.message:
            try:
                await save_active_poll(
                    message_id=self.message.id,
                    guild_id=self.message.guild.id,
                    channel_id=self.message.channel.id,
                    author_id=self.author.id,
                    question=self.question,
                    options=self.options,
                    votes=self.votes,
                    end_time=self.end_time
                )
            except Exception as e:
                print(f"[Poll DB Save Error on vote] {e}")

        await self.update_poll(interaction, f"{CustomEmojis['VERIFIED']} You voted for **{choice_label}**")

    async def add_option(self, interaction: discord.Interaction):
        """
        Initiates the AddOptionModal to allow the poll author to append new options.

        Only the poll creator (author) is permitted to add options.
        """
        if not await self._ensure_poll_active(interaction):
            return

        if interaction.user.id != self.author.id:
            return await interaction.response.send_message("⚠️ Only the poll creator can add options.", ephemeral=True)

        modal = AddOptionModal(self)
        await interaction.response.send_modal(modal)

    async def remove_vote(self, interaction: discord.Interaction):
        """
        Remove the invoking user's vote if they previously voted.
        """
        if not await self._ensure_poll_active(interaction):
            return

        removed = False
        for opt in self.votes:
            if interaction.user.id in self.votes[opt]:
                self.votes[opt].remove(interaction.user.id)
                removed = True

        if removed:
            if self.message:
                try:
                    await save_active_poll(
                        message_id=self.message.id,
                        guild_id=self.message.guild.id,
                        channel_id=self.message.channel.id,
                        author_id=self.author.id,
                        question=self.question,
                        options=self.options,
                        votes=self.votes,
                        end_time=self.end_time
                    )
                except Exception as e:
                    print(f"[Poll DB Save Error on remove] {e}")
            await self.update_poll(interaction, "❌ Your vote was removed.")
        else:
            await interaction.response.send_message("⚠️ You haven't voted yet.", ephemeral=True)

    async def end_poll(self, interaction: discord.Interaction):
        """
        Allow the poll author to end the poll immediately.

        This method cancels any running updater_task and delegates to on_timeout().
        """
        if interaction.user.id != self.author.id:
            return await interaction.response.send_message("⚠️ Only the poll creator can end this poll.", ephemeral=True)

        if self.updater_task and not self.updater_task.done():
            self.updater_task.cancel()

        await interaction.response.defer(ephemeral=True)
        await self.on_timeout()

    async def update_poll(self, interaction: discord.Interaction, ephemeral_msg: str):
        """
        Update the Discord message embed and respond to the interaction with an
        ephemeral confirmation.

        This method attempts progressively smaller embed renderings if Discord
        rejects the size due to embed field limits.
        """
        embed = self.make_poll_embed()
        if self.message:
            try:
                await self.message.edit(embed=embed, view=self)
            except discord.errors.HTTPException as e:
                err_str = str(e).lower()
                if "embed size" in err_str or "exceeds" in err_str:
                    for bl in (8, 6, 4, 2):
                        try:
                            smaller = self.make_poll_embed(bar_len=bl)
                            await self.message.edit(embed=smaller, view=self)
                            embed = smaller
                            break
                        except Exception:
                            continue
                    else:
                        try:
                            fetched = await self.message.channel.fetch_message(self.message.id)
                            self.message = fetched
                            await self.message.edit(embed=embed, view=self)
                        except Exception:
                            try:
                                new_msg = await self.message.channel.send(embed=embed, view=self)
                                self.message = new_msg
                            except Exception as ex:
                                print(f"[update_poll] failed to update/send poll message: {ex}")
                else:
                    try:
                        fetched = await self.message.channel.fetch_message(self.message.id)
                        self.message = fetched
                        await self.message.edit(embed=embed, view=self)
                    except Exception:
                        try:
                            new_msg = await self.message.channel.send(embed=embed, view=self)
                            self.message = new_msg
                        except Exception as ex:
                            print(f"[update_poll] failed to recover from HTTPException: {ex}")
            except Exception as e:
                try:
                    new_msg = await self.message.channel.send(embed=embed, view=self)
                    self.message = new_msg
                except Exception as ex:
                    print(f"[update_poll] unexpected failure editing/sending message: {ex}")
        else:
            try:
                sent = await interaction.channel.send(embed=embed, view=self)
                self.message = sent
            except Exception:
                pass
        try:
            await interaction.response.send_message(ephemeral_msg, ephemeral=True)
        except discord.errors.InteractionResponded:
            try:
                await interaction.followup.send(ephemeral_msg, ephemeral=True)
            except Exception:
                pass
        except Exception:
            pass

    def make_poll_embed(self, closed: bool = False, bar_len: int = 10):
        """
        Build and return a Discord embed representation of the poll.

        Parameters
        ----------
        closed:
            If True, the embed will indicate the poll is closed.
        bar_len:
            Length of the textual progress bar displayed for each option.

        Returns
        -------
        discord.Embed
            The constructed embed ready to be sent or edited into the poll message.
        """
        total_votes = sum(len(v) for v in self.votes.values())
        colors = ["🟦", "🟥", "🟩", "🟨", "🟪", "🟧", "🟫"]

        embed = discord.Embed(
            title=f"{CustomEmojis['CHART']}  {self.question}",
            color=discord.Color.blurple()
        )

        for i, (opt, users) in enumerate(self.votes.items(), 1):
            count = len(users)
            percent = (count / total_votes * 100) if total_votes > 0 else 0
            filled = int(percent / 100 * bar_len) if bar_len > 0 else 0
            empty = max(0, bar_len - filled)
            color = colors[i % len(colors)]
            bar = color * filled + f"{CustomEmojis['Gray_Large_Square']}" * empty

            name = opt
            embed.add_field(
                name=name,
                value=f"{bar} `{percent:.0f}% ({count})`",
                inline=False
            )

        if closed:
            if self.end_time:
                status = (
                    f"{CustomEmojis['Locked']} Poll closed <t:{int(self.end_time.timestamp())}:R>\n"
                    f"{CustomEmojis['SecretBox']} Votes are anonymous\n"
                    f"With total of `{total_votes} votes`"
                )
            else:
                status = f"{CustomEmojis['Locked']} Poll closed\n{CustomEmojis['SecretBox']} Votes are anonymous\n{total_votes} votes"
        elif self.end_time:
            status = (
                f"{CustomEmojis['TIME']} Poll closes <t:{int(self.end_time.timestamp())}:R>\n"
                f"{CustomEmojis['SecretBox']} Votes are anonymous\n"
                f"Total Votes: `{total_votes}` votes"
            )
        else:
            status = f"{CustomEmojis['SecretBox']} Votes are anonymous\n{total_votes} votes"
        embed.add_field(name="\u200b", value=status, inline=False)
        return embed


class AddOptionModal(ui.Modal, title="Add Poll Options"):
    """
    Modal presented to the poll creator to add up to 5 additional options.

    Upon submit the modal updates the PollView, persists the new state, and
    edits the poll message.
    """
    opt1 = ui.TextInput(label="Option 1 (optional)", required=False, max_length=100,
                        placeholder=MODAL_PLACEHOLDER)
    opt2 = ui.TextInput(label="Option 2 (optional)", required=False, max_length=100,
                        placeholder=MODAL_PLACEHOLDER)
    opt3 = ui.TextInput(label="Option 3 (optional)", required=False, max_length=100,
                        placeholder=MODAL_PLACEHOLDER)
    opt4 = ui.TextInput(label="Option 4 (optional)", required=False, max_length=100,
                        placeholder=MODAL_PLACEHOLDER)
    opt5 = ui.TextInput(label="Option 5 (optional)", required=False, max_length=100,
                        placeholder=MODAL_PLACEHOLDER)

    def __init__(self, poll_view: "PollView"):
        super().__init__()
        self.poll_view = poll_view
        self.description = "Note: Discord only allows a maximum of 25 options per select menu."

    async def on_submit(self, interaction: discord.Interaction):
        """
        Add options to the poll and persist the new state.

        Validations:
        - No duplicate options (case-insensitive).
        - Poll author only.
        - Maximum options limit enforced.
        """
        if not self.poll_view.message:
            return await interaction.response.send_message("⚠️ Poll message no longer exists.", ephemeral=True)

        new_opts_raw = [
            self.opt1.value.strip(),
            self.opt2.value.strip(),
            self.opt3.value.strip(),
            self.opt4.value.strip(),
            self.opt5.value.strip()
        ]
        new_opts = [o for o in new_opts_raw if o]

        if not new_opts:
            return await interaction.response.send_message(
                "⚠️ No new options were added.", ephemeral=True
            )

        normalized_existing = [o.lower() for o in self.poll_view.options]
        for opt in new_opts:
            if opt.lower() in normalized_existing:
                return await interaction.response.send_message(
                    f"{MinoriEmojis['MinoriConfused']} You can't add duplicate options.",
                    ephemeral=True
                )
        MAX_OPTIONS = 14
        if len(self.poll_view.options) + len(new_opts) > MAX_OPTIONS:
            return await interaction.response.send_message(
                f"⚠️ You can only add up to {MAX_OPTIONS} options.", ephemeral=True
            )

        for opt in new_opts:
            self.poll_view.options.append(opt)
            self.poll_view.votes[opt] = set()
            select: discord.ui.Select = next(
                (i for i in self.poll_view.children if isinstance(i, discord.ui.Select)), None
            )
            if select:
                select.options = [discord.SelectOption(label=opt, value=str(idx))
                                  for idx, opt in enumerate(self.poll_view.options)]
                select.placeholder = "Select one answer (scroll for more)" if len(self.poll_view.options) > 10 else "Select one answer"

        embed = self.poll_view.make_poll_embed()
        await self.poll_view.message.edit(embed=embed, view=self.poll_view)

        try:
            await save_active_poll(
                message_id=self.poll_view.message.id,
                guild_id=self.poll_view.message.guild.id,
                channel_id=self.poll_view.message.channel.id,
                author_id=self.poll_view.author.id,
                question=self.poll_view.question,
                options=self.poll_view.options,
                votes=self.poll_view.votes,
                end_time=self.poll_view.end_time
            )
        except Exception as e:
            print(f"[Poll DB Save Error on add_option] {e}")

        await interaction.response.send_message(
            f"{CustomEmojis['VERIFIED']} Added {len(new_opts)} option(s). Total options: {len(self.poll_view.options)}",
            ephemeral=True
        )


class PollInputModal(ui.Modal, title="Create Poll"):
    """
    Modal used to create a new poll.

    When submitted this modal constructs a PollView, sends the poll message, and
    persists the active poll state via save_active_poll.
    """
    question = ui.TextInput(label="Question", placeholder="What's the poll about?", required=True, max_length=200)
    opt1 = ui.TextInput(label="Option 1 (required)", placeholder="First option (required)", required=True, max_length=100)
    opt2 = ui.TextInput(label="Option 2 (required)", placeholder="Second option (required)", required=True, max_length=100)
    opt3 = ui.TextInput(label="Option 3 (optional)", placeholder="Third option (optional)", required=False, max_length=100)
    opt4 = ui.TextInput(label="Option 4 (optional)", placeholder="Fourth option (optional)", required=False, max_length=100)

    def __init__(self, ctx: commands.Context, timeout_seconds: Optional[int] = None):
        super().__init__()
        self.ctx = ctx
        self.timeout_seconds = timeout_seconds

    async def on_submit(self, interaction: discord.Interaction):
        """
        Create the poll and persist it.

        Validations:
        - At least two options required.
        - No duplicate options (case-insensitive).
        """
        raw_opts = [
            self.opt1.value.strip(),
            self.opt2.value.strip(),
            self.opt3.value.strip(),
            self.opt4.value.strip()
        ]
        opts = [o for o in raw_opts if o]

        if len(opts) < 2:
            return await interaction.response.send_message(
                "⚠️ Please provide at least two options (Option 1 and Option 2 are required).",
                ephemeral=True
            )

        normalized = [o.strip().lower() for o in opts]
        if len(set(normalized)) != len(normalized):
            return await interaction.response.send_message(
                f"{MinoriEmojis['MinoriConfused']} You cant make same options",
                ephemeral=True
            )
        try:
            view = PollView(self.question.value, opts, self.ctx.author, timeout=self.timeout_seconds)
            embed = view.make_poll_embed()
            msg = await interaction.channel.send(embed=embed, view=view)
            view.message = msg
            end_time = (datetime.now(timezone.utc) + timedelta(seconds=self.timeout_seconds)) if self.timeout_seconds else None
            await save_active_poll(
                message_id=msg.id,
                guild_id=interaction.guild.id,
                channel_id=interaction.channel.id,
                author_id=interaction.user.id,
                question=self.question.value,
                options=opts,
                votes=view.votes,
                end_time=end_time
            )

            try:
                await interaction.response.send_message(f"{CustomEmojis['VERIFIED']} Poll successfully created!", ephemeral=True)
            except discord.errors.InteractionResponded:
                await interaction.followup.send(f"{CustomEmojis['VERIFIED']} Poll successfully created!", ephemeral=True)
        except Exception as e:
            print(f"[Poll Create Error] {e}")
            try:
                await interaction.response.send_message(f"⚠️ Failed to create poll: {e}", ephemeral=True)
            except discord.errors.InteractionResponded:
                await interaction.followup.send(f"⚠️ Failed to create poll: {e}", ephemeral=True)