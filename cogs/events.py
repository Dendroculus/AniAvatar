import discord
from discord.ext import commands, tasks
import random
import os
import json
from datetime import datetime, timezone
from cogs.utils.pollUtils import init_db, load_active_polls, PollView

class Events(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.anime_list_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "data", "animelist.txt"
        )
        with open(self.anime_list_path, "r", encoding="utf-8") as f:
            self.anime_list = [line.split(". ")[1].strip() for line in f.readlines()]

    @commands.Cog.listener()
    async def on_ready(self):
        try:
            await init_db()
        except Exception as e:
            print(f"[DB Init Error] {e}")

        if not self.status_task.is_running():
            self.status_task.start()
        print(f"🟣 Presence rotation started as {self.bot.user} | {len(self.anime_list)} titles loaded")

        try:
            rows = await load_active_polls()
        except Exception as e:
            print(f"[Poll Reload Error - load_active_polls] {e}")
            rows = []

        for row in rows:
            (
                message_id, guild_id, channel_id,
                question, options_json, votes_json,
                end_time, ended, *_  
            ) = row

            if ended:
                continue

            try:
                guild = self.bot.get_guild(guild_id)
                channel = guild.get_channel(channel_id) if guild else None
                if not channel:
                    continue

                msg = await channel.fetch_message(message_id)

                options = json.loads(options_json)
                votes_raw = json.loads(votes_json)
                votes = {opt: set(uids) for opt, uids in votes_raw.items()}

                timeout = None
                if end_time:
                    try:
                        remaining = int(float(end_time) - datetime.now(timezone.utc).timestamp())
                        timeout = remaining if remaining > 0 else None
                    except Exception:
                        timeout = None

                view = PollView(
                    question=question,
                    options=options,
                    author=msg.guild.me,  
                    timeout=timeout
                )
                view.message = msg
                view.votes = votes

                await msg.edit(view=view)  
                print(f"♻️ Reloaded poll {message_id}")

            except Exception as e:
                print(f"[Poll Reload Error] {e}")

    @tasks.loop(seconds=1200)  # every 20 minutes
    async def status_task(self):
        anime = random.choice(self.anime_list)
        await self.bot.change_presence(
            activity=discord.Activity(type=discord.ActivityType.watching, name=anime)
        )

    def cog_unload(self):
        self.status_task.cancel()

async def setup(bot):
    await bot.add_cog(Events(bot))
    print("📦 Loaded Events cog.")
