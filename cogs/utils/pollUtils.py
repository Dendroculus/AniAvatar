import asyncio
import asyncpg
import discord
import json
import os
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any, Iterable
from discord import ui
from discord.ext import commands

from cogs.utils.emojis import MinoriEmojis, CustomEmojis

"""
pollUtils.py

Purpose
-------
Persistence and UI helpers for the bot's polling subsystem.

This module provides a production-oriented polling implementation that:
- Persists poll metadata (question/options/end time/finished state) in a `polls`
  table.
- Persists votes in a relational `poll_votes` table (one row per user vote).
- Exposes a compact interactive UI (discord.ui.View + Modal) for creating and
  running polls inside Discord.

Why relational votes?
---------------------
Storing votes as a JSONB blob and rewriting that blob on every vote leads to
"write amplification" and heavy locks on the polls row under high concurrency.
This causes latency spikes and can overload the database during viral events.

This implementation instead stores individual votes in `poll_votes`:
  (message_id, user_id, option_idx)
with PRIMARY KEY (message_id, user_id) so each vote is a cheap INSERT/UPSERT that
scales to many concurrent voters without rewriting a large JSON object.

Key design goals
----------------
- Concurrency: rely on PostgreSQL atomic operations (INSERT ... ON CONFLICT)
  and short transactions rather than in-process Python locks to permit high
  throughput and multi-process/multi-host deployments.
- Durability: persist every vote as it occurs to minimize recent-state loss on
  crashes. If you prefer higher throughput at the cost of durability, consider
  batching/debouncing writes (not implemented here).
- Observability: table and index DDLs are included in init_db() so a fresh
  deployment will create the minimal schema needed. Use migration tooling for
  schema evolution in production.
- Safety: every acquired connection is configured with a local statement_timeout
  to prevent runaway queries from exhausting the pool.
"""

_POOL: Optional[asyncpg.Pool] = None
MODAL_PLACEHOLDER = "Leave empty if not needed"
STMT_TIMEOUT_MS = 2000  # safety valve for long-running queries


#  DB Pool Helpers  #


async def init_db_pool(dsn: Optional[str] = None, *, min_size: int = 1, max_size: int = 10) -> None:
    """
    Lazily initialize the asyncpg connection pool.

    Parameters
    ----------
    dsn : Optional[str]
        Database DSN to connect to. If omitted, the function reads
        DATABASE_URL from the environment.
    min_size, max_size : int
        Connection pool sizing parameters. Increase max_size for higher
        concurrent voter throughput.

    Behavior
    --------
    - The pool is cached in the module-global _POOL variable.
    - Safe to call multiple times; the pool is only created once until closed.

    Raises
    ------
    RuntimeError
        If no DSN was provided and DATABASE_URL is not set in the environment.
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

    Safe to call multiple times. After calling this function, a subsequent
    get_pool/init_db_pool call will create a new pool.
    """
    global _POOL
    if _POOL is not None:
        await _POOL.close()
        _POOL = None


async def get_pool() -> asyncpg.Pool:
    """
    Ensure the pool exists and return it.

    Returns
    -------
    asyncpg.Pool
        A ready-to-use connection pool.
    """
    await init_db_pool()
    assert _POOL is not None
    return _POOL


async def _set_stmt_timeout(conn: asyncpg.Connection, ms: int = STMT_TIMEOUT_MS):
    """
    Apply a per-connection statement timeout to avoid runaway queries.

    This uses: SET LOCAL statement_timeout = <ms>

    Notes
    -----
    - SET LOCAL limits the timeout to the current transaction or statement.
    - This helper is best-effort; failures are ignored so callers do not crash
      on restrictive DB server configurations.
    """
    try:
        await conn.execute(f"SET LOCAL statement_timeout = {ms}")
    except Exception:
        pass


#  Schema Initialization  #


