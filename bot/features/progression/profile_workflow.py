"""Profile rendering workflow for progression commands."""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass

import discord

from bot.config.assets import asset_catalog
from bot.config.configs import AssetPaths as AP, ProgressionConstants as PC
from bot.features.progression.domain.levels import (
    get_title,
    get_title_emoji,
    required_exp,
)
from bot.services.render_manager import RenderContext, RenderManager
from bot.services.user_repository import UserRepository

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class ProfileRenderResult:
    """Rendered profile data required by Discord command responses."""

    image_bytes: bytes
    title_name: str
    badge_text: str
    theme_name: str
    background_label: str


class ProfileWorkflow:
    """Prepare and render profile cards independently from the Discord cog."""

    def __init__(
        self,
        repository: UserRepository,
        render_manager: RenderManager,
    ) -> None:
        self.repository = repository
        self.render_manager = render_manager

    async def fetch_avatar_bytes(
        self,
        member_or_user: discord.Member | discord.User,
        *,
        size: int = 128,
        timeout: float = 3.0,
    ) -> bytes:
        """Fetch an avatar while keeping rendering resilient to network failures."""
        try:
            return await asyncio.wait_for(
                member_or_user.display_avatar.with_size(size).read(),
                timeout=timeout,
            )
        except Exception:
            logger.warning(
                "Failed to fetch avatar for user %s.",
                getattr(member_or_user, "id", None),
                exc_info=True,
            )
            return b""

    async def render(
        self,
        member: discord.Member | discord.User,
        guild_id: int,
        *,
        include_rank: bool = False,
        include_background_label: bool = False,
    ) -> ProfileRenderResult:
        """Load profile state and render a profile card."""
        exp, level = await self.repository.get_user(member.id, guild_id)
        title_name = get_title(level)
        next_exp = None if level >= PC.MAX_LEVEL else required_exp(level)
        avatar_bytes = await self.fetch_avatar_bytes(member)

        theme_name, bg_file, font_color = await self.repository.get_user_theme(
            member.id
        )
        user_rank = (
            await self.repository.get_rank(member.id, guild_id)
            if include_rank
            else None
        )

        render_context = RenderContext(
            avatar_bytes=avatar_bytes,
            display_name=member.display_name,
            title_name=title_name,
            level=level,
            exp=exp,
            next_exp=next_exp,
            bg_file=bg_file,
            theme_name=theme_name,
            font_color=font_color,
            user_rank=user_rank,
        )
        image_bytes = await self.render_manager.render_profile(render_context)

        badge_path = AP.TITLE_EMOJI_FILES.get(title_name)
        badge_exists = await asyncio.to_thread(
            self._badge_exists,
            badge_path,
        )
        badge_text = "" if badge_exists else get_title_emoji(level)
        background_label = ""

        if include_background_label:
            background_label = await asyncio.to_thread(
                asset_catalog.background_label,
                theme_name,
                bg_file,
            )

        return ProfileRenderResult(
            image_bytes=image_bytes or b"",
            title_name=title_name,
            badge_text=badge_text,
            theme_name=theme_name,
            background_label=background_label,
        )

    async def reset_and_render(
        self,
        member: discord.Member | discord.User,
        guild_id: int,
    ) -> ProfileRenderResult:
        """Reset a member's theme and return the freshly rendered default card."""
        await self.repository.set_user_theme(
            member.id,
            "default",
            None,
            "white",
        )
        return await self.render(member, guild_id)

    @staticmethod
    def _badge_exists(path: str | None) -> bool:
        """Return whether a configured title badge exists on disk."""
        return bool(path and os.path.exists(path))
