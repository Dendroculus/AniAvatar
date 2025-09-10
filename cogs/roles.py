import asyncio
from collections import defaultdict
from typing import Optional, List, Dict

import discord
from discord.ext import commands, tasks

from .progression import get_title, TITLE_COLORS

# Keep this list in the same order as your get_title tiers.
TITLE_ORDER = [
    "Novice", "Warrior", "Elite", "Champion", "Hero", "Legend", "Mythic",
    "Ascendant", "Immortal", "Celestial", "Transcendent", "Aetherborn",
    "Cosmic", "Divine", "Eternal", "Enlightened"
]


class Roles(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # per-guild locks to prevent concurrent creates
        self._locks: Dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

        # Sync loop settings (tune as needed)
        self.SYNC_INTERVAL_MINUTES = 2
        self.MAX_PER_GUILD = 30
        self.SLEEP_BETWEEN_OPS = 0.06

        # start loop
        self.sync_roles_loop.change_interval(minutes=self.SYNC_INTERVAL_MINUTES)
        self.sync_roles_loop.start()

    async def cog_unload(self):
        self.sync_roles_loop.cancel()

    # --- helpers ---------------------------------------------------------

    async def _find_role_by_name(self, guild: discord.Guild, title: str) -> Optional[discord.Role]:
        """Case-insensitive and whitespace-stripped lookup for existing roles."""
        if not title:
            return None
        title_norm = title.strip().lower()
        return discord.utils.find(lambda r: r.name and r.name.strip().lower() == title_norm, guild.roles)

    async def _get_or_create_role(self, guild: discord.Guild, title: str) -> Optional[discord.Role]:
        """
        Return the single role for a title.
        - If multiple exist, keep one (lowest ID) and delete extras.
        - If none exist, create it.
        """
        title_norm = title.strip().lower()
        matches = [r for r in guild.roles if r.name and r.name.strip().lower() == title_norm]

        if matches:
            # Keep the oldest role (lowest ID = usually the first created)
            keep = min(matches, key=lambda r: r.id)
            extras = [r for r in matches if r != keep]

            for r in extras:
                try:
                    if not r.managed and guild.me and guild.me.guild_permissions.manage_roles:
                        await r.delete(reason=f"Duplicate title role '{title}' removed by AniAvatar")
                        print(f"[Roles] Deleted duplicate role {r} in guild {guild.id}")
                except discord.Forbidden:
                    print(f"[Roles] Cannot delete role {r} in guild {guild.id} (missing perms)")
                except Exception as e:
                    print(f"[Roles] Error deleting role {r} in guild {guild.id}: {e}")

            if keep.managed:
                return None
            return keep

        # No matches → create new
        bot_member = guild.me
        if not bot_member or not bot_member.guild_permissions.manage_roles:
            print(f"[Roles] Missing Manage Roles, cannot create role '{title}' in guild {guild.id}")
            return None

        color = TITLE_COLORS.get(title, discord.Color.default())
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

    async def _ensure_titles_exist(self, guild: discord.Guild) -> List[discord.Role]:
        """
        Ensure that all roles from TITLE_ORDER exist (best-effort).
        Returns the list of roles that exist / were created, in the same order as TITLE_ORDER.
        Skips managed roles and roles that couldn't be created.
        """
        roles: List[discord.Role] = []
        for title in TITLE_ORDER:
            r = await self._get_or_create_role(guild, title)
            if r and not r.managed:
                try:
                    desired_color = TITLE_COLORS.get(title, discord.Color.default())
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
        Best-effort ordering of the title roles according to TITLE_ORDER.
        Places the group directly below the bot's top role (bot cannot move roles above itself).
        """
        if not roles:
            return

        bot_member = guild.me or await guild.fetch_member(self.bot.user.id)
        if not bot_member.guild_permissions.manage_roles:
            return

        bot_top_pos = bot_member.top_role.position
        base_pos = bot_top_pos - len(roles)
        if base_pos < 0:
            base_pos = 0

        positions = {}
        for idx, role in enumerate(roles):
            # skip roles above bot's top role (can't move them anyway)
            if role.position >= bot_top_pos:
                continue

            desired_pos = base_pos + idx
            if desired_pos >= bot_top_pos:
                desired_pos = bot_top_pos - 1

            if role.position != desired_pos:
                positions[role] = desired_pos

        if not positions:
            return  # nothing to change

        try:
            await guild.edit_role_positions(positions=positions)
            print(f"[Roles] Reordered title roles in guild {guild.id}")
        except discord.Forbidden:
            print(f"[Roles] Forbidden to edit role positions in guild {guild.id}.")
        except discord.HTTPException as e:
            print(f"[Roles] Failed to reorder roles in guild {guild.id}: {e}")


    async def update_roles(self, member: discord.Member, level: int):
        try:
            guild = member.guild
            title = get_title(level)

            role = await self._get_or_create_role(guild, title)
            if role is None:
                return

            try:
                if guild.me and guild.me.guild_permissions.manage_roles:
                    desired_color = TITLE_COLORS.get(title, discord.Color.default())
                    if role.color != desired_color:
                        await role.edit(color=desired_color, reason="Sync role color with title")
            except discord.Forbidden:
                print(f"[Roles] Missing permission to edit role color for {role.name}")
            except Exception as e:
                print(f"[Roles] Error editing role color for {role.name}: {e}")

            title_names = {t.strip().lower() for t in TITLE_ORDER}
            roles_to_remove = [r for r in member.roles if r.name and r.name.strip().lower() in title_names and r != role]
            if roles_to_remove:
                try:
                    await member.remove_roles(*roles_to_remove, reason="Level update")
                except discord.Forbidden:
                    print(f"[Roles] Missing permission to remove roles from {member.display_name} ({member.id})")
                except Exception as e:
                    print(f"[Roles] Error removing old roles for {member.id}: {e}")

            if role not in member.roles:
                try:
                    await member.add_roles(role, reason="Level update")
                except discord.Forbidden:
                    print(f"[Roles] Missing permission to add role '{role.name}' to {member.display_name} ({member.id})")
                except Exception as e:
                    print(f"[Roles] Error adding role for {member.id}: {e}")

        except Exception as e:
            print(f"[Roles] Unexpected error updating roles for {member.display_name} ({member.id}): {e}")

    @tasks.loop(minutes=2)
    async def sync_roles_loop(self):
        progression = self.bot.get_cog("Progression")
        if not progression:
            print("[Roles] Progression cog not found for sync loop.")
            return

        for guild in self.bot.guilds:
            try:
                roles = await self._ensure_titles_exist(guild)
                await self._sync_role_hierarchy(guild, roles)

                processed = 0
                for member in guild.members:
                    if member.bot:
                        continue
                    if processed >= self.MAX_PER_GUILD:
                        break
                    try:
                        # progression.get_user is synchronous in your earlier code; keep same contract
                        exp, level = progression.get_user(member.id, guild.id)
                        await self.update_roles(member, level)
                        processed += 1
                        await asyncio.sleep(self.SLEEP_BETWEEN_OPS)
                    except Exception as e:
                        print(f"[Roles] Skipping member {member.id} in guild {guild.id}: {e}")
            except Exception as e:
                print(f"[Roles] Error during guild sync {guild.id}: {e}")

        print("[Roles] Periodic role sync complete.")

    @sync_roles_loop.before_loop
    async def before_sync_roles(self):
        await self.bot.wait_until_ready()
        print("[Roles] Started periodic role sync loop.")

    @commands.Cog.listener()
    async def on_ready(self):
        print("[Roles] Syncing progression roles on startup...")
        progression = self.bot.get_cog("Progression")
        if not progression:
            print("[Roles] Progression cog not found.")
            return

        for guild in self.bot.guilds:
            try:
                roles = await self._ensure_titles_exist(guild)
                await self._sync_role_hierarchy(guild, roles)

                for member in guild.members:
                    if member.bot:
                        continue
                    try:
                        exp, level = progression.get_user(member.id, guild.id)
                        await self.update_roles(member, level)
                    except Exception as e:
                        print(f"[Roles] Skipping member {member.id} in guild {guild.id}: {e}")
            except Exception as e:
                print(f"[Roles] Error during on_ready sync for guild {guild.id}: {e}")

        print("[Roles] Startup role sync complete.")

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if before.roles != after.roles:
            progression = self.bot.get_cog("Progression")
            if not progression:
                return
            try:
                exp, level = progression.get_user(after.id, after.guild.id)
                await self.update_roles(after, level)
            except Exception as e:
                print(f"[Roles] Failed to update roles for {after.id}: {e}")


async def setup(bot):
    await bot.add_cog(Roles(bot))
    print("📦 Loaded roles cog.")
