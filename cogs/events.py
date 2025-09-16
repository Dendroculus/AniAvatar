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
    
    
    # Rules
    # @commands.Cog.listener()
    # async def on_ready(self):
    #     if not self.status_task.is_running():
    #         self.status_task.start()
    #     print(f"🟣 Presence rotation started as {self.bot.user}")

    #     channel = discord.utils.get(self.bot.get_all_channels(), name="rules")
    #     if channel:
    #         rules_message = (
    #             "<:Scroll:1417358440174719047> Server Rules\n\n"
    #             "<:MinoriSmile:1415203661616906321> Be respectful — no harassment, hate speech, or bullying.\n"
    #             "<:MinoriConfused:ID> No NSFW, illegal content, or spam.\n"
    #             "<:MinoriWink:1414901802314371163> Keep discussions safe and friendly.\n"
    #             "<:MinoriDissapointed:1416018383278968914> Follow Discord’s Terms of Service & Community Guidelines.\n"
    #             "<:Globe:1417358558873518172> English is preferred so everyone can understand.\n\n"
    #             "Breaking these rules may result in warnings or removal from the server.\n"
    #             "Thanks for keeping this place safe!"
    #         )
    #         try:
    #             await channel.send(rules_message)
    #         except discord.Forbidden:
    #             print("⚠️ I don't have permission to send messages in #rules.")

