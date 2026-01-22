from dotenv import load_dotenv
import discord
from discord.ext import commands
import logging
import aiohttp
import asyncpg
from loggers.bot_logging import setup_logging
from constants.configs import DISCORD_TOKEN, DATABASE

"""
main.py

Entrypoint for the Minori Discord bot.

Responsibilities:
- Configure logging using cogs.utils.logging_setup.setup_logging.
- Define Discord intents required by the bot.
- Provide the Minori Bot subclass which loads extensions and syncs application commands.
- Centralize resource management (HTTP Session, DB Pool).
- Load the DISCORD_TOKEN from environment and run the bot.
"""

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

class Minori(commands.AutoShardedBot):
    """
    Main Bot subclass for the Minori/AniAvatar application.

    This class centralizes startup tasks and resource management:
    - Sets up a logger for the bot.
    - Initializes shared resources (aiohttp Session, asyncpg Pool) in setup_hook.
    - Loads extensions and attempts to sync application (slash) commands.
    - Cleans up resources in close().
    """
    def __init__(self):
        super().__init__(command_prefix='!', intents=intents, help_command=None)
        self.logger = logging.getLogger("Minori")
        self.logger.setLevel(logging.INFO)
        
        self.session: aiohttp.ClientSession = None
        self.pool: asyncpg.Pool = None

    async def setup_hook(self):
        """
        Async setup hook run by discord.py during bot startup.

        Responsibilities:
        - Initialize aiohttp.ClientSession and asyncpg.Pool.
        - Load a predefined list of extensions (cogs).
        - Log successes and exceptions during extension loading.
        - Attempt to sync application (slash) commands.
        """
        self.logger.info("Running setup_hook...", extra={"phase": "startup"})

        try:
            self.session = aiohttp.ClientSession()
            self.logger.info("aiohttp.ClientSession initialized.")
        except Exception:
            self.logger.exception("Failed to initialize aiohttp session")
            raise

        try:
            # Assumes DATABASE is a valid postgres connection string/DSN
            self.pool = await asyncpg.create_pool(DATABASE)
            self.logger.info("asyncpg Connection Pool initialized.")
        except Exception:
            self.logger.exception("Failed to initialize database pool")
            raise

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

    async def close(self):
        """
        Cleanup resources on shutdown.
        """
        if self.session:
            await self.session.close()
            self.logger.info("aiohttp.ClientSession closed.")
        
        if self.pool:
            await self.pool.close()
            self.logger.info("asyncpg Connection Pool closed.")
            
        await super().close()

    async def on_ready(self):
        """
        Event handler called when the bot has connected and is ready.
        """
        self.logger.info("Logged in as %s", self.user, extra={"user": str(self.user)})

if __name__ == "__main__":
    load_dotenv()
    bot = Minori()
    bot.run(DISCORD_TOKEN)