async def init_db():
    """
    Initialize the polls and poll_votes tables if they don't exist.

    The function is idempotent and will not alter existing columns. Use a
    migration tool for schema changes in production.

    Recommended schema:
      - polls: stores poll metadata and final aggregated results
      - poll_votes: one row per (message_id, user_id) to persist current vote

    See module top-level docstring for migration guidance.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        await _set_stmt_timeout(conn)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS polls (
                message_id BIGINT PRIMARY KEY,
                guild_id   BIGINT,
                channel_id BIGINT,
                author_id  BIGINT,
                question   TEXT,
                options    JSONB DEFAULT '[]'::jsonb,
                end_time   DOUBLE PRECISION,
                ended      BOOLEAN DEFAULT FALSE,
                winners    JSONB,
                counts     JSONB,
                total_votes INTEGER,
                created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS poll_votes (
                message_id BIGINT REFERENCES polls(message_id) ON DELETE CASCADE,
                user_id    BIGINT NOT NULL,
                option_idx INTEGER NOT NULL,
                PRIMARY KEY (message_id, user_id)
            )
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS poll_votes_option_idx
            ON poll_votes (message_id, option_idx)
        """)


def _json_dumps(value: Any) -> str:
    """
    Serialize Python objects to JSON text for deterministic storage/inspection.

    Parameters
    ----------
    value : Any
        Python object to serialize.

    Returns
    -------
    str
        JSON encoded string.
    """
    return json.dumps(value, ensure_ascii=False)


#  Persistence helpers  #


async def save_active_poll(message_id, guild_id, channel_id, author_id, question, options, end_time):
    """
    Insert or update poll metadata (no vote blob).

    Notes
    -----
    - votes are intentionally not stored on the polls row; they live in poll_votes.
    - options is persisted as JSON text for human readability and to preserve
      ordering. Consumers relying on DB access can read the options JSONB.
    - end_time may be None; when provided it is stored as epoch seconds (float).

    Parameters
    ----------
    message_id, guild_id, channel_id, author_id : int
        Discord identifiers.
    question : str
        Poll question text.
    options : list[str]
        Ordered list of option strings.
    end_time : Optional[datetime]
        Expiration time for the poll or None.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        await _set_stmt_timeout(conn)
        await conn.execute(
            """
            INSERT INTO polls (
                message_id, guild_id, channel_id, author_id,
                question, options, end_time, ended
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, FALSE)
            ON CONFLICT (message_id) DO UPDATE SET
                guild_id   = EXCLUDED.guild_id,
                channel_id = EXCLUDED.channel_id,
                author_id  = EXCLUDED.author_id,
                question   = EXCLUDED.question,
                options    = EXCLUDED.options,
                end_time   = EXCLUDED.end_time,
                ended      = FALSE
            """,
            message_id,
            guild_id,
            channel_id,
            author_id,
            question,
            _json_dumps(options),
            end_time.timestamp() if end_time else None,
        )


async def upsert_vote(message_id: int, user_id: int, option_idx: int):
    """
    Insert or update a single user's vote (constant-time write).

    Parameters
    ----------
    message_id : int
        The Discord message id that identifies the poll.
    user_id : int
        The Discord user id of the voter.
    option_idx : int
        Zero-based index into the poll's options list.

    Behavior
    --------
    - Uses INSERT ... ON CONFLICT to upsert the user's choice. This is atomic
      at the row level and safe for concurrent writers.
    - Caller should ensure option_idx is a valid index for the poll options.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        await _set_stmt_timeout(conn)
        await conn.execute(
            """
            INSERT INTO poll_votes (message_id, user_id, option_idx)
            VALUES ($1, $2, $3)
            ON CONFLICT (message_id, user_id)
            DO UPDATE SET option_idx = EXCLUDED.option_idx
            """,
            message_id, user_id, option_idx
        )


