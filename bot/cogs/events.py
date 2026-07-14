import asyncio
import random
import discord
from discord.ext import commands, tasks

from bot.features.polling.recovery import reconstruct_poll
from bot.features.polling.repository import (
    init_db,
    load_active_polls,
    purge_finished_polls,
)
from bot.features.anime.presence_provider import AnimePresenceProvider

"""
Events Cog - Poll restoration and presence rotation.

This module is responsible for:
- Rehydrating active polls from persistent storage on bot startup, attaching
  interactive views to existing messages where possible.
- Finalizing polls that have expired while the bot was offline (recording results).
- Rotating presence from AniList-backed cached titles.

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
    - Load AniList-backed titles for periodic presence rotation.
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
        self.presence_provider = AnimePresenceProvider(bot)
        self.anime_titles: list[str] = []

    async def cog_load(self) -> None:
        """Load cached or freshly fetched AniList presence titles."""
        self.anime_titles = await self.presence_provider.load_titles()

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

        if not self.refresh_presence_titles.is_running():
            self.refresh_presence_titles.start()

        print(
            f"🟣 Presence rotation started as {self.bot.user} | "
            f"{len(self.anime_titles)} AniList titles loaded"
        )

    @tasks.loop(minutes=20)
    async def status_task(self) -> None:
        """Rotate the bot presence from the locally cached title pool."""
        if not self.anime_titles:
            return

        anime = random.choice(self.anime_titles)

        try:
            await self.bot.change_presence(
                activity=discord.Activity(
                    type=discord.ActivityType.watching,
                    name=anime,
                )
            )
        except Exception:
            pass

    @tasks.loop(hours=24)
    async def refresh_presence_titles(self) -> None:
        """Refresh the local presence title pool from AniList."""
        titles = await self.presence_provider.refresh_titles()

        if titles:
            self.anime_titles = titles
            print(f"[Events] Refreshed {len(titles)} AniList presence titles.")

    @refresh_presence_titles.before_loop
    async def before_refresh_presence_titles(self) -> None:
        """Delay the first scheduled refresh after startup."""
        await self.bot.wait_until_ready()
        await asyncio.sleep(24 * 60 * 60)

    def cog_unload(self) -> None:
        """Cancel background presence tasks during extension unload."""
        for loop in (
            self.status_task,
            self.refresh_presence_titles,
        ):
            if loop.is_running():
                loop.cancel()


async def setup(bot: commands.Bot):
    await bot.add_cog(Events(bot))
