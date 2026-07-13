"""Gambling wager reservation and result settlement."""

from __future__ import annotations

import random
from typing import Optional

import discord
from discord.ext import commands

from bot.config.configs import FunConstants as FC
from bot.config.emojis import MinoriEmojis, ShopEmojis


class GamblingSettlementMixin:
    async def _send_insufficient_funds(
        self,
        ctx: commands.Context,
        interaction: discord.Interaction,
        progression_cog,
        guild_id: int,
        user_id: int,
        amount: int,
    ) -> None:
        """
        Notify user of insufficient funds and refresh the gambling UI
        to show their actual balance.
        """
        await self._send(
            ctx,
            interaction,
            f"❌ Could not place bet of {amount} {ShopEmojis['Coins']}. You don't have enough coins.",
            ephemeral=True,
        )
        try:
            new_balance_inner = await progression_cog.get_coins(user_id, guild_id)
            vo_inner = self._get_active_view(guild_id, user_id)
            if vo_inner and vo_inner.message:
                await vo_inner.message.edit(
                    content=(
                        f"You have {new_balance_inner} {ShopEmojis['Coins']}. "
                        "Select amount to gamble:"
                    ),
                    view=vo_inner,
                )
        except (discord.HTTPException, discord.Forbidden, discord.NotFound):
            pass

    async def _settle_win(
        self,
        ctx: commands.Context,
        interaction: discord.Interaction,
        progression_cog,
        guild_id: int,
        user_id: int,
        amount: int,
        pre_balance_val: int,
    ) -> Optional[str]:
        """
        Credit winnings to the user's database balance.

        Returns:
            str: Success message if settlement worked.
            None: If an error occurred (attempts refund).
        """
        try:
            await progression_cog.add_coins(user_id, guild_id, amount * 2)
            if amount == pre_balance_val:
                return (
                    f"{MinoriEmojis['MinoriAmazed']} WOOOAA JACKPOT! "
                    "You just doubled everything you own!"
                )
            return (
                f"{MinoriEmojis['MinoriAmazed']} You won {amount} "
                f"{ShopEmojis['Coins']}!"
            )
        except Exception:
            try:
                await progression_cog.add_coins(user_id, guild_id, amount)
            except Exception:
                pass
            await self._send(
                ctx,
                interaction,
                (
                    "❌ An error occurred while settling your win. "
                    "We've attempted to refund your bet; contact an admin."
                ),
                ephemeral=True,
            )
            return None

    async def _run_single_gamble(
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
        Execute a single gambling round.

        Flow:
        1. Reserve coins (deduct from DB).
        2. Calculate win probability based on bet ratio.
        3. Determine win/loss.
        4. Settle transaction (Add coins if won).
        5. Update UI.
        """
        if amount <= 0:
            await self._send(ctx, interaction, "❌ Invalid bet amount.", ephemeral=True)
            return

        pre_balance = await progression_cog.get_coins(user_id, guild_id)
        reserved = await progression_cog.reserve_coins(user_id, guild_id, amount)
        if not reserved:
            await self._send_insufficient_funds(
                ctx, interaction, progression_cog, guild_id, user_id, amount
            )
            return

        bet_ratio = (amount / pre_balance) if pre_balance else 1
        win_chance = max(0.201, FC.DEFAULT_WIN_PROBABILITY - bet_ratio * 0.5)
        won = random.random() < win_chance

        if won:
            result_text = await self._settle_win(
                ctx,
                interaction,
                progression_cog,
                guild_id,
                user_id,
                amount,
                pre_balance,
            )
            if result_text is None:
                return
        else:
            result_text = (
                f"{MinoriEmojis['MinoriDissapointed']} You lost {amount} "
                f"{ShopEmojis['Coins']}."
            )

        new_balance = await progression_cog.get_coins(user_id, guild_id)
        await self._send(
            ctx,
            interaction,
            (f"{result_text} Your new balance: {new_balance:,} {ShopEmojis['Coins']}."),
        )
        await self._refresh_gamble_prompt(progression_cog, guild_id, user_id)
