# cogs/events.py
import os
import json
import random
import discord
from discord.ext import commands, tasks
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict

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

    def _compute_results_from_votes(self, votes_raw) -> tuple[dict[str, int], list[str]]:
        counts: dict[str, int] = {}
        if not votes_raw:
            return counts, []

        for opt, uids in votes_raw.items():
            try:
                size = len(uids) if uids is not None else 0
            except TypeError:
                size = 0
            counts[str(opt)] = int(size)

        if counts:
            max_votes = max(counts.values())
            winners = [opt for opt, c in counts.items() if c == max_votes]
        else:
            winners = []
        return counts, winners

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
                message_id = row.get("message_id")
                guild_id = row.get("guild_id")
                channel_id = row.get("channel_id")
                author_id = row.get("author_id")
                question = row.get("question")
                options_json = row.get("options")
                votes_json = row.get("votes")
                end_time = row.get("end_time")
                ended = row.get("ended")
            except Exception:
                print("[Poll Reload] skipping row due to unexpected shape:", row)
                continue

            if ended:
                continue

            options = await self._parse_options(options_json)
            votes_raw = await self._parse_votes(votes_json)
            for opt in options:
                votes_raw.setdefault(opt, [])

            sanitized_votes = {}
            for opt, uids in votes_raw.items():
                sanitized_list = []
                if isinstance(uids, (list, tuple)):
                    for uid in uids:
                        try:
                            sanitized_list.append(int(uid))
                        except Exception:
                            continue
                else:
                    try:
                        sanitized_list.append(int(uids))
                    except Exception:
                        pass
                sanitized_votes[str(opt)] = sanitized_list

            remaining_seconds: Optional[int] = None
            if end_time is not None:
                try:
                    remaining_seconds = int(float(end_time) - datetime.now(timezone.utc).timestamp())
                except Exception:
                    remaining_seconds = None

            try:
                guild = self.bot.get_guild(int(guild_id)) if guild_id is not None else None
            except Exception:
                guild = None

            if not guild:
                print(f"[Poll Reload] guild {guild_id} not found for poll {message_id}, skipping restore.")
                if remaining_seconds is not None and remaining_seconds <= 0:
                    counts, winners = self._compute_results_from_votes(sanitized_votes)
                    try:
                        await record_poll_result(message_id=message_id, winners=winners, counts=counts, total_votes=sum(counts.values()))
                    except Exception as e:
                        print(f"[Poll Reload] failed to record result for missing-guild poll {message_id}: {e}")
                continue

            channel = guild.get_channel(int(channel_id)) if channel_id is not None else None
            if not channel:
                print(f"[Poll Reload] channel {channel_id} not found in guild {guild.id} for poll {message_id}, skipping.")
                if remaining_seconds is not None and remaining_seconds <= 0:
                    counts, winners = self._compute_results_from_votes(sanitized_votes)
                    try:
                        await record_poll_result(message_id=message_id, winners=winners, counts=counts, total_votes=sum(counts.values()))
                    except Exception as e:
                        print(f"[Poll Reload] failed to record result for missing-channel poll {message_id}: {e}")
                continue

            try:
                msg = await channel.fetch_message(int(message_id))
            except Exception:
                print(f"[Poll Reload] message {message_id} not found in channel {channel.id}.")
                msg = None

            if remaining_seconds is not None and remaining_seconds <= 0:
                counts, winners = self._compute_results_from_votes(sanitized_votes)
                try:
                    await record_poll_result(message_id=message_id, winners=winners, counts=counts, total_votes=sum(counts.values()))
                except Exception as e:
                    print(f"[Poll Reload] failed to record result for expired poll {message_id}: {e}")

                if msg:
                    try:
                        author_member = None
                        if author_id:
                            try:
                                author_member = guild.get_member(int(author_id))
                                if not author_member:
                                    author_member = await guild.fetch_member(int(author_id))
                            except Exception:
                                author_member = None
                        if not author_member:
                            author_member = guild.me

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
                else:
                    print(f"[Poll Reload] expired poll {message_id} finalized without message (no message to edit).")
                continue

            try:
                author_member = None
                if author_id:
                    try:
                        author_member = guild.get_member(int(author_id))
                        if not author_member:
                            author_member = await guild.fetch_member(int(author_id))
                    except Exception:
                        author_member = None
                if not author_member:
                    author_member = guild.me

                view = PollView(question=question or "Poll", options=options, author=author_member, timeout=remaining_seconds)
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
    print("📦 Loaded Events cog.")
