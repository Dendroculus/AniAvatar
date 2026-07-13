"""Consumable-item effects for the trading feature."""

from __future__ import annotations

import random
from typing import Any

import discord

from bot.config.configs import (
    ProgressionConstants as PC,
    TradingConstants as TC,
)
from bot.config.emojis import CustomEmojis
from bot.services.trading_repository import (
    TradingRepository,
)
from bot.services.user_repository import (
    UserRepository,
)
from bot.utils.progression.profile_cards import (
    get_title,
    get_title_emoji,
)


class ItemEffectService:
    """Apply inventory-item effects and rewards."""

    def __init__(
        self,
        *,
        bot: Any,
        user_repository: UserRepository,
        trading_repository: TradingRepository,
    ) -> None:
        self.bot = bot
        self.user_repository = user_repository
        self.trading_repository = trading_repository

    async def apply_potion_effect(
        self,
        user_id: int,
        guild_id: int,
        item_name: str,
        channel: discord.TextChannel | None = None,
    ) -> tuple[int, str]:
        """Apply an EXP potion or level-skip token."""
        potion_effects = {
            TC.SMALL_EXP_POTION: 0.03,
            TC.MEDIUM_EXP_POTION: 0.12,
            TC.LARGE_EXP_POTION: 0.225,
        }

        exp, level = await self.user_repository.get_user(
            user_id,
            guild_id,
        )

        if level >= PC.MAX_LEVEL:
            return 0, ""

        required_exp = 50 * level + 20 * level**2

        if item_name == TC.LEVEL_SKIP_TOKEN:
            remaining = required_exp - exp

            gain = remaining if remaining > 0 else required_exp

        elif item_name in potion_effects:
            gain = int(required_exp * potion_effects[item_name])

        else:
            return 0, ""

        old_level = level

        (
            new_level,
            _,
            leveled_up,
        ) = await self.user_repository.add_exp(
            user_id,
            guild_id,
            gain,
        )

        if leveled_up and channel:
            await self._send_level_up_announcement(
                guild_id=guild_id,
                user_id=user_id,
                new_level=new_level,
                old_level=old_level,
                channel=channel,
            )

        return gain, ""

    async def apply_mystery_box(
        self,
        user_id: int,
        guild_id: int,
    ) -> list[tuple[str, int]]:
        """Open a mystery box and store its rewards."""
        rewards: list[tuple[str, int]] = []

        if random.random() < 0.15:
            rewards.append(
                (
                    TC.LEVEL_SKIP_TOKEN,
                    random.randint(1, 3),
                )
            )

        if random.random() < 0.20:
            rewards.append(
                (
                    TC.LARGE_EXP_POTION,
                    random.randint(1, 3),
                )
            )

        if random.random() < 0.50:
            rewards.append(
                (
                    TC.MEDIUM_EXP_POTION,
                    random.randint(1, 3),
                )
            )

        rewards.append(
            (
                TC.SMALL_EXP_POTION,
                3,
            )
        )

        for item_name, quantity in rewards:
            await self.trading_repository.add_item(
                user_id,
                guild_id,
                item_name,
                quantity,
            )

        return rewards

    async def _send_level_up_announcement(
        self,
        *,
        guild_id: int,
        user_id: int,
        new_level: int,
        old_level: int,
        channel: discord.abc.Messageable,
    ) -> None:
        """Send the level-up produced by an item."""
        guild = self.bot.get_guild(guild_id)

        if not guild:
            return

        member = guild.get_member(user_id)

        if not member:
            return

        old_title = get_title(old_level)
        new_title = get_title(new_level)

        old_emoji = get_title_emoji(old_level)
        new_emoji = get_title_emoji(new_level)

        if new_title != old_title:
            embed_title = (
                f"{member.display_name} "
                f"{CustomEmojis['UPWARDARROW']} "
                f"{new_level}    "
                f"{old_emoji} "
                f"{CustomEmojis['RIGHTWARDARROW']} "
                f"{new_emoji}"
            )

            embed_description = (
                "```"
                f"Congratulations {member.display_name}! "
                f"You have reached level {new_level} "
                f"and ascended to {new_title}. "
                "```\n"
                f"Title: `{new_title}` {new_emoji}"
            )

        else:
            embed_title = (
                f"{member.display_name} {CustomEmojis['UPWARDARROW']} {new_level}"
            )

            embed_description = (
                "```"
                f"Congratulations {member.display_name}! "
                f"You have reached level {new_level}."
                "```\n"
                f"Title: `{new_title}` {new_emoji}"
            )

        embed = discord.Embed(
            title=embed_title,
            description=embed_description,
            color=discord.Color.green(),
        )

        embed.set_thumbnail(url=member.display_avatar.url)

        try:
            await channel.send(embed=embed)

        except discord.HTTPException:
            pass
