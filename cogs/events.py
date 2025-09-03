import discord
from discord.ext import commands, tasks
import random
import os

class Events(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.anime_list_path = os.path.join(os.path.dirname(__file__), "..", "data", "animelist.txt")
        with open(self.anime_list_path, "r", encoding="utf-8") as f:
            self.anime_list = [line.split(". ")[1].strip() for line in f.readlines()]

    @commands.Cog.listener()
    async def on_ready(self):
        if not self.status_task.is_running():
            self.status_task.start()
        print(f"🟣 Presence rotation started as {self.bot.user}")

    @tasks.loop(seconds=1200)  # rotates/60s
    async def status_task(self):
        anime = random.choice(self.anime_list)
        await self.bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name=anime))

    def cog_unload(self):
        self.status_task.cancel()

async def setup(bot):
    await bot.add_cog(Events(bot))
    print("📦 Loaded Events cog.")
