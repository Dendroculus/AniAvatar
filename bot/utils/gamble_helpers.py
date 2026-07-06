"""
This module contains helper classes and functions for the gambling feature. It defines an interactive Discord UI view that allows users to select gamble amounts, including preset options and a custom amount modal. This module depends on cogs.fun for processing the gamble logic.
"""

import discord
from typing import Optional, TYPE_CHECKING
from bot.config.emojis import ShopEmojis
from discord.ext import commands
from bot.config.configs import FunConstants as FC

if TYPE_CHECKING: # NOTE : TYPE_CHECKING ONLY IS USED TOAVOID CIRCULAR IMPORTS
    from bot.cogs.fun import Fun 
    
class GambleView(discord.ui.View):
        """
        Interactive view presented to users to select gamble amounts.

        Lifecycle:
        - Constructed with references to the parent Fun instance and progression cog.
        - The view uses the native Discord.py timeout mechanism.
        - The view manipulates its own disabled state to prevent double submissions.
        """
        def __init__(
            self,
            *,
            fun: "Fun",
            ctx: commands.Context,
            user_id: int,
            guild_id: int,
            progression_cog,
            initial_coins: Optional[int],
            timeout: int = 120,
        ):
            super().__init__(timeout=timeout)
            self.fun = fun
            self.ctx = ctx
            self.bot = fun.bot
            self.user_id = user_id
            self.guild_id = guild_id
            self.progression_cog = progression_cog
            self.message: Optional[discord.Message] = None
            self.initial_coins = initial_coins

            self.options_list = [
                ("100", 100, discord.PartialEmoji(name="Coins", id=1415353285270966403)),
                ("250", 250, discord.PartialEmoji(name="Coins", id=1415353285270966403)),
                ("500", 500, discord.PartialEmoji(name="Coins", id=1415353285270966403)),
                ("All In", -2, discord.PartialEmoji(name="Coins", id=1415353285270966403)),
                ("Custom", -1, None),
            ]
            self.select = self._create_select()
            self.add_item(self.select)

            self.exit_button = discord.ui.Button(label="Exit Gamble", style=discord.ButtonStyle.danger)
            self.exit_button.callback = self.exit_callback
            self.add_item(self.exit_button)

        def _create_select_options(self):
            """
            Helper to build discord.SelectOption objects for the current options_list.
            """
            return [
                discord.SelectOption(label=label, value=str(value), emoji=emoji)
                for label, value, emoji in self.options_list
            ]

        def _create_select(self):
            """
            Construct and return a Select UI element wired to the view's select_callback.
            """
            select = discord.ui.Select(
                placeholder="Select amount to gamble",
                options=self._create_select_options(),
                min_values=1,
                max_values=1,
            )
            select.callback = self.select_callback
            return select

        async def on_timeout(self) -> None:
            """
            Callback invoked when the view times out.
            """
            if self.message:
                try:
                    await self.message.edit(content="❌ Gamble timed out.", embed=None, view=None)
                except (discord.HTTPException, discord.Forbidden, discord.NotFound):
                    pass
            self.fun._set_active_view(self.guild_id, self.user_id, None)

        async def _disable_controls(self):
            """
            Disable all interactive children and attempt to persist the disabled state to the message.
            """
            for item in self.children:
                if hasattr(item, "disabled"):
                    item.disabled = True
            if self.message:
                try:
                    await self.message.edit(view=self)
                except (discord.HTTPException, discord.Forbidden, discord.NotFound):
                    pass

        async def _enable_controls(self):
            """
            Re-enable interactive children and update the message view where possible.
            """
            for item in self.children:
                if hasattr(item, "disabled"):
                    item.disabled = False
            if self.message:
                try:
                    await self.message.edit(view=self)
                except (discord.HTTPException, discord.Forbidden, discord.NotFound):
                    pass

        async def _clear_selection(self):
            """
            Reset the Select to its original set of options and update the message.
            """
            self.select.options = self._create_select_options()
            if self.message:
                try:
                    await self.message.edit(view=self)
                except (discord.HTTPException, discord.Forbidden, discord.NotFound):
                    pass

        def _parse_value_from_interaction(self, interaction: discord.Interaction) -> Optional[int]:
            """
            Parse an integer selection value from the interaction payload or the Select state.

            Returns None for invalid or missing values.
            """
            try:
                value_raw = None
                if isinstance(getattr(interaction, "data", None), dict):
                    value_raw = interaction.data.get("values", [None])[0]
                if value_raw is None:
                    value_raw = self.select.values[0] if getattr(self.select, "values", None) else None
                if value_raw is None:
                    return None
                return int(value_raw)
            except (ValueError, TypeError, KeyError, AttributeError):
                return None

        async def _send_invalid_selection(self, interaction: discord.Interaction) -> None:
            """
            Notify the user that their selection was invalid and reset the selection UI.
            """
            await self.fun._send(self.ctx, interaction, "❌ Invalid selection.", ephemeral=True)
            await self._clear_selection()

        async def _edit_view_after_disable(self, interaction: discord.Interaction) -> None:
            """
            Attempt to persist the view state after controls have been disabled.

            Uses interaction.response.edit_message when possible, otherwise edits the stored message.
            """
            try:
                if not interaction.response.is_done():
                    await interaction.response.edit_message(view=self)
                elif self.message:
                    await self.message.edit(view=self)
            except (discord.HTTPException, discord.Forbidden, discord.NotFound):
                pass

        async def _show_custom_modal(self, interaction: discord.Interaction) -> None:
            """
            Present a small inline Modal for entering a custom gamble amount.

            The inner CustomModal enforces that only the session owner may submit and
            validates the provided amount against the user's current balance.
            """
            await self._clear_selection()

            parent = self

            class CustomModal(discord.ui.Modal):
                def __init__(inner_self):
                    title_text = (
                        "Custom Gamble"
                        if parent.initial_coins is None
                        else f"Custom Gamble (Max {parent.initial_coins})"
                    )
                    super().__init__(title=title_text)
                    inner_self.amount_input = discord.ui.TextInput(
                        label="Enter amount",
                        placeholder="Enter a positive number",
                        style=discord.TextStyle.short,
                    )
                    inner_self.add_item(inner_self.amount_input)

                async def on_submit(inner_self, inter: discord.Interaction):
                    if inter.user.id != parent.user_id:
                        await parent.fun._send(parent.ctx, inter, FC.FALSE_GAMBLE_SESSION, ephemeral=True)
                        return
                    try:
                        amount = int(inner_self.amount_input.value)
                    except (ValueError, TypeError):
                        await parent.fun._send(parent.ctx, inter, "❌ Invalid number.", ephemeral=True)
                        await parent._clear_selection()
                        return
                    latest = await parent.progression_cog.get_coins(parent.user_id, parent.guild_id)
                    if amount <= 0 or amount > latest:
                        await parent.fun._send(
                            parent.ctx,
                            inter,
                            f"❌ Invalid amount. You have {latest} {ShopEmojis['Coins']}.",
                            ephemeral=True,
                        )
                        await parent._clear_selection()
                        return
                    await parent.fun._process_gamble(
                        parent.ctx,
                        inter,
                        guild_id=parent.guild_id,
                        user_id=parent.user_id,
                        progression_cog=parent.progression_cog,
                        amount=amount,
                    )
                    await parent._clear_selection()

            await interaction.response.send_modal(CustomModal())

        async def _handle_bet_value(self, interaction: discord.Interaction, value: int) -> None:
            """
            Core handler for numeric bet values including "All In" (-2) semantics.

            Disables controls during processing to avoid duplicate submissions.
            """
            await self._disable_controls()
            await self._edit_view_after_disable(interaction)

            bet = value
            if value == -2:
                bet = await self.progression_cog.get_coins(self.user_id, self.guild_id)

            if bet <= 0:
                await self.fun._send(self.ctx, interaction, "❌ Invalid bet amount.", ephemeral=True)
                await self._clear_selection()
                await self._enable_controls()
                return

            await self.fun._process_gamble(
                self.ctx,
                interaction,
                guild_id=self.guild_id,
                user_id=self.user_id,
                progression_cog=self.progression_cog,
                amount=bet,
            )
            await self._clear_selection()

        async def select_callback(self, interaction: discord.Interaction):
            """
            Select callback invoked when a user chooses a gamble option.

            Validates session ownership, parses the selection and dispatches to the appropriate handler.
            """
            if interaction.user.id != self.user_id:
                await self.fun._send(self.ctx, interaction, FC.FALSE_GAMBLE_SESSION, ephemeral=True)
                return

            value = self._parse_value_from_interaction(interaction)
            if value is None:
                return await self._send_invalid_selection(interaction)

            if value == -1:
                await self._show_custom_modal(interaction)
                return

            await self._handle_bet_value(interaction, value)

        async def exit_callback(self, interaction: discord.Interaction):
            """
            Exit the gamble UI. Only the session owner may exit; cleans up active view mapping.
            """
            if interaction.user.id != self.user_id:
                await self.fun._send(self.ctx, interaction, FC.FALSE_GAMBLE_SESSION, ephemeral=True)
                return
            self.fun._set_active_view(self.guild_id, self.user_id, None)
            try:
                if not interaction.response.is_done():
                    await interaction.response.edit_message(content="❌ Gamble exited.", embed=None, view=None)
                else:
                    await interaction.message.edit(content="❌ Gamble exited.", embed=None, view=None)
            except (discord.HTTPException, discord.Forbidden, discord.NotFound):
                pass
            self.stop()