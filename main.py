import os
from dotenv import load_dotenv
import discord
from discord.ext import commands

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

class AniAvatar(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix='!', intents=intents, help_command=None)

    async def setup_hook(self):
        print("Running setup_hook...")
        extensions = [
            "cogs.general",
            "cogs.search",
            "cogs.events"
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

    bot = AniAvatar()
    bot.run(TOKEN)

