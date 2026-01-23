import asyncio
import asyncpg
import discord
import json
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any, Tuple
from discord import ui
from discord.ext import commands
from constants.emojis import MinoriEmojis, CustomEmojis
from constants.configs import PollingConstants as POLCONST

from utils.pollings_db import (
    PollData,
    save_active_poll,
    upsert_vote,
    delete_vote,
    record_poll_result,
)

"""
pollings.py

Purpose
-------
UI helpers and Business Logic for the bot's polling subsystem.

This module consumes `poll_db.py` to handle persistence but focuses on:
- Interactive Discord Views (PollView)
- Modals (Create/Add Options)
- Reconstructing poll state from raw DB rows
- Managing poll timers and live updates
"""

#  Poll Reconstruction Logic  #

async def _parse_options(raw) -> list:
    """Robustly parse stored poll options."""
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        return list(raw)
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, (list, tuple)):
                return list(parsed)
        except Exception:
            return []
    return []

async def _parse_votes(raw) -> Dict[str, list]:
    """Parse persisted votes into a dictionary mapping option -> list of user ids."""
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return {str(k): list(v) for k, v in raw.items()}
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return {str(k): list(v) for k, v in parsed.items()}
        except Exception:
            return {}
    return {}

def _sanitize_votes(options: list, votes_raw: Dict[str, list]) -> Dict[str, list[int]]:
    """Ensure votes are keyed by option strings and values are lists of integer user IDs."""
    for opt in options:
        votes_raw.setdefault(opt, [])
    sanitized: Dict[str, list[int]] = {}
    for opt, uids in votes_raw.items():
        out = []
        if isinstance(uids, (list, tuple)):
            for uid in uids:
                try:
                    out.append(int(uid))
                except Exception:
                    continue
        else:
            try:
                out.append(int(uids))
            except Exception:
                pass
        sanitized[str(opt)] = out
    return sanitized

def _remaining_seconds(end_time: Optional[float]) -> Optional[int]:
    """Compute remaining seconds until end_time (UNIX timestamp) relative to UTC now."""
    if end_time is None:
        return None
    try:
        return int(float(end_time) - datetime.now(timezone.utc).timestamp())
    except Exception:
        return None

def _compute_results_from_votes(votes_raw: Dict[str, list[int]]) -> Tuple[dict[str, int], list[str]]:
    """Compute counts per option and determine winner(s)."""
    counts: dict[str, int] = {}
    if not votes_raw:
        return counts, []
    for opt, uids in votes_raw.items():
        try:
            size = len(uids) if uids is not None else 0
        except TypeError:
            size = 0
        counts[str(opt)] = int(size)
    winners = []
    if counts:
        max_votes = max(counts.values())
        winners = [opt for opt, c in counts.items() if c == max_votes]
    return counts, winners

async def _get_author_member(guild: discord.Guild, author_id: Optional[int]) -> discord.Member:
    """Resolve the author_id to a Guild Member object."""
    if author_id:
        try:
            member = guild.get_member(int(author_id))
            if not member:
                member = await guild.fetch_member(int(author_id))
            if member:
                return member
        except Exception:
            pass
    return guild.me

def _get_guild(bot: commands.Bot, guild_id: Optional[int]) -> Optional[discord.Guild]:
    """Resolve a guild id to a Guild object using the bot's internal cache."""
    try:
        return bot.get_guild(int(guild_id)) if guild_id is not None else None
    except Exception:
        return None

def _get_channel(guild: discord.Guild, channel_id: Optional[int]) -> Optional[discord.abc.GuildChannel]:
    """Resolve a channel id to a GuildChannel via guild.get_channel."""
    try:
        return guild.get_channel(int(channel_id)) if channel_id is not None else None
    except Exception:
        return None

async def _try_fetch_message(channel: Optional[discord.TextChannel], message_id: int) -> Optional[discord.Message]:
    """Attempt to fetch a message from a channel; return None when the message is not found."""
    if not channel:
        return None
    try:
        return await channel.fetch_message(int(message_id))
    except Exception:
        print(f"[Poll Reload] message {message_id} not found in channel {channel.id}.")
        return None

def _is_expired(remaining_seconds: Optional[int]) -> bool:
    """Return True if remaining_seconds indicates the poll should be considered expired."""
    return remaining_seconds is not None and remaining_seconds <= 0

