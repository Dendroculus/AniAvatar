"""Gambling validation, prompts, and view coordination."""

from __future__ import annotations

from typing import Optional

import discord
from discord.ext import commands

from bot.config.emojis import MinoriEmojis, ShopEmojis
from bot.features.fun.gambling.view import GambleView


class GamblingPromptMixin:
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
