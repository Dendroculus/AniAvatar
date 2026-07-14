"""Message-based experience and level-up workflow."""

from __future__ import annotations

import logging
import random
from typing import Any

import discord
import redis.asyncio as redis
from discord import MessageReference

from bot.config.configs import ProgressionConstants as PC
from bot.config.emojis import CustomEmojis
from bot.features.progression.domain.levels import (
    get_title,
    get_title_emoji,
)
from bot.core.repositories.user_repository import UserRepository

logger = logging.getLogger(__name__)


class ExperienceWorkflow:
    """Award message EXP and announce progression milestones."""

    COOLDOWN_SECONDS = 5

    def __init__(
        self,
        *,
        bot: Any,
        repository: UserRepository,
        redis_client: redis.Redis | None,
    ) -> None:
        self.bot = bot
        self.repository = repository
        self.redis = redis_client
        self._fallback_cooldowns: dict[str, float] = {}

    async def handle_message(
        self,
        message: discord.Message,
    ) -> None:
        """Award EXP for an eligible guild message."""
        if message.author.bot or not message.guild:
            return

        guild_id = message.guild.id
        user_id = message.author.id

        if not await self._claim_cooldown(
            guild_id,
            user_id,
        ):
            return

        old_exp, old_level = await self.repository.get_user(
            user_id,
            guild_id,
        )

        exp_gain = random.randint(
            5 + old_level * 8,
            10 + old_level * 12,
        )

        (
            new_level,
            new_exp,
            leveled_up,
        ) = await self.repository.add_exp(
            user_id,
            guild_id,
            exp_gain,
        )

        if not leveled_up:
            return

        await self._announce_level_up(
            guild_id=guild_id,
            user_id=user_id,
            new_level=new_level,
            old_level=old_level,
            channel=message.channel,
        )

        old_rank = await self.repository.get_rank_for(
            guild_id,
            old_level,
            old_exp,
        )

        new_rank = await self.repository.get_rank_for(
            guild_id,
            new_level,
            new_exp,
        )

        if new_rank < old_rank:
            await self._announce_rank_up(
                message,
                new_rank,
            )

    async def _claim_cooldown(
        self,
        guild_id: int,
        user_id: int,
    ) -> bool:
        """Claim the user's EXP cooldown."""
        cooldown_key = f"cooldown:{guild_id}:{user_id}"

        if self.redis:
            try:
                allowed = await self.redis.set(
                    cooldown_key,
                    b"1",
                    ex=self.COOLDOWN_SECONDS,
                    nx=True,
                )

                if not allowed:
                    return False

                return True

            except Exception:
                logger.warning(
                    "Redis failed during EXP cooldown check for guild=%s user=%s.",
                    guild_id,
                    user_id,
                    exc_info=True,
                )

        now = discord.utils.utcnow().timestamp()

        last_award = self._fallback_cooldowns.get(
            cooldown_key,
            0,
        )

        if now - last_award < self.COOLDOWN_SECONDS:
            return False

        self._fallback_cooldowns[cooldown_key] = now

        return True

    async def _announce_level_up(
        self,
        *,
        guild_id: int,
        user_id: int,
        new_level: int,
        old_level: int,
        channel: discord.abc.Messageable,
    ) -> None:
        """Announce a level-up and award bonus coins."""
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

        level_up_message = await channel.send(embed=embed)

        coin_reward = random.randint(30, 50)

        await self.repository.add_coins(
            user_id,
            guild_id,
            coin_reward,
        )

        await channel.send(
            (
                f"{member.display_name} received "
                f"{PC.coins_emoji()} "
                f"{coin_reward} coins for leveling up!"
            ),
            reference=MessageReference(
                message_id=level_up_message.id,
                channel_id=level_up_message.channel.id,
                guild_id=level_up_message.guild.id,
            ),
        )

    @staticmethod
    async def _announce_rank_up(
        message: discord.Message,
        new_rank: int,
    ) -> None:
        """Announce an improved leaderboard rank."""
        embed = discord.Embed(
            title=(
                f"{CustomEmojis['UPWARDARROW']} Rank Up! {message.author.display_name}"
            ),
            description=(
                "```"
                f"{message.author.display_name} "
                f"has ranked up to #{new_rank} "
                "in the server leaderboard! 🎉"
                "```"
            ),
            color=discord.Color.gold(),
        )

        embed.set_thumbnail(url=message.author.display_avatar.url)

        await message.channel.send(embed=embed)
