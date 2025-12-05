import os
import json
import random
import discord
from discord.ext import commands, tasks
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from cogs.utils.pollUtils import (
    init_db,
    load_active_polls,
    PollView,
    record_poll_result,
    purge_finished_polls,
)

"""
Events Cog - Poll restoration and presence rotation.

This module is responsible for:
- Rehydrating active polls from persistent storage on bot startup, attaching
  interactive views to existing messages where possible.
- Finalizing polls that have expired while the bot was offline (recording results).
- Providing defensive parsing and sanitization for stored poll rows whose shape
  may vary between schema versions or due to partial corruption.
- Rotating presence by sampling from a local anime list file.

Operational notes and guarantees:
- Restoration is best-effort: missing guilds/channels/messages are logged and
  expired polls are finalized without a message when necessary to ensure results
  are recorded.
- All network and I/O operations are wrapped with try/except and print statements
  to avoid preventing the bot from completing startup tasks.
- Poll vote tracking uses sets in memory for quick membership checks; persisted
  rows are parsed into lists then sanitized into integer user IDs.
- The cog avoids raising on_ready exceptions; failures are logged to stdout for
  operator inspection (this keeps the bot running even if the poll subsystem has
  issues).
"""

class Events(commands.Cog):
    """
    Cog managing event-like background behavior.

    Responsibilities:
    - Load a curated list of anime titles for periodic presence rotation.
    - On bot ready, initialize poll DB, reload active polls, attach PollView objects,
      finalize expired polls, and purge finished entries from storage.
    - Provide helper functions used during poll reconstruction and validation.

    Concurrency considerations:
    - Poll restoration runs synchronously in on_ready; PollView objects are created
      and attached to messages, which requires the bot to be fully connected.
    - All I/O with Discord (fetching members/messages) is awaited and isolated to
      prevent a single failing poll from stopping the overall restoration process.
    """
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.anime_list_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "data", "animelist.txt"
        )
        try:
            with open(self.anime_list_path, "r", encoding="utf-8") as f:
                # Expect lines like "1. Title", extract the portion after the first dot-space
                self.anime_list = [line.split(". ")[1].strip() for line in f.readlines() if ". " in line]
        except Exception:
            # If the file cannot be read, default to an empty list so presence rotation becomes a no-op.
            self.anime_list = []

    async def _parse_options(self, raw) -> list:
        """
        Robustly parse stored poll options.

        Accepts:
        - None -> []
        - list/tuple -> list copy
        - JSON-encoded string representing a list -> parsed list

        Returns an empty list for any invalid input. This defensive parsing prevents
        the restoration process from failing due to unexpected storage formats.
        """
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

    async def _parse_votes(self, raw) -> Dict[str, list]:
        """
        Parse persisted votes into a dictionary mapping option -> list of user ids.

        Accepts:
        - dict -> ensures keys and values are converted to str and list respectively
        - JSON-encoded string representing such a dict -> parsed and normalized

        Returns an empty dict for invalid input. This function does not coerce types
        of ids; that is handled later in _sanitize_votes.
        """
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

    def _sanitize_votes(self, options: list, votes_raw: Dict[str, list]) -> Dict[str, list[int]]:
        """
        Ensure votes are keyed by option strings and values are lists of integer user IDs.

        Behavior:
        - Guarantees every option in `options` has an entry in the returned dict
          (missing options receive an empty list).
        - Filters out non-integer user ids and coerces numeric-like strings to int.
        - Returns a mapping option -> list[int] suitable for counting and set conversion.

        This function protects downstream logic from malformed vote data and prevents
        exceptions during len() calls or integer conversions.
        """
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

    def _remaining_seconds(self, end_time: Optional[float]) -> Optional[int]:
        """
        Compute remaining seconds until end_time (UNIX timestamp) relative to UTC now.

        Returns None if end_time is None or invalid. Uses timezone-aware UTC timestamp
        to avoid issues with local timezone differences on the host machine.
        """
        if end_time is None:
            return None
        try:
            return int(float(end_time) - datetime.now(timezone.utc).timestamp())
        except Exception:
            return None

    def _compute_results_from_votes(self, votes_raw: Dict[str, list[int]]) -> tuple[dict[str, int], list[str]]:
        """
        Compute counts per option and determine winner(s).

        Returns:
        - counts: mapping option -> vote count (int)
        - winners: list of option(s) with the highest count (supports ties)

        Defensive behavior: handles malformed values by treating them as zero-length votes.
        """
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

    async def _get_author_member(self, guild: discord.Guild, author_id: Optional[int]) -> discord.Member:
        """
        Resolve the author_id to a Guild Member object.

        Behavior:
        - Attempts a cached lookup with guild.get_member first; falls back to fetch_member.
        - Returns guild.me on failure to provide a stable 'system' fallback (useful for
          displaying a PollView when the original author cannot be resolved).
        """
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

    async def _finalize_expired_poll(
        self,
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
        """
        Finalize a poll that has expired while the bot was offline.

        Steps:
        - Compute counts and winners.
        - Persist results via record_poll_result (best-effort; logs on failure).
        - If the original message is available, create a PollView populated with votes
          and call its timeout handler to update the message to a finalized state.

        Notes:
        - If guild or message are missing, the function still records results to avoid
          losing poll outcomes.
        - Failures in view editing are logged but do not interrupt finalization of other polls.
        """
        counts, winners = self._compute_results_from_votes(sanitized_votes)
        try:
            await record_poll_result(
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
            author_member = await self._get_author_member(guild, author_id)
            view = PollView(question=question or "Poll", options=options, author=author_member, timeout=None)
            view.votes = {opt: set(uids) for opt, uids in sanitized_votes.items()}
            try:
                view.end_time = datetime.fromtimestamp(float(end_time), timezone.utc) if end_time else None
            except Exception:
                view.end_time = None
            view.message = msg
            # Trigger the same code path that runs when a PollView naturally times out.
            await view.on_timeout()
            print(f"[Poll Reload] finalized expired poll {message_id} (edited message).")
        except Exception as e:
            print(f"[Poll Reload] failed to finalize expired poll {message_id} via message edit: {e}")

    async def _restore_active_poll(
        self,
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
        """
        Restore an active poll into memory and re-attach its interactive view.

        Behavior:
        - Creates a PollView with the remaining timeout and current votes.
        - If the message object is available, attempts to edit the message to attach the view.
        - If the message is missing, the view is kept in memory (so voting won't work),
          but an informational log is emitted to aid operators in troubleshooting.
        """
        try:
            author_member = await self._get_author_member(guild, author_id)
            view = PollView(
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

    @staticmethod
    def _is_expired(remaining_seconds: Optional[int]) -> bool:
        """Return True if remaining_seconds indicates the poll should be considered expired."""
        return remaining_seconds is not None and remaining_seconds <= 0

    def _get_guild(self, guild_id: Optional[int]) -> Optional[discord.Guild]:
        """
        Resolve a guild id to a Guild object using the bot's internal cache.

        Returns None if the guild is not present in cache (e.g., bot not a member).
        """
        try:
            return self.bot.get_guild(int(guild_id)) if guild_id is not None else None
        except Exception:
            return None

    @staticmethod
    def _get_channel(guild: discord.Guild, channel_id: Optional[int]) -> Optional[discord.abc.GuildChannel]:
        """
        Resolve a channel id to a GuildChannel via guild.get_channel.

        Returns None if the channel is not found (deleted or bot lacks access).
        """
        try:
            return guild.get_channel(int(channel_id)) if channel_id is not None else None
        except Exception:
            return None

    @staticmethod
    async def _try_fetch_message(channel: Optional[discord.TextChannel], message_id: int) -> Optional[discord.Message]:
        """
        Attempt to fetch a message from a channel; return None when the message is not found.

        The method swallows exceptions and logs a concise message to aid operators.
        """
        if not channel:
            return None
        try:
            return await channel.fetch_message(int(message_id))
        except Exception:
            print(f"[Poll Reload] message {message_id} not found in channel {channel.id}.")
            return None

    async def _finalize_or_restore(
        self,
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
        """
        Decide whether to finalize an expired poll or restore an active one.

        Delegates to _finalize_expired_poll or _restore_active_poll based on remaining_seconds.
        Performs minimal validation (e.g., guild presence) before attempting restore.
        """
        if self._is_expired(remaining_seconds):
            await self._finalize_expired_poll(
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
            await self._restore_active_poll(
                guild=guild,
                msg=msg,
                message_id=message_id,
                question=question,
                options=options,
                sanitized_votes=sanitized_votes,
                remaining_seconds=remaining_seconds,
                author_id=author_id,
            )

    async def _reconstruct_poll(self, row: Dict[str, Any]) -> None:
        """
        Rehydrate a single stored poll row.

        Steps:
        - Extract fields with defensive fallbacks.
        - Skip if the row is marked ended.
        - Parse and sanitize options and votes.
        - Resolve guild and channel; fetch the message if possible.
        - Either finalize (if expired) or restore (if active).

        This function is intentionally tolerant of missing/invalid fields so a single
        malformed row does not abort the entire restoration process.
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

        options = await self._parse_options(options_json)
        votes_raw = await self._parse_votes(votes_json)
        sanitized_votes = self._sanitize_votes(options, votes_raw)
        remaining_seconds = self._remaining_seconds(end_time)

        guild = self._get_guild(guild_id)
        if not guild:
            print(f"[Poll Reload] guild {guild_id} not found for poll {message_id}, skipping restore.")
            if self._is_expired(remaining_seconds):
                await self._finalize_expired_poll(
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

        channel = self._get_channel(guild, channel_id)
        if not channel:
            print(f"[Poll Reload] channel {channel_id} not found in guild {guild.id} for poll {message_id}, skipping.")
            if self._is_expired(remaining_seconds):
                await self._finalize_expired_poll(
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

        msg = await self._try_fetch_message(channel, message_id)
        await self._finalize_or_restore(
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

    @commands.Cog.listener()
    async def on_ready(self):
        """
        Startup hook that initializes the poll database and attempts to restore state.

        Sequence:
        1. init_db - prepare storage (best-effort).
        2. load_active_polls - retrieve rows describing polls that were active before restart.
        3. For each row, attempt reconstruction (restore or finalize).
        4. purge_finished_polls - clean up any leftover finished entries.
        5. Start the status_task loop for presence rotation if not already running.

        Rationale:
        - Performing purge_finished_polls after restoration minimizes race windows where
          a poll may be removed while being processed.
        - All operations are guarded so on_ready completes even if poll subsystem errors occur.
        """
        try:
            await init_db()
        except Exception as e:
            print(f"[DB Init Error] {e}")

        try:
            rows = await load_active_polls()
        except Exception as e:
            print(f"[Poll Reload Error - load_active_polls] {e}")
            rows = []

        for row in rows:
            try:
                await self._reconstruct_poll(row)
            except Exception as e:
                print(f"[Poll Reload] unexpected error reconstructing a poll: {e}")

        try:
            await purge_finished_polls()
        except Exception as e:
            print(f"[Poll Reload] failed to purge finished polls: {e}")

        if not self.status_task.is_running():
            self.status_task.start()
        print(f"🟣 Presence rotation started as {self.bot.user} | {len(self.anime_list)} titles loaded")

    @tasks.loop(seconds=1200)
    async def status_task(self):
        """
        Periodically rotate bot presence.

        Behavior:
        - If anime_list is empty the task becomes a no-op to avoid changing presence.
        - Uses a WATCHING activity for consistent appearance.
        - Exceptions when changing presence are suppressed because failures here are
          cosmetic and should not affect other functionalities.
        """
        if not self.anime_list:
            return
        anime = random.choice(self.anime_list)
        try:
            await self.bot.change_presence(
                activity=discord.Activity(type=discord.ActivityType.watching, name=anime)
            )
        except Exception:
            # Ignore presence-setting errors (rate limits, missing intents, etc.)
            pass

    def cog_unload(self):
        """
        Clean shutdown for the cog: cancel the periodic status task.

        The method swallows exceptions as the bot teardown sequence may already
        be in an inconsistent state where cancelling tasks can raise.
        """
        try:
            self.status_task.cancel()
        except Exception:
            pass

async def setup(bot: commands.Bot):
    await bot.add_cog(Events(bot))