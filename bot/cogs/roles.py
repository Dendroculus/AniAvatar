import asyncio
import contextlib
from collections import defaultdict
from typing import Optional, List, Dict
import discord
from discord.ext import commands, tasks
from bot.utils.progression.profile_cards import get_title
from bot.config.configs import ProfileCardConstants as PCC
from bot.config.configs import RolesConstants as RC


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
                print(f"[Roles] Forbidden updating roles for user {user_id} in guild {guild_id}")
            except discord.NotFound:
                print(f"[Roles] Guild or user not found (guild {guild_id}, user {user_id})")
            except Exception as e:
                print(f"[Roles] Error processing queued role update (guild {guild_id}, user {user_id}): {e}")
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
            print(f"[Roles] Error executing update_roles for {user_id} in guild {guild_id}: {e}")

    async def _find_role_by_name(self, guild: discord.Guild, title: str) -> Optional[discord.Role]:
        """
        Finds a role in the guild by name using case-insensitive comparison.

        Args:
            guild (discord.Guild): The guild to search in.
            title (str): The role name to find.

        Returns:
            Optional[discord.Role]: The matching Role object if found, else None.
        """
        if not title:
            return None
        title_norm = title.strip().lower()
        return discord.utils.find(lambda r: r.name and r.name.strip().lower() == title_norm, guild.roles)
    
    async def _cleanup_duplicates(self, guild: discord.Guild, title: str, roles: List[discord.Role]):
        """Helper to delete duplicate roles."""
        for r in roles:
            try:
                if not r.managed and guild.me and guild.me.guild_permissions.manage_roles:
                    await r.delete(reason=f"Duplicate title role '{title}' removed by AniAvatar")
                    print(f"[Roles] Deleted duplicate role {r.name} in guild {guild.id}")
            except discord.Forbidden:
                print(f"[Roles] Cannot delete role {r.name} in guild {guild.id} (missing perms)")
            except Exception as e:
                print(f"[Roles] Error deleting role {getattr(r, 'name', r)} in guild {guild.id}: {e}")

    async def _create_new_role(self, guild: discord.Guild, title: str) -> Optional[discord.Role]:
        """Helper to create a new role safely."""
        bot_member = guild.me
        if not bot_member or not bot_member.guild_permissions.manage_roles:
            print(f"[Roles] Missing Manage Roles, cannot create role '{title}' in guild {guild.id}")
            return None

        color = PCC.TITLE_COLORS.get(title, discord.Color.default())
        try:
            role = await guild.create_role(
                name=title,
                color=color,
                reason="Auto created by AniAvatar progression roles"
            )
            return role
        except discord.Forbidden:
            print(f"[Roles] Forbidden creating role '{title}' in guild {guild.id}.")
        except discord.HTTPException as e:
            print(f"[Roles] HTTP error creating role '{title}' in guild {guild.id}: {e}")
        except Exception as e:
            print(f"[Roles] Unexpected error creating role '{title}' in guild {guild.id}: {e}")
        return None

    async def _get_or_create_role(self, guild: discord.Guild, title: str) -> Optional[discord.Role]:
        """
        Retrieves an existing title role or creates it if missing.
        
        Handles deduplication by removing extra roles with the same name.

        Args:
            guild (discord.Guild): The guild context.
            title (str): The name of the role (Title).

        Returns:
            Optional[discord.Role]: The active role object, or None if creation failed/permission missing.
        """
        title_norm = title.strip().lower()
        matches = [r for r in guild.roles if r.name and r.name.strip().lower() == title_norm]

        if matches:
            keep = min(matches, key=lambda r: r.id)
            extras = [r for r in matches if r != keep]
            
            if extras:
                await self._cleanup_duplicates(guild, title, extras)

            if keep.managed:
                return None
            return keep

        return await self._create_new_role(guild, title)

    async def _ensure_titles_exist(self, guild: discord.Guild) -> List[discord.Role]:
        """
        Ensures all defined progression title roles exist in the given guild.
        Also attempts to sync role colors if they mismatch.

        Args:
            guild (discord.Guild): The target guild.

        Returns:
            List[discord.Role]: A list of the valid title roles present in the guild.
        """
        roles: List[discord.Role] = []
        for title in RC.TITLE_ORDER:
            r = await self._get_or_create_role(guild, title)
            if r and not r.managed:
                try:
                    desired_color = PCC.TITLE_COLORS.get(title, discord.Color.default())
                    if guild.me and guild.me.guild_permissions.manage_roles and r.color != desired_color:
                        await r.edit(color=desired_color, reason="Sync role color with title")
                except discord.Forbidden:
                    print(f"[Roles] Missing permission to edit role color for {r.name} in guild {guild.id}")
                except Exception as e:
                    print(f"[Roles] Error editing role color for {r.name}: {e}")
                roles.append(r)
        return roles

    async def _sync_role_hierarchy(self, guild: discord.Guild, roles: List[discord.Role]):
        """
        Adjusts role positions to match the progression order defined in configuration.

        Args:
            guild (discord.Guild): The target guild.
            roles (List[discord.Role]): The list of title roles to order.
        """
        if not roles:
            return

        bot_member = guild.me or await guild.fetch_member(self.bot.user.id)
        if not bot_member.guild_permissions.manage_roles:
            return

        bot_top_pos = bot_member.top_role.position
        base_pos = max(0, bot_top_pos - len(roles))

        positions = {}
        for idx, role in enumerate(roles):
            if role.position >= bot_top_pos:
                continue

            desired_pos = base_pos + idx
            if desired_pos >= bot_top_pos:
                desired_pos = bot_top_pos - 1

            if role.position != desired_pos:
                positions[role] = desired_pos

        if not positions:
            return

        try:
            await guild.edit_role_positions(positions=positions)
            print(f"[Roles] Reordered title roles in guild {guild.id}")
        except discord.Forbidden:
            print(f"[Roles] Forbidden to edit role positions in guild {guild.id}.")
        except discord.HTTPException as e:
            print(f"[Roles] Failed to reorder roles in guild {guild.id}: {e}")

    async def _check_bot_hierarchy(self, guild: discord.Guild, role: discord.Role) -> bool:
        """Helper to verify if the bot outranks the target role."""
        try:
            bot_member = guild.me or await guild.fetch_member(self.bot.user.id)
            if bot_member.top_role.position <= role.position:
                print(f"[Roles] Cannot manage role '{role.name}' in guild {guild.id}: role is at or above bot's top role.")
                return False
            return True
        except Exception:
            return True 

    async def _sync_role_color(self, guild: discord.Guild, role: discord.Role, title: str):
        """Helper to ensure the role color matches the progression config."""
        try:
            if not (guild.me and guild.me.guild_permissions.manage_roles):
                return

            desired_color = PCC.TITLE_COLORS.get(title, discord.Color.default())
            if role.color != desired_color:
                await role.edit(color=desired_color, reason="Sync role color with title")
        except discord.Forbidden:
            print(f"[Roles] Missing permission to edit role color for {role.name}")
        except Exception as e:
            print(f"[Roles] Error editing role color for {role.name}: {e}")

    async def _remove_old_roles(self, member: discord.Member, current_role: discord.Role):
        """Helper to remove outdated progression roles."""
        title_names = {t.strip().lower() for t in RC.TITLE_ORDER}
        roles_to_remove = [
            r for r in member.roles 
            if r.name and r.name.strip().lower() in title_names and r != current_role
        ]
        
        if roles_to_remove:
            try:
                await member.remove_roles(*roles_to_remove, reason="Level update")
            except discord.Forbidden:
                print(f"[Roles] Missing permission to remove roles from {member.display_name} ({member.id})")
            except Exception as e:
                print(f"[Roles] Error removing old roles for {member.id}: {e}")

    async def _add_new_role(self, member: discord.Member, role: discord.Role):
        """Helper to add the new progression role if missing."""
        if role in member.roles:
            return
        try:
            await member.add_roles(role, reason="Level update")
        except discord.Forbidden:
            print(f"[Roles] Missing permission to add role '{role.name}' to {member.display_name} ({member.id})")
        except Exception as e:
            print(f"[Roles] Error adding role for {member.id}: {e}")

    async def update_roles(self, member: discord.Member, level: int):
        """
        Updates a member's roles based on their current progression level.
        
        Calculates the correct title for the level, assigns it, and removes
        any other outdated progression titles.

        Args:
            member (discord.Member): The member to update.
            level (int): The current progression level.
        """
        if member.bot:
            return

        try:
            guild = member.guild
            title = get_title(level)

            role = await self._get_or_create_role(guild, title)
            if role is None:
                return

            if not await self._check_bot_hierarchy(guild, role):
                return

            await self._sync_role_color(guild, role, title)
            await self._remove_old_roles(member, role)
            await self._add_new_role(member, role)

        except Exception as e:
            print(f"[Roles] Unexpected error updating roles for {member.display_name} ({member.id}): {e}")

    async def _ensure_guild_titles_and_hierarchy(self, guild: discord.Guild) -> None:
        """
        Helper method to sync titles and hierarchy for a single guild.

        Args:
            guild (discord.Guild): The guild to sync.
        """
        roles = await self._ensure_titles_exist(guild)
        await self._sync_role_hierarchy(guild, roles)

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
            print("[Roles] Startup role setup complete. Periodic fail-safe will catch rare inconsistencies.")
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
        added_roles = [r for r in after.roles if r.id not in before_role_ids and r.name and r.name.strip().lower() in title_names]
        removed_roles = [r for r in before.roles if r.id not in after_role_ids and r.name and r.name.strip().lower() in title_names]

        if not added_roles and not removed_roles:
            return

        print(f"[Roles] Member {after.id} role change detected. Added: {[r.name for r in added_roles]}, Removed: {[r.name for r in removed_roles]}")

        try:
            _, level = await progression.get_user(after.id, after.guild.id)
            await self.queue_role_update(after.guild.id, after.id, level)
            print(f"[Roles] Queued role resync for {after.display_name} after manual role edit.")
        except Exception as e:
            print(f"[Roles] Failed to queue resync for {after.id}: {e}")


async def setup(bot):
    await bot.add_cog(Roles(bot))