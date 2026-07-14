"""Gambling workflow orchestration."""

from __future__ import annotations

import discord
from discord.ext import commands

from bot.config.configs import FunConstants as FC
from bot.features.fun.gambling.prompts import (
    GamblingPromptMixin,
)
from bot.features.fun.gambling.session import (
    GamblingSessionMixin,
)
from bot.features.fun.gambling.settlement import (
    GamblingSettlementMixin,
)


class GamblingMixin(
    GamblingSessionMixin,
    GamblingSettlementMixin,
    GamblingPromptMixin,
):
    """Compose gambling state, settlement, and UI workflows."""

    async def _process_gamble(
        self,
        ctx: commands.Context,
        interaction: discord.Interaction,
        *,
        guild_id: int,
        user_id: int,
        progression_cog,
        amount: int,
    ) -> None:
        """
        Orchestrate the gambling process, including cooldown management.

        Called by the GambleView when a bet button is clicked.
        """
        await self._run_single_gamble(
            ctx,
            interaction,
            guild_id=guild_id,
            user_id=user_id,
            progression_cog=progression_cog,
            amount=amount,
        )

        count = self._count_attempt(guild_id, user_id)
        if count >= FC.GAMBLE_MAX_ATTEMPTS:
            await self._handle_gamble_cooldown_and_disable_view(
                ctx, interaction, guild_id, user_id
            )
            return

        await self._enable_gamble_view_controls_if_any(guild_id, user_id)
