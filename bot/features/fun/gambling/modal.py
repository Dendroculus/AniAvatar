"""Custom amount modal for interactive gambling."""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord

from bot.config.configs import FunConstants as FC
from bot.config.emojis import ShopEmojis

if TYPE_CHECKING:
    from bot.features.fun.gambling.view import (
        GambleView,
    )


class CustomGambleModal(discord.ui.Modal):
    """Collect and validate a custom gambling amount."""

    def __init__(
        self,
        parent: GambleView,
    ) -> None:
        self.parent = parent

        title = (
            "Custom Gamble"
            if parent.initial_coins is None
            else (f"Custom Gamble (Max {parent.initial_coins})")
        )

        super().__init__(title=title)

        self.amount_input = discord.ui.TextInput(
            label="Enter amount",
            placeholder="Enter a positive number",
            style=discord.TextStyle.short,
        )

        self.add_item(self.amount_input)

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ) -> None:
        """Validate the amount and dispatch the wager."""

        parent = self.parent

        if interaction.user.id != parent.user_id:
            await parent.fun._send(
                parent.ctx,
                interaction,
                FC.FALSE_GAMBLE_SESSION,
                ephemeral=True,
            )
            return

        try:
            amount = int(self.amount_input.value)
        except (TypeError, ValueError):
            await parent.fun._send(
                parent.ctx,
                interaction,
                "? Invalid number.",
                ephemeral=True,
            )
            await parent._clear_selection()
            return

        latest_balance = await parent.progression_cog.get_coins(
            parent.user_id,
            parent.guild_id,
        )

        if amount <= 0 or amount > latest_balance:
            await parent.fun._send(
                parent.ctx,
                interaction,
                (f"? Invalid amount. You have {latest_balance} {ShopEmojis['Coins']}."),
                ephemeral=True,
            )
            await parent._clear_selection()
            return

        await parent.fun._process_gamble(
            parent.ctx,
            interaction,
            guild_id=parent.guild_id,
            user_id=parent.user_id,
            progression_cog=(parent.progression_cog),
            amount=amount,
        )

        await parent._clear_selection()
