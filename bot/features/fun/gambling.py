"""Gambling session state, validation, and settlement workflow."""

from __future__ import annotations

import random
import time
from typing import Optional

import discord
from discord.ext import commands

from bot.config.configs import FunConstants as FC
from bot.config.emojis import MinoriEmojis, ShopEmojis
from bot.utils.gamble_helpers import GambleView


class GamblingMixin:
    def _cooldown_remaining(self, guild_id: int, user_id: int) -> int:
        """
        Calculate remaining cooldown seconds for a user's gamble session.

        This tracks the specific 'session cooldown' triggered after max attempts,
        separate from the standard command rate limit.
        """
        key = (guild_id, user_id)
        now = time.time()
        expires = self._gamble_cooldowns.get(key)
        if expires and expires > now:
            return int(expires - now)
        return 0

    def _start_session_cooldown(self, guild_id: int, user_id: int) -> None:
        """Start the gamble session cooldown and reset the attempt counter."""
        key = (guild_id, user_id)
        self._gamble_cooldowns[key] = time.time() + FC.GAMBLE_COOLDOWN_SECONDS
        self._gamble_counts.pop(key, None)

    def _count_attempt(self, guild_id: int, user_id: int) -> int:
        """Increment and return the gamble attempt count for the current session."""
        key = (guild_id, user_id)
        new_val = self._gamble_counts.get(key, 0) + 1
        self._gamble_counts[key] = new_val
        return new_val

    def _clear_attempts(self, guild_id: int, user_id: int) -> None:
        """Clear the gamble attempt counter for a user."""
        self._gamble_counts.pop((guild_id, user_id), None)

    def _set_active_view(
        self, guild_id: int, user_id: int, view: Optional[GambleView]
    ) -> None:
        """
        Register or remove the active GambleView for a user.

        Ensures we can locate the specific view instance later to update
        buttons or balances.
        """
        self.active_views.setdefault(guild_id, {})
        if view is None:
            self.active_views[guild_id].pop(user_id, None)
        else:
            self.active_views[guild_id][user_id] = view

    def _get_active_view(self, guild_id: int, user_id: int) -> Optional[GambleView]:
        """Retrieve the active GambleView for a user, if one exists."""
        return self.active_views.get(guild_id, {}).get(user_id)

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

    async def _refresh_gamble_prompt(
        self,
        progression_cog,
        guild_id: int,
        user_id: int,
    ) -> None:
        """
        Refetch user balance and update the active gamble message prompt.
        """
        try:
            vo_inner = self._get_active_view(guild_id, user_id)
            if not vo_inner or not vo_inner.message:
                return
            updated = await progression_cog.get_coins(user_id, guild_id)
            await vo_inner.message.edit(
                content=(
                    f"You have {updated} {ShopEmojis['Coins']}. "
                    "Select amount to gamble:"
                ),
                view=vo_inner,
            )
        except (discord.HTTPException, discord.Forbidden, discord.NotFound):
            pass

    async def _handle_gamble_cooldown_and_disable_view(
        self,
        ctx: commands.Context,
        interaction: discord.Interaction,
        guild_id: int,
        user_id: int,
    ) -> None:
        """
        Triggered when max attempts are reached. Applies internal session
        cooldown and disables UI buttons.
        """
        self._start_session_cooldown(guild_id, user_id)
        await self._send(
            ctx,
            interaction,
            (
                f"{MinoriEmojis['MinoriConfused']} Woah woah you have been "
                "gambling for a while — I think it's time to stop for a while. "
                "You're on cooldown for 5 minutes."
            ),
            ephemeral=True,
        )
        vo = self._get_active_view(guild_id, user_id)
        if vo:
            try:
                await vo._disable_controls()
            except (discord.HTTPException, discord.Forbidden, discord.NotFound):
                pass
            self._set_active_view(guild_id, user_id, None)

    async def _enable_gamble_view_controls_if_any(
        self,
        guild_id: int,
        user_id: int,
    ) -> None:
        """Ensure controls are enabled (if they were previously disabled)."""
        vo = self._get_active_view(guild_id, user_id)
        if not vo:
            return
        try:
            await vo._enable_controls()
        except (discord.HTTPException, discord.Forbidden, discord.NotFound):
            pass

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

    async def _send_gamble_cooldown_message(
        self,
        ctx: commands.Context,
        interaction: Optional[discord.Interaction],
        remaining: int,
    ) -> None:
        """Notify user that they are on gambling cooldown."""
        mins, secs = divmod(remaining, 60)
        await self._send(
            ctx,
            interaction,
            f"{MinoriEmojis['MinoriConfused']} Woah woah you have been gambling for a while, "
            f"please wait for `{mins}m {secs}s` before gambling again.",
            ephemeral=True,
        )

    async def _ensure_progression_cog(
        self,
        ctx: commands.Context,
        interaction: Optional[discord.Interaction],
    ):
        """Check availability of Progression cog."""
        progression_cog = self.bot.get_cog("Progression")
        if not progression_cog:
            await self._send(
                ctx,
                interaction,
                "❌ Progression cog not loaded. Coins unavailable.",
                ephemeral=True,
            )
            return None
        return progression_cog

    async def _ensure_user_has_coins(
        self,
        ctx: commands.Context,
        interaction: Optional[discord.Interaction],
        progression_cog,
        user_id: int,
        guild_id: int,
    ) -> Optional[int]:
        """Check if user has a positive coin balance."""
        user_coins = await progression_cog.get_coins(user_id, guild_id)
        if user_coins <= 0:
            await self._send(
                ctx,
                interaction,
                "❌ You don't have any coins to gamble!",
                ephemeral=True,
            )
            return None
        return user_coins

    async def _send_gamble_prompt(
        self,
        ctx: commands.Context,
        interaction: Optional[discord.Interaction],
        view: "GambleView",
        user_coins: int,
    ) -> Optional[discord.Message]:
        """Send the initial gambling UI prompt."""
        prompt = (
            f"You have {user_coins} {ShopEmojis['Coins']}. Select amount to gamble:"
        )

        if interaction:
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(prompt, view=view)
                    try:
                        return await interaction.original_response()
                    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                        return None
                return await interaction.followup.send(prompt, view=view)
            except (discord.HTTPException, discord.Forbidden, discord.NotFound):
                return await ctx.send(prompt, view=view)

        return await ctx.send(prompt, view=view)

    async def _attach_view_message_from_context(
        self,
        ctx: commands.Context,
        view: "GambleView",
        sent_message: Optional[discord.Message],
    ) -> None:
        """
        Associate the GambleView with the sent message.

        This allows the view to edit the message later (e.g. to update balances
        or disable buttons).
        """
        if isinstance(sent_message, discord.Message):
            view.message = sent_message
            return

        try:
            if ctx.channel:
                last = None
                async for m in ctx.channel.history(limit=1):
                    last = m
                if last:
                    view.message = last
        except (discord.HTTPException, discord.Forbidden):
            view.message = None
