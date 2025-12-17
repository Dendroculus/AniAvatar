import os
from dotenv import load_dotenv
import discord
from discord.ext import commands
import logging
from cogs.utils.logging_setup import setup_logging

"""
main.py

Entrypoint for the Minori Discord bot.

Responsibilities:
- Configure logging using cogs.utils.logging_setup.setup_logging.
- Define Discord intents required by the bot.
- Provide the Minori Bot subclass which loads extensions and syncs application commands.
- Load the DISCORD_TOKEN from environment (via python-dotenv) and run the bot.

Notes:
- This module intentionally does not modify runtime behavior; only docstrings/comments were added.
- Extensions loaded in setup_hook should correspond to available cogs in the cogs/ package.
"""

setup_logging(
    level=logging.INFO,
    console_format="%(levelname)s %(name)s: %(message)s",
    text_log_file="bot.log",
    text_use_timed_rotation=True,
    json_enabled=True,
    json_log_file="bot.jsonl",  
)

# Configure intents: members and message_content are required by several features/cogs.
intents = discord.Intents.default()
intents.members = True
intents.message_content = True

class Minori(commands.AutoShardedBot):
    """
    Main Bot subclass for the Minori/AniAvatar application.

    This class centralizes startup tasks:
    - Sets up a logger for the bot.
    - Loads extensions in setup_hook and attempts to sync application (slash) commands.
    - Logs when the bot is ready in on_ready.

    The command_prefix is '!' for legacy (text) commands and help_command is disabled to
    allow custom help implementations inside cogs.
    """
    def __init__(self):
        super().__init__(command_prefix='!', intents=intents, help_command=None)
        self.logger = logging.getLogger("Minori")
        self.logger.setLevel(logging.INFO)

    async def setup_hook(self):
        """
        Async setup hook run by discord.py during bot startup.

        Responsibilities:
        - Load a predefined list of extensions (cogs).
        - Log successes and exceptions during extension loading.
        - Attempt to sync application (slash) commands with Discord and log the result.

        If an extension fails to load, the exception is logged but loading continues for others.
        """
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
        """
        Event handler called when the bot has connected and is ready.

        Logs the bot user information at INFO level.
        """
        self.logger.info("Logged in as %s", self.user, extra={"user": str(self.user)})

if __name__ == "__main__":
    # Load environment variables from .env PERSONAL NOTE: PLEASE ADD YOUR .env FILE TO .gitignore 
    load_dotenv()
    TOKEN = os.getenv("DISCORD_TOKEN")
    
    # Keep the bot alive if running in an environment that may sleep    
    bot = Minori()
    bot.run(TOKEN)