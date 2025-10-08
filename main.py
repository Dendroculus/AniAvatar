import os
from dotenv import load_dotenv
import discord
from discord.ext import commands
import logging

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

class Minori(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix='!', intents=intents, help_command=None)
        self.logger = logging.getLogger("Minori")
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s"))
            self.logger.addHandler(handler)
        self.logger.setLevel(logging.INFO)
    
    async def setup_hook(self):
        print("Running setup_hook...")
        extensions = [
            "cogs.general", 
            "cogs.search",
            "cogs.progression", 
            "cogs.roles",
            "cogs.events",
            "cogs.games",   
            "cogs.fun",
            "cogs.errors",
            "cogs.trading",
            "cogs.admin"
        ]
        for ext in extensions:  
            try:        
                await self.load_extension(ext)
            except Exception as e:
                print(f"❌ Failed to load {ext}: {e}")
        try:
            synced = await self.tree.sync()
            print(f"🔄 Synced {len(synced)} slash commands.")
        except Exception as e:
            print(f"❌ Failed to sync slash commands: {e}")

    async def on_ready(self):   
        print(f'✅ Logged in as {self.user}')

if __name__ == "__main__":
    load_dotenv()
    TOKEN = os.getenv("DISCORD_TOKEN")

    bot = Minori()
    bot.run(TOKEN)
        
            