async def delete_vote(message_id: int, user_id: int):
    """
    Remove a user's vote for a poll.

    If no vote exists this operation is a no-op.

    Parameters
    ----------
    message_id : int
        Poll message id.
    user_id : int
        Voter's Discord user id.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        await _set_stmt_timeout(conn)
        await conn.execute(
            "DELETE FROM poll_votes WHERE message_id = $1 AND user_id = $2",
            message_id, user_id
        )


async def load_active_polls():
    """
    Return active polls plus their votes aggregated from poll_votes.

    Returns
    -------
    List[dict]
        Each dict contains poll columns and a `votes` mapping:
            item["votes"] -> { option_label (str) : set(user_id ints) }

    Notes
    -----
    - This function fetches polls (ended = FALSE) and then fetches all related
      poll_votes for those polls in a single query (WHERE message_id = ANY(...)).
    - Aggregation maps option_idx back to the option label using the poll's
      persisted options value.
    - Consumers should be careful with memory if reloading tens of thousands of
      active polls (not typical). This function is primarily intended for
      rehydrating currently active polls at bot startup.
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
            end_time,
            ended
        FROM polls
        WHERE ended = FALSE
    """
    async with pool.acquire() as conn:
        await _set_stmt_timeout(conn)
        poll_rows = await conn.fetch(query)
        if not poll_rows:
            return []

        message_ids = [r["message_id"] for r in poll_rows]
        vote_rows = await conn.fetch(
            "SELECT message_id, user_id, option_idx FROM poll_votes WHERE message_id = ANY($1)",
            message_ids
        )

    votes_by_message: Dict[int, Dict[str, set[int]]] = {mid: {} for mid in message_ids}
    # Build label lookup per poll to map option_idx -> option text
    options_map: Dict[int, List[str]] = {r["message_id"]: json.loads(r["options"]) for r in poll_rows}
    for row in vote_rows:
        mid = row["message_id"]
        option_idx = row["option_idx"]
        user_id = row["user_id"]
        opts = options_map.get(mid, [])
        if 0 <= option_idx < len(opts):
            label = opts[option_idx]
            votes_by_message[mid].setdefault(label, set()).add(user_id)

    result = []
    for r in poll_rows:
        mid = r["message_id"]
        votes = votes_by_message.get(mid, {})
        # ensure all options present even if zero votes
        for opt in options_map.get(mid, []):
            votes.setdefault(opt, set())
            
        item = dict(r)
        item["options"] = options_map[mid]
        item["votes"] = votes
        result.append(item)

    return result


async def purge_finished_polls():
    """
    Delete polls that have ended (ended = TRUE).

    Warning
    -------
    - This permanently removes historical poll rows and relies on cascade to
      remove poll_votes. Archive to another table first if you need auditing.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        await _set_stmt_timeout(conn)
        await conn.execute("DELETE FROM polls WHERE ended = TRUE")


