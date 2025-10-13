import asyncio
from collections import defaultdict
from typing import Optional, List, Dict
import discord
from discord.ext import commands, tasks
from cogs.utils.constants import *
from cogs.utils.progUtils import *

TITLE_ORDER = [
    "Novice", "Warrior", "Elite", "Champion", "Hero", "Legend", "Mythic",
    "Ascendant", "Immortal", "Celestial", "Transcendent", "Aetherborn",
    "Cosmic", "Divine", "Eternal", "Enlightened"
]


class Roles(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._locks: Dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
        self.SYNC_INTERVAL_MINUTES = 120  
        self.MAX_PER_GUILD = 30
        self.SLEEP_BETWEEN_OPS = 0.25

        self.sync_roles_loop.change_interval(minutes=self.SYNC_INTERVAL_MINUTES)
        self.sync_roles_loop.start()

    async def cog_unload(self):
        self.sync_roles_loop.cancel()


    async def update_roles_by_ids(self, guild_id: int, user_id: int, level: int):
        guild = self.bot.get_guild(guild_id)
        if not guild:
            try:
                guild = await self.bot.fetch_guild(guild_id)
            except Exception:
                return
        try:
            member = guild.get_member(user_id) or await guild.fetch_member(user_id)
        except Exception:
            return
        await self.update_roles(member, level)

    async def _find_role_by_name(self, guild: discord.Guild, title: str) -> Optional[discord.Role]:
        if not title:
            return None
        title_norm = title.strip().lower()
        return discord.utils.find(lambda r: r.name and r.name.strip().lower() == title_norm, guild.roles)

    async def _get_or_create_role(self, guild: discord.Guild, title: str) -> Optional[discord.Role]:
        title_norm = title.strip().lower()
        matches = [r for r in guild.roles if r.name and r.name.strip().lower() == title_norm]

        if matches:
            keep = min(matches, key=lambda r: r.id)
            extras = [r for r in matches if r != keep]

            for r in extras:
                try:
                    if not r.managed and guild.me and guild.me.guild_permissions.manage_roles:
                        await r.delete(reason=f"Duplicate title role '{title}' removed by AniAvatar")
                        print(f"[Roles] Deleted duplicate role {r.name} in guild {guild.id}")
                except discord.Forbidden:
                    print(f"[Roles] Cannot delete role {r.name} in guild {guild.id} (missing perms)")
                except Exception as e:
                    print(f"[Roles] Error deleting role {getattr(r,'name',r)} in guild {guild.id}: {e}")

            if keep.managed:
                return None
            return keep

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

    async def update_roles(self, member: discord.Member, level: int):
        if member.bot:
            return
        try:
            try:
                member = await member.guild.fetch_member(member.id)
            except Exception:
                pass

            guild = member.guild
            title = get_title(level)

            role = await self._get_or_create_role(guild, title)
            if role is None:
                return

            bot_member = guild.me or await guild.fetch_member(self.bot.user.id)
            try:
                if bot_member.top_role.position <= role.position:
                    print(f"[Roles] Cannot manage role '{role.name}' in guild {guild.id}: role is at or above bot's top role.")
                    return
            except Exception:
                pass

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

    @tasks.loop(minutes=120) 
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
                    try:
                        if member.bot:
                            processed += 1
                            await asyncio.sleep(self.SLEEP_BETWEEN_OPS)
                            continue
                        if processed >= self.MAX_PER_GUILD:
                            break

                        exp, level = await progression.get_user(member.id, guild.id)
                        desired_title = get_title(level).strip().lower()

                        desired_role = discord.utils.find(
                            lambda r: r.name and r.name.strip().lower() == desired_title,
                            guild.roles
                        )

                        member_title_names = {r.name.strip().lower() for r in member.roles if r.name}
                        other_title_names = {t.lower() for t in TITLE_ORDER} - {desired_title}
                        has_other_titles = any(n in other_title_names for n in member_title_names)
                        already_ok = (desired_role is not None and desired_role in member.roles and not has_other_titles)

                        if not already_ok:
                            try:
                                fresh_member = await guild.fetch_member(member.id)
                                await self.update_roles(fresh_member, level)
                            except discord.Forbidden:
                                print(f"[Roles] Missing perms to update roles for {member.id} in guild {guild.id}")
                            except discord.HTTPException as he:
                                print(f"[Roles] HTTP error updating roles for {member.id} in guild {guild.id}: {he}")
                            except Exception as e:
                                print(f"[Roles] Error updating roles for {member.id} in guild {guild.id}: {e}")

                        processed += 1
                        await asyncio.sleep(self.SLEEP_BETWEEN_OPS)
                    except Exception as e:
                        print(f"[Roles] Skipping member {member.id} in guild {guild.id}: {e}")
                        processed += 1
                        await asyncio.sleep(self.SLEEP_BETWEEN_OPS)
            except Exception as e:
                print(f"[Roles] Error during guild sync {guild.id}: {e}")

        print("[Roles] Fail-safe role sync complete.")

    @sync_roles_loop.before_loop
    async def before_sync_roles(self):
        await self.bot.wait_until_ready()
        print("[Roles] Started periodic role fail-safe sync loop.")

    @commands.Cog.listener()
    async def on_ready(self):
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
        progression = self.bot.get_cog("Progression")
        if not progression or after.bot:
            return

        before_role_ids = {r.id for r in before.roles}
        after_role_ids = {r.id for r in after.roles}

        if before_role_ids == after_role_ids:
            return

        title_names = {t.lower() for t in TITLE_ORDER}
        added_roles = [r for r in after.roles if r.id not in before_role_ids and r.name and r.name.strip().lower() in title_names]
        removed_roles = [r for r in before.roles if r.id not in after_role_ids and r.name and r.name.strip().lower() in title_names]

        if not added_roles and not removed_roles:
            return

        print(f"[Roles] Member {after.id} role change detected. Added: {[r.name for r in added_roles]}, Removed: {[r.name for r in removed_roles]}")

        try:
            exp, level = await progression.get_user(after.id, after.guild.id)
            await self.update_roles(after, level)
            print(f"[Roles] Synced roles for {after.display_name} after manual role edit.")
        except Exception as e:
            print(f"[Roles] Failed to resync roles for {after.id}: {e}")

async def setup(bot):
    await bot.add_cog(Roles(bot))
