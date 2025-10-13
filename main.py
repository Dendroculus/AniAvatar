import os
from dotenv import load_dotenv
import discord
from discord.ext import commands
import logging
from cogs.utils.logging_setup import setup_logging

setup_logging(
    level=logging.INFO,
    console_format="%(levelname)s %(name)s: %(message)s",
    text_log_file="bot.log",
    text_use_timed_rotation=True,
    json_enabled=True,
    json_log_file="bot.jsonl",
)

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

class Minori(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix='!', intents=intents, help_command=None)
        self.logger = logging.getLogger("Minori")
        self.logger.setLevel(logging.INFO)

    async def setup_hook(self):
        self.logger.info("Running setup_hook...", extra={"phase": "startup"})
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
            "cogs.admin",
        ]
        for ext in extensions:
            try:
                await self.load_extension(ext)
                self.logger.info("Loaded %s", ext, extra={"extension": ext})
            except Exception:
                self.logger.exception("Failed to load extension", extra={"extension": ext})
        try:
            synced = await self.tree.sync()
            self.logger.info("Synced %d slash commands.", len(synced), extra={"synced_count": len(synced)})
        except Exception:
            self.logger.exception("Failed to sync slash commands")

    async def on_ready(self):
        self.logger.info("Logged in as %s", self.user, extra={"user": str(self.user)})

if __name__ == "__main__":
    load_dotenv()
    TOKEN = os.getenv("DISCORD_TOKEN")
    bot = Minori()
    bot.run(TOKEN)