async def record_poll_result(message_id, winners, counts, total_votes):
    """
    Mark a poll as ended and persist winners/counts/total_votes.

    Parameters
    ----------
    message_id : int
        Poll identifier (Discord message id).
    winners :
        Python object describing winners; will be JSON-serialized.
    counts :
        Python object mapping option_label -> integer count; will be JSON-serialized.
    total_votes : int
        Total number of votes cast.

    Behavior
    --------
    - Updates polls.winners, polls.counts, polls.total_votes and sets ended = TRUE.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        await _set_stmt_timeout(conn)
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


#  Poll UI  #


class PollView(discord.ui.View):
    """
    Interactive in-memory representation of a poll.

    Behavior & responsibilities
    - Maintain an in-memory view of a poll (question/options/votes as sets).
    - Render an embedded message and attach interactive controls (vote select,
      remove vote, add option, end poll).
    - Persist metadata (save_active_poll) and incremental vote changes via
      upsert_vote/delete_vote in poll_votes to avoid JSON rewrites.
    - Finalize and persist results on timeout or manual end (record_poll_result).

    Implementation notes
    - Votes are kept in-memory for display speed and to compute the embed. On
      process restart the bot should call load_active_polls() to reconstruct
      in-memory PollView objects and rehydrate votes from poll_votes.
    - The PollView code calls upsert_vote/delete_vote directly. For very high
      scale, consider separating persistence into a background worker or
      batching layer.
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

        Safety
        ------
        - If the poll has already been ended or the end_time is None, this
          coroutine returns immediately.
        - Cancelling the updater_task is safe and performed when the poll is
          manually ended.
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
        Ensure the poll is still active before processing an interaction.

        Returns True if the poll is active; otherwise informs the user and
        returns False.
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
        Cancel the background updater_task if it is still running.

        Prevents the auto-end task from performing finalization after a manual end.
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
        tuple:
            - results (dict): option -> vote count
            - winners (list): list of winning option strings
            - winner_text (str): human-readable summary for posting
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
        Persist final poll results to the database via record_poll_result.

        This method swallows exceptions to avoid blocking finalization if the DB
        is temporarily unavailable.
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
        Update the Discord message to a closed view and optionally announce winners.

        Clears interactive components and attempts to edit the original message.
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
        Finalize a poll when it times out. Safe to call multiple times.

        Steps:
        - Mark poll ended.
        - Cancel the updater task.
        - Compute results and persist them.
        - Update the message and announce winners if any.
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

        Workflow:
        - Validate the poll is active.
        - Convert the selected index to an option label.
        - Ensure each user has at most one vote (removes prior choices).
        - Persist the single vote using upsert_vote.
        - Update the message and send an ephemeral confirmation.
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

        # Persist only the single vote change (no JSON blob rewrite)
        if self.message:
            try:
                await upsert_vote(self.message.id, interaction.user.id, idx)
            except Exception as e:
                print(f"[Poll DB Save Error on vote] {e}")

        await self.update_poll(interaction, f"{CustomEmojis['VERIFIED']} You voted for **{choice_label}**")

    async def add_option(self, interaction: discord.Interaction):
        """
        Initiate the AddOptionModal to let the poll author append options.

        Permissions:
        - Only the poll creator (author) may add options. Attempts by others will
          be rejected with an ephemeral message.
        """
        if not await self._ensure_poll_active(interaction):
            return

        if interaction.user.id != self.author.id:
            return await interaction.response.send_message("⚠️ Only the poll creator can add options.", ephemeral=True)

        modal = AddOptionModal(self)
        await interaction.response.send_modal(modal)

    async def remove_vote(self, interaction: discord.Interaction):
        """
        Remove the invoking user's vote if present.

        Behavior:
        - Removes the in-memory vote and deletes the row in poll_votes.
        - Sends an ephemeral confirmation to the user.
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
                    await delete_vote(self.message.id, interaction.user.id)
                except Exception as e:
                    print(f"[Poll DB Save Error on remove] {e}")
            await self.update_poll(interaction, "❌ Your vote was removed.")
        else:
            await interaction.response.send_message("⚠️ You haven't voted yet.", ephemeral=True)

    async def end_poll(self, interaction: discord.Interaction):
        """
        Allow the poll author to end the poll immediately.

        Permissions:
        - Only the poll author may end the poll manually.

        Behavior:
        - Cancels the background updater_task and finalizes the poll.
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

        The method attempts progressively smaller embed renderings if Discord
        rejects the size due to embed field limits, and falls back to refetching
        or re-sending the message.
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
        closed : bool
            If True, the embed will indicate the poll is closed.
        bar_len : int
            Length of the textual progress bar displayed for each option.

        Returns
        -------
        discord.Embed
            The constructed embed ready to be sent or edited into the poll message.

        Notes
        -----
        - The progress bars use a small palette of emoji squares; adjust the
          palette if you want different colors or properties.
        - When total_votes == 0 the percentage for every option is displayed as 0%.
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

            embed.add_field(
                name=opt,
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

    Behavior
    --------
    - Presents five optional text fields. Non-empty fields are appended to the
      poll's options list on submit (subject to duplication and maximum checks).
    - Updates the in-memory PollView instance and persists the new state.
    - Edits the poll message to reflect newly added options.
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
        - Only the poll author may add options (checked by the caller before
          presenting the modal).
        - Maximum options limit enforced (MAX_OPTIONS defined in method).

        Side effects
        ------------
        - Updates the in-memory PollView.options and PollView.votes.
        - Recomputes the Select menu options to reflect new indices.
        - Persists the active poll via save_active_poll and edits the poll message.
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

    When submitted the modal constructs a PollView, sends the poll message, and
    persists the active poll state via save_active_poll.

    Validation rules
    ----------------
    - Requires at least two non-empty options (opt1 and opt2 are required fields).
    - Enforces uniqueness of option text (case-insensitive).
    - Option fields are trimmed for whitespace before validation.
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
        - Duplicate option strings (case-insensitive) are rejected.

        Side effects
        ------------
        - Creates a PollView and posts it to the channel where the modal was
          submitted.
        - Persists the active poll into the polls table via save_active_poll.
        - Sends an ephemeral confirmation to the user.
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