async def _finalize_expired_poll(
    bot: commands.Bot,
    *,
    guild: Optional[discord.Guild],
    msg: Optional[discord.Message],
    message_id: int,
    question: str,
    options: list,
    sanitized_votes: Dict[str, list[int]],
    end_time: Optional[float],
    author_id: Optional[int],
) -> None:
    """Finalize a poll that has expired while the bot was offline."""
    counts, winners = _compute_results_from_votes(sanitized_votes)
    try:
        await record_poll_result(
            bot.pool,
            message_id=message_id,
            winners=winners,
            counts=counts,
            total_votes=sum(counts.values()),
        )
    except Exception as e:
        print(f"[Poll Reload] failed to record result for expired poll {message_id}: {e}")

    if not msg:
        print(f"[Poll Reload] expired poll {message_id} finalized without message (no message to edit).")
        return

    try:
        assert guild is not None
        author_member = await _get_author_member(guild, author_id)
        view = PollView(bot.pool, question=question or "Poll", options=options, author=author_member, timeout=None)
        view.votes = {opt: set(uids) for opt, uids in sanitized_votes.items()}
        try:
            view.end_time = datetime.fromtimestamp(float(end_time), timezone.utc) if end_time else None
        except Exception:
            view.end_time = None
        view.message = msg
        await view.on_timeout()
        print(f"[Poll Reload] finalized expired poll {message_id} (edited message).")
    except Exception as e:
        print(f"[Poll Reload] failed to finalize expired poll {message_id} via message edit: {e}")

async def _restore_active_poll(
    bot: commands.Bot,
    *,
    guild: discord.Guild,
    msg: Optional[discord.Message],
    message_id: int,
    question: str,
    options: list,
    sanitized_votes: Dict[str, list[int]],
    remaining_seconds: Optional[int],
    author_id: Optional[int],
) -> None:
    """Restore an active poll into memory and re-attach its interactive view."""
    try:
        author_member = await _get_author_member(guild, author_id)
        view = PollView(
            bot.pool,
            question=question or "Poll",
            options=options,
            author=author_member,
            timeout=remaining_seconds,
        )
        view.votes = {opt: set(uids) for opt, uids in sanitized_votes.items()}
        if msg:
            view.message = msg
            try:
                await msg.edit(view=view)
            except Exception as e:
                print(f"[Poll Reload] failed to attach view to message {message_id}: {e}")
        else:
            print(f"[Poll Reload] message not found for active poll {message_id}; view created in memory only.")
        print(f"♻️ Reloaded poll {message_id} (remaining: {remaining_seconds}s).")
    except Exception as e:
        print(f"[Poll Reload Error] failed to restore active poll {message_id}: {e}")

async def _finalize_or_restore(
    bot: commands.Bot,
    *,
    guild: Optional[discord.Guild],
    msg: Optional[discord.Message],
    message_id: int,
    question: str,
    options: list,
    sanitized_votes: Dict[str, list[int]],
    remaining_seconds: Optional[int],
    end_time: Optional[float],
    author_id: Optional[int],
) -> None:
    """Decide whether to finalize an expired poll or restore an active one."""
    if _is_expired(remaining_seconds):
        await _finalize_expired_poll(
            bot,
            guild=guild,
            msg=msg,
            message_id=message_id,
            question=question,
            options=options,
            sanitized_votes=sanitized_votes,
            end_time=end_time,
            author_id=author_id,
        )
    else:
        if guild is None:
            print(f"[Poll Reload] cannot restore active poll {message_id} without guild.")
            return
        await _restore_active_poll(
            bot,
            guild=guild,
            msg=msg,
            message_id=message_id,
            question=question,
            options=options,
            sanitized_votes=sanitized_votes,
            remaining_seconds=remaining_seconds,
            author_id=author_id,
        )

async def reconstruct_poll(bot: commands.Bot, row: Dict[str, Any]) -> None:
    """
    Rehydrate a single stored poll row.
    """
    try:
        message_id = row.get("message_id")
        guild_id = row.get("guild_id")
        channel_id = row.get("channel_id")
        author_id = row.get("author_id")
        question = (row.get("question") or "Poll")
        options_json = row.get("options")
        votes_json = row.get("votes")
        end_time = row.get("end_time")
        ended = row.get("ended")
    except Exception:
        print("[Poll Reload] skipping row due to unexpected shape:", row)
        return

    if ended:
        return

    options = await _parse_options(options_json)
    votes_raw = await _parse_votes(votes_json)
    sanitized_votes = _sanitize_votes(options, votes_raw)
    remaining_seconds = _remaining_seconds(end_time)

    guild = _get_guild(bot, guild_id)
    if not guild:
        print(f"[Poll Reload] guild {guild_id} not found for poll {message_id}, skipping restore.")
        if _is_expired(remaining_seconds):
            await _finalize_expired_poll(
                bot,
                guild=None,
                msg=None,
                message_id=message_id,
                question=question,
                options=options,
                sanitized_votes=sanitized_votes,
                end_time=end_time,
                author_id=author_id,
            )
        return

    channel = _get_channel(guild, channel_id)
    if not channel:
        print(f"[Poll Reload] channel {channel_id} not found in guild {guild.id} for poll {message_id}, skipping.")
        if _is_expired(remaining_seconds):
            await _finalize_expired_poll(
                bot,
                guild=guild,
                msg=None,
                message_id=message_id,
                question=question,
                options=options,
                sanitized_votes=sanitized_votes,
                end_time=end_time,
                author_id=author_id,
            )
        return

    msg = await _try_fetch_message(channel, message_id)
    await _finalize_or_restore(
        bot,
        guild=guild,
        msg=msg,
        message_id=message_id,
        question=question,
        options=options,
        sanitized_votes=sanitized_votes,
        remaining_seconds=remaining_seconds,
        end_time=end_time,
        author_id=author_id,
    )


