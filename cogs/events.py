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

class Events(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.anime_list_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "data", "animelist.txt"
        )
        try:
            with open(self.anime_list_path, "r", encoding="utf-8") as f:
                self.anime_list = [line.split(". ")[1].strip() for line in f.readlines() if ". " in line]
        except Exception:
            self.anime_list = []

    async def _parse_options(self, raw) -> list:
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
        if end_time is None:
            return None
        try:
            return int(float(end_time) - datetime.now(timezone.utc).timestamp())
        except Exception:
            return None

    def _compute_results_from_votes(self, votes_raw: Dict[str, list[int]]) -> tuple[dict[str, int], list[str]]:
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
        return remaining_seconds is not None and remaining_seconds <= 0

    def _get_guild(self, guild_id: Optional[int]) -> Optional[discord.Guild]:
        try:
            return self.bot.get_guild(int(guild_id)) if guild_id is not None else None
        except Exception:
            return None

    @staticmethod
    def _get_channel(guild: discord.Guild, channel_id: Optional[int]) -> Optional[discord.abc.GuildChannel]:
        try:
            return guild.get_channel(int(channel_id)) if channel_id is not None else None
        except Exception:
            return None

    @staticmethod
    async def _try_fetch_message(channel: Optional[discord.TextChannel], message_id: int) -> Optional[discord.Message]:
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
        if not self.anime_list:
            return
        anime = random.choice(self.anime_list)
        try:
            await self.bot.change_presence(
                activity=discord.Activity(type=discord.ActivityType.watching, name=anime)
            )
        except Exception:
            pass

    def cog_unload(self):
        try:
            self.status_task.cancel()
        except Exception:
            pass

async def setup(bot: commands.Bot):
    await bot.add_cog(Events(bot))