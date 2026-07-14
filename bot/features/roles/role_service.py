"""Progression role creation, hierarchy, and assignment services."""

from typing import List, Optional

import discord
from discord.ext import commands

from bot.config.configs import ProfileCardConstants as PCC
from bot.config.configs import RolesConstants as RC
from bot.utils.progression.profile_cards import get_title


class ProgressionRoleService:
    """Manage progression roles for Discord guilds and members."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _find_role_by_name(
        self, guild: discord.Guild, title: str
    ) -> Optional[discord.Role]:
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
        return discord.utils.find(
            lambda r: r.name and r.name.strip().lower() == title_norm, guild.roles
        )

    async def _cleanup_duplicates(
        self, guild: discord.Guild, title: str, roles: List[discord.Role]
    ):
        """Helper to delete duplicate roles."""
        for r in roles:
            try:
                if (
                    not r.managed
                    and guild.me
                    and guild.me.guild_permissions.manage_roles
                ):
                    await r.delete(
                        reason=f"Duplicate title role '{title}' removed by AniAvatar"
                    )
                    print(
                        f"[Roles] Deleted duplicate role {r.name} in guild {guild.id}"
                    )
            except discord.Forbidden:
                print(
                    f"[Roles] Cannot delete role {r.name} in guild {guild.id} (missing perms)"
                )
            except Exception as e:
                print(
                    f"[Roles] Error deleting role {getattr(r, 'name', r)} in guild {guild.id}: {e}"
                )

    async def _create_new_role(
        self, guild: discord.Guild, title: str
    ) -> Optional[discord.Role]:
        """Helper to create a new role safely."""
        bot_member = guild.me
        if not bot_member or not bot_member.guild_permissions.manage_roles:
            print(
                f"[Roles] Missing Manage Roles, cannot create role '{title}' in guild {guild.id}"
            )
            return None

        color = PCC.TITLE_COLORS.get(title, discord.Color.default())
        try:
            role = await guild.create_role(
                name=title,
                color=color,
                reason="Auto created by AniAvatar progression roles",
            )
            return role
        except discord.Forbidden:
            print(f"[Roles] Forbidden creating role '{title}' in guild {guild.id}.")
        except discord.HTTPException as e:
            print(
                f"[Roles] HTTP error creating role '{title}' in guild {guild.id}: {e}"
            )
        except Exception as e:
            print(
                f"[Roles] Unexpected error creating role '{title}' in guild {guild.id}: {e}"
            )
        return None

    async def _get_or_create_role(
        self, guild: discord.Guild, title: str
    ) -> Optional[discord.Role]:
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
        matches = [
            r for r in guild.roles if r.name and r.name.strip().lower() == title_norm
        ]

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
                    if (
                        guild.me
                        and guild.me.guild_permissions.manage_roles
                        and r.color != desired_color
                    ):
                        await r.edit(
                            color=desired_color, reason="Sync role color with title"
                        )
                except discord.Forbidden:
                    print(
                        f"[Roles] Missing permission to edit role color for {r.name} in guild {guild.id}"
                    )
                except Exception as e:
                    print(f"[Roles] Error editing role color for {r.name}: {e}")
                roles.append(r)
        return roles

    async def _sync_role_hierarchy(
        self, guild: discord.Guild, roles: List[discord.Role]
    ):
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

    async def _check_bot_hierarchy(
        self, guild: discord.Guild, role: discord.Role
    ) -> bool:
        """Helper to verify if the bot outranks the target role."""
        try:
            bot_member = guild.me or await guild.fetch_member(self.bot.user.id)
            if bot_member.top_role.position <= role.position:
                print(
                    f"[Roles] Cannot manage role '{role.name}' in guild {guild.id}: role is at or above bot's top role."
                )
                return False
            return True
        except Exception:
            return True

    async def _sync_role_color(
        self, guild: discord.Guild, role: discord.Role, title: str
    ):
        """Helper to ensure the role color matches the progression config."""
        try:
            if not (guild.me and guild.me.guild_permissions.manage_roles):
                return

            desired_color = PCC.TITLE_COLORS.get(title, discord.Color.default())
            if role.color != desired_color:
                await role.edit(
                    color=desired_color, reason="Sync role color with title"
                )
        except discord.Forbidden:
            print(f"[Roles] Missing permission to edit role color for {role.name}")
        except Exception as e:
            print(f"[Roles] Error editing role color for {role.name}: {e}")

    async def _remove_old_roles(
        self, member: discord.Member, current_role: discord.Role
    ):
        """Helper to remove outdated progression roles."""
        title_names = {t.strip().lower() for t in RC.TITLE_ORDER}
        roles_to_remove = [
            r
            for r in member.roles
            if r.name and r.name.strip().lower() in title_names and r != current_role
        ]

        if roles_to_remove:
            try:
                await member.remove_roles(*roles_to_remove, reason="Level update")
            except discord.Forbidden:
                print(
                    f"[Roles] Missing permission to remove roles from {member.display_name} ({member.id})"
                )
            except Exception as e:
                print(f"[Roles] Error removing old roles for {member.id}: {e}")

    async def _add_new_role(self, member: discord.Member, role: discord.Role):
        """Helper to add the new progression role if missing."""
        if role in member.roles:
            return
        try:
            await member.add_roles(role, reason="Level update")
        except discord.Forbidden:
            print(
                f"[Roles] Missing permission to add role '{role.name}' to {member.display_name} ({member.id})"
            )
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
            print(
                f"[Roles] Unexpected error updating roles for {member.display_name} ({member.id}): {e}"
            )

    async def _ensure_guild_titles_and_hierarchy(self, guild: discord.Guild) -> None:
        """
        Helper method to sync titles and hierarchy for a single guild.

        Args:
            guild (discord.Guild): The guild to sync.
        """
        roles = await self._ensure_titles_exist(guild)
        await self._sync_role_hierarchy(guild, roles)
