import discord
from discord.ext import commands, tasks
import itertools

class Events(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.presences = itertools.cycle([
            discord.Activity(type=discord.ActivityType.watching, name="anime avatars ✨"),
            discord.Game("with profile styles 🎭"),
            discord.Activity(type=discord.ActivityType.listening, name="your avatar requests 🎶"),
            discord.Activity(type=discord.ActivityType.watching, name="over the server 🌙")
        ])

    @commands.Cog.listener()
    async def on_ready(self):
        if not self.status_task.is_running():
            self.status_task.start()
        print(f"🟣 Presence rotation started as {self.bot.user}")

    @tasks.loop(seconds=60)  # rotates every 60s
    async def status_task(self):
        await self.bot.change_presence(activity=next(self.presences))

    def cog_unload(self):
        self.status_task.cancel()

async def setup(bot):
    await bot.add_cog(Events(bot))
    print("📦 Loaded Events cog.")
