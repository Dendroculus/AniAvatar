import asyncio
import contextlib
from collections import defaultdict
from typing import Dict, List
import discord
from discord.ext import commands, tasks
from bot.config.configs import RolesConstants as RC
from bot.features.roles import ProgressionRoleService


"""
roles.py

Cog managing role-based progression titles and synchronization.
"""


class Roles(commands.Cog):
    """
    Manages role-based progression, ensuring role hierarchy and synchronization with user levels.

    Responsibilities:
    - Creating and maintaining progression title roles in guilds.
    - Synchronizing role colors and hierarchy positions.
    - Queueing and processing user role updates asynchronously.
    - reacting to member updates to prevent manual role tampering.
    """

    def __init__(self, bot: commands.Bot):
        """
        Initialize the Roles cog.

        Args:
            bot (commands.Bot): The bot instance.
        """
        self.bot = bot
        self.role_service = ProgressionRoleService(bot)
        self._locks: Dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

        # Producer-Consumer queue
        self.queue: asyncio.Queue[tuple[int, int, int]] = asyncio.Queue()

        # Semaphore for concurrent guild processing
        self._sync_sem = asyncio.Semaphore(5)

        # Background worker task
        self.worker_task = asyncio.create_task(self.worker())

        # Periodic fail-safe (no member fetching)
        self.sync_roles_loop.change_interval(minutes=RC.SYNC_INTERVAL_MINUTES)
        self.sync_roles_loop.start()

    async def cog_unload(self):
        """
        Clean up background tasks when the cog is unloaded.

        Cancels the sync loop and the worker task, awaiting the worker's graceful exit.
        """
        self.sync_roles_loop.cancel()
        self.worker_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self.worker_task

    #  Producer API
    async def queue_role_update(self, guild_id: int, user_id: int, level: int):
        """
        Public method to enqueue a role update for a specific user.

        Args:
            guild_id (int): The ID of the guild.
            user_id (int): The ID of the user to update.
            level (int): The new progression level to apply.
        """
        await self.queue.put((guild_id, user_id, level))

    #  Worker
    async def worker(self):
        """
        Background consumer loop processing queued role updates.

        Continually pulls from self.queue and delegates to update_roles_by_ids
        while managing concurrency locks per guild.
        """
        while True:
            guild_id, user_id, level = await self.queue.get()
            try:
                lock = self._locks[guild_id]
                async with lock:
                    await self.update_roles_by_ids(guild_id, user_id, level)
            except discord.Forbidden:
                print(
                    f"[Roles] Forbidden updating roles for user {user_id} in guild {guild_id}"
                )
            except discord.NotFound:
                print(
                    f"[Roles] Guild or user not found (guild {guild_id}, user {user_id})"
                )
            except Exception as e:
                print(
                    f"[Roles] Error processing queued role update (guild {guild_id}, user {user_id}): {e}"
                )
            finally:
                self.queue.task_done()
                await asyncio.sleep(1.5)

    async def update_roles_by_ids(self, guild_id: int, user_id: int, level: int):
        """
        Fetches guild and member objects by ID and triggers the role update logic.

        Args:
            guild_id (int): The target guild ID.
            user_id (int): The target user ID.
            level (int): The user's new progression level.
        """
        guild = self.bot.get_guild(guild_id)
        if not guild:
            try:
                guild = await self.bot.fetch_guild(guild_id)
            except Exception as e:
                print(f"[Roles] Failed to fetch guild {guild_id} in worker: {e}")
                return
        try:
            member = guild.get_member(user_id) or await guild.fetch_member(user_id)
        except Exception as e:
            print(f"[Roles] Failed to fetch member {user_id} in guild {guild_id}: {e}")
            return

        try:
            await self.update_roles(member, level)
        except Exception as e:
            print(
                f"[Roles] Error executing update_roles for {user_id} in guild {guild_id}: {e}"
            )

    async def update_roles(
        self,
        member: discord.Member,
        level: int,
    ):
        """Delegate progression role assignment to the role service."""
        await self.role_service.update_roles(member, level)

    async def _ensure_titles_exist(
        self,
        guild: discord.Guild,
    ) -> List[discord.Role]:
        """Delegate title-role creation and color synchronization."""
        return await self.role_service._ensure_titles_exist(guild)

    async def _sync_role_hierarchy(
        self,
        guild: discord.Guild,
        roles: List[discord.Role],
    ):
        """Delegate progression role ordering."""
        await self.role_service._sync_role_hierarchy(guild, roles)

    async def _ensure_guild_titles_and_hierarchy(
        self,
        guild: discord.Guild,
    ) -> None:
        """Delegate complete guild title synchronization."""
        await self.role_service._ensure_guild_titles_and_hierarchy(guild)

    #  Fail-safe loop (no member iteration)
    @tasks.loop(minutes=720)
    async def sync_roles_loop(self):
        """
        Periodic background task to sync role existence and hierarchy across guilds.

        Uses a semaphore to process guilds concurrently but with a limited pool
        to prevent API flooding.
        """
        progression = self.bot.get_cog("Progression")
        if not progression:
            print("[Roles] Progression cog not found for sync loop.")
            return

        async def sync_guild_safe(guild: discord.Guild):
            async with self._sync_sem:
                try:
                    await self._ensure_guild_titles_and_hierarchy(guild)
                except Exception as e:
                    print(f"[Roles] Error during guild sync {guild.id}: {e}")

        await asyncio.gather(*(sync_guild_safe(g) for g in self.bot.guilds))

        print("[Roles] Fail-safe role sync tick complete.\n")

    @sync_roles_loop.before_loop
    async def before_sync_roles(self):
        """Pre-loop hook waiting for the bot to be fully ready before starting the sync loop."""
        await self.bot.wait_until_ready()
        print("[Roles] Started periodic role fail-safe sync loop.")

    #  Events
    @commands.Cog.listener()
    async def on_ready(self):
        """
        Listener for the on_ready event.

        Triggers an initial scan of all guilds to ensure progression roles exist
        and are ordered correctly upon startup.
        """
        print("[Roles] Ensuring progression roles and order on startup...")
        try:
            for guild in self.bot.guilds:
                roles = await self._ensure_titles_exist(guild)
                await self._sync_role_hierarchy(guild, roles)
            print(
                "[Roles] Startup role setup complete. Periodic fail-safe will catch rare inconsistencies."
            )
        except Exception as e:
            print(f"[Roles] Error during startup role setup: {e}")

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        """
        Listener for member updates to detect and revert manual role changes.

        If a user manually modifies roles that are managed by the progression system,
        this listener queues a resync to restore the correct state.

        Args:
            before (discord.Member): The member state before update.
            after (discord.Member): The member state after update.

        Returns:
            None
        """
        progression = self.bot.get_cog("Progression")
        if not progression or after.bot:
            return

        before_role_ids = {r.id for r in before.roles}
        after_role_ids = {r.id for r in after.roles}

        if before_role_ids == after_role_ids:
            return

        title_names = {t.lower() for t in RC.TITLE_ORDER}
        added_roles = [
            r
            for r in after.roles
            if r.id not in before_role_ids
            and r.name
            and r.name.strip().lower() in title_names
        ]
        removed_roles = [
            r
            for r in before.roles
            if r.id not in after_role_ids
            and r.name
            and r.name.strip().lower() in title_names
        ]

        if not added_roles and not removed_roles:
            return

        print(
            f"[Roles] Member {after.id} role change detected. Added: {[r.name for r in added_roles]}, Removed: {[r.name for r in removed_roles]}"
        )

        try:
            _, level = await progression.get_user(after.id, after.guild.id)
            await self.queue_role_update(after.guild.id, after.id, level)
            print(
                f"[Roles] Queued role resync for {after.display_name} after manual role edit."
            )
        except Exception as e:
            print(f"[Roles] Failed to queue resync for {after.id}: {e}")


async def setup(bot):
    await bot.add_cog(Roles(bot))
