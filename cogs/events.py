import os
import random
import discord
from discord.ext import commands, tasks

from utils.pollings_db import (
    init_db,
    load_active_polls,
    purge_finished_polls,
)
from utils.pollings import reconstruct_poll
"""
Events Cog - Poll restoration and presence rotation.

This module is responsible for:
- Rehydrating active polls from persistent storage on bot startup, attaching
  interactive views to existing messages where possible.
- Finalizing polls that have expired while the bot was offline (recording results).
- Rotating presence by sampling from a local anime list file.

Operational notes and guarantees:
- Restoration is best-effort: missing guilds/channels/messages are logged and
  expired polls are finalized without a message when necessary to ensure results
  are recorded.
- All network and I/O operations are wrapped with try/except and print statements
  to avoid preventing the bot from completing startup tasks.
- Poll vote tracking uses sets in memory for quick membership checks; persisted
  rows are parsed into lists then sanitized into integer user IDs.
- The cog avoids raising on_ready exceptions; failures are logged to stdout for
  operator inspection (this keeps the bot running even if the poll subsystem has
  issues).
"""

class Events(commands.Cog):
    """
    Cog managing event-like background behavior.

    Responsibilities:
    - Load a curated list of anime titles for periodic presence rotation.
    - On bot ready, initialize poll DB, reload active polls, attach PollView objects,
      finalize expired polls, and purge finished entries from storage.
    - Provide helper functions used during poll reconstruction and validation.

    Concurrency considerations:
    - Poll restoration runs synchronously in on_ready; PollView objects are created
      and attached to messages, which requires the bot to be fully connected.
    - All I/O with Discord (fetching members/messages) is awaited and isolated to
      prevent a single failing poll from stopping the overall restoration process.
    """
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.anime_list_path = None
        self.anime_list = []

    async def cog_load(self):
        """
        Async initialization: load anime list from file without blocking the event loop.
        """
        self.anime_list_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "data", "animelist.txt"
        )
        def load_anime_file():
            try:
                with open(self.anime_list_path, "r", encoding="utf-8") as f:
                    # Expect lines like "1. Title", extract the portion after the first dot-space
                    return [line.split(". ")[1].strip() for line in f.readlines() if ". " in line]
            except Exception:
                return []

        # Offload file I/O to a thread
        self.anime_list = await self.bot.loop.run_in_executor(None, load_anime_file)

    @commands.Cog.listener()
    async def on_ready(self):
        """
        Startup hook that initializes the poll database and attempts to restore state.

        Sequence:
        1. init_db - prepare storage (best-effort).
        2. load_active_polls - retrieve rows describing polls that were active before restart.
        3. For each row, attempt reconstruction (restore or finalize).
        4. purge_finished_polls - clean up any leftover finished entries.
        5. Start the status_task loop for presence rotation if not already running.

        Rationale:
        - Performing purge_finished_polls after restoration minimizes race windows where
          a poll may be removed while being processed.
        - All operations are guarded so on_ready completes even if poll subsystem errors occur.
        """
        if not self.bot.pool:
            print("[Events] Warning: bot.pool is not initialized, cannot load polls.")
            return

        try:
            await init_db(self.bot.pool)
        except Exception as e:
            print(f"[DB Init Error] {e}")

        try:
            rows = await load_active_polls(self.bot.pool)
        except Exception as e:
            print(f"[Poll Reload Error - load_active_polls] {e}")
            rows = []

        for row in rows:
            try:
                await reconstruct_poll(self.bot, row)
            except Exception as e:
                print(f"[Poll Reload] unexpected error reconstructing a poll: {e}")

        try:
            await purge_finished_polls(self.bot.pool)
        except Exception as e:
            print(f"[Poll Reload] failed to purge finished polls: {e}")

        if not self.status_task.is_running():
            self.status_task.start()
        print(f"🟣 Presence rotation started as {self.bot.user} | {len(self.anime_list)} titles loaded")

    @tasks.loop(seconds=1200)
    async def status_task(self):
        """
        Periodically rotate bot presence.

        Behavior:
        - If anime_list is empty the task becomes a no-op to avoid changing presence.
        - Uses a WATCHING activity for consistent appearance.
        - Exceptions when changing presence are suppressed because failures here are
          cosmetic and should not affect other functionalities.
        """
        if not self.anime_list:
            return
        anime = random.choice(self.anime_list)
        try:
            await self.bot.change_presence(
                activity=discord.Activity(type=discord.ActivityType.watching, name=anime)
            )
        except Exception:
            # Ignore presence-setting errors (rate limits, missing intents, etc.)
            pass

    def cog_unload(self):
        """
        Clean shutdown for the cog: cancel the periodic status task.

        The method swallows exceptions as the bot teardown sequence may already
        be in an inconsistent state where cancelling tasks can raise.
        """
        try:
            self.status_task.cancel()
        except Exception:
            pass

async def setup(bot: commands.Bot):
    await bot.add_cog(Events(bot))