class PollView(discord.ui.View):
    """
    Interactive in-memory representation of a poll.
    """

    def __init__(self, pool: asyncpg.Pool, question: str, options: List[str], author: discord.Member, timeout: Optional[int] = None):
        super().__init__(timeout=timeout)
        self.pool = pool
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
        Ensure the poll is still active before processing an interaction.
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
        """
        try:
            await record_poll_result(
                self.pool,
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
                await upsert_vote(self.pool, self.message.id, interaction.user.id, idx)
            except Exception as e:
                print(f"[Poll DB Save Error on vote] {e}")

        await self.update_poll(interaction, f"{CustomEmojis['VERIFIED']} You voted for **{choice_label}**")

    async def add_option(self, interaction: discord.Interaction):
        """
        Initiate the AddOptionModal to let the poll author append options.
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
                    await delete_vote(self.pool, self.message.id, interaction.user.id)
                except Exception as e:
                    print(f"[Poll DB Save Error on remove] {e}")
            await self.update_poll(interaction, "❌ Your vote was removed.")
        else:
            await interaction.response.send_message("⚠️ You haven't voted yet.", ephemeral=True)

    async def end_poll(self, interaction: discord.Interaction):
        """
        Allow the poll author to end the poll immediately.
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
        """
        embed = self.make_poll_embed()
        if self.message:
            try:
                await self.message.edit(embed=embed, view=self)
            except discord.errors.HTTPException as e:
                # Retry logic for embed size limits
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
            except Exception :
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
    """
    opt1 = ui.TextInput(label="Option 1 (optional)", required=False, max_length=100,
                        placeholder=POLCONST.MODAL_PLACEHOLDER)
    opt2 = ui.TextInput(label="Option 2 (optional)", required=False, max_length=100,
                        placeholder=POLCONST.MODAL_PLACEHOLDER)
    opt3 = ui.TextInput(label="Option 3 (optional)", required=False, max_length=100,
                        placeholder=POLCONST.MODAL_PLACEHOLDER)
    opt4 = ui.TextInput(label="Option 4 (optional)", required=False, max_length=100,
                        placeholder=POLCONST.MODAL_PLACEHOLDER)
    opt5 = ui.TextInput(label="Option 5 (optional)", required=False, max_length=100,
                        placeholder=POLCONST.MODAL_PLACEHOLDER)

    def __init__(self, poll_view: "PollView"):
        super().__init__()
        self.poll_view = poll_view
        self.description = "Note: Discord only allows a maximum of 25 options per select menu."

    async def on_submit(self, interaction: discord.Interaction):
        """
        Handle submission of new options.
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
            data = PollData(
                message_id=self.poll_view.message.id,
                guild_id=self.poll_view.message.guild.id,
                channel_id=self.poll_view.message.channel.id,
                author_id=self.poll_view.author.id,
                question=self.poll_view.question,
                options=self.poll_view.options,
                end_time=self.poll_view.end_time
            )
            await save_active_poll(self.poll_view.pool, data)
        except Exception as e:
            print(f"[Poll DB Save Error on add_option] {e}")

        await interaction.response.send_message(
            f"{CustomEmojis['VERIFIED']} Added {len(new_opts)} option(s). Total options: {len(self.poll_view.options)}",
            ephemeral=True
        )


class PollInputModal(ui.Modal, title="Create Poll"):
    """
    Modal used to create a new poll.
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
            pool = self.ctx.bot.pool
            view = PollView(pool, self.question.value, opts, self.ctx.author, timeout=self.timeout_seconds)
            embed = view.make_poll_embed()
            msg = await interaction.channel.send(embed=embed, view=view)
            view.message = msg
            end_time = (datetime.now(timezone.utc) + timedelta(seconds=self.timeout_seconds)) if self.timeout_seconds else None
            
            data = PollData(
                message_id=msg.id,
                guild_id=interaction.guild.id,
                channel_id=interaction.channel.id,
                author_id=interaction.user.id,
                question=self.question.value,
                options=opts,
                end_time=end_time
            )
            await save_active_poll(pool, data)

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