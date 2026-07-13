"""Inventory item-use Discord views."""

import asyncio

import discord

from bot.config.configs import (
    ProgressionConstants as PC,
    TradingConstants as TC,
)
from bot.config.emojis import (
    CustomEmojis,
    MinoriEmojis,
    ShopEmojis,
)
from bot.features.trading.view_registry import TradingViewRegistry
from bot.features.trading.views.common import CloseButton


class InventorySelect(discord.ui.Select):
    """
    A dropdown menu for selecting and using inventory items.
    """

    def __init__(self, cog, user_id, guild_id, items, parent_view):
        self.cog = cog
        self.user_id = user_id
        self.guild_id = guild_id
        self.items_data = items
        self.parent_view = parent_view
        self.registry = parent_view.registry

        options = [
            discord.SelectOption(
                label=name,
                description=f"You own {qty} of this item.",
                emoji=emoji,
                value=name,
            )
            for name, qty, emoji in items
            if qty > 0
        ]
        super().__init__(
            placeholder="Choose an item to use...",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def on_timeout(self):
        """Disable component on timeout."""
        for child in self.children:
            child.disabled = True
        if hasattr(self, "message") and self.message:
            await self.message.edit(view=self)

    async def _check_level_cap(
        self, interaction: discord.Interaction, item: str
    ) -> bool:
        """Helper to check if the user is at max level before using EXP items."""
        if item not in TC.POTION_ITEMS:
            return False

        _, level = await self.cog.user_repo.get_user(self.user_id, self.guild_id)
        if level >= PC.MAX_LEVEL:
            await interaction.followup.send(
                f"{MinoriEmojis['MinoriWink']} You’ve already reached the max level! You can’t use {CustomEmojis['EXP']} items anymore.",
                ephemeral=True,
            )
            return True
        return False

    async def _apply_item_effects(
        self, interaction: discord.Interaction, item: str, emoji: str
    ) -> str:
        """Helper to apply the specific effects of an item and generate feedback text."""
        feedback = f"You used {emoji} **{item}**!"

        if item in TC.POTION_ITEMS:
            gain, extra_msg = await self.cog.apply_potion_effect(
                self.user_id, self.guild_id, item, interaction.channel
            )
            feedback = (
                f"You used {emoji} **{item}** and gained {gain} {CustomEmojis['EXP']}!"
            )
            if extra_msg:
                feedback += f"\n{extra_msg}"

        elif item == TC.MYSTERY_BOX_NAME:
            rewards = await self.cog.apply_mystery_box(self.user_id, self.guild_id)
            if rewards:
                lines = []
                for r_item, r_qty in rewards:
                    d = await self.cog.trading_repo.get_item_details(r_item)
                    em = d["emoji"] if d else "📦"
                    lines.append(f"{r_qty}x {em} {r_item}")
                feedback = (
                    f"{ShopEmojis['MysteryBox']} You opened a {TC.MYSTERY_BOX_NAME} and got:\n"
                    + "\n".join(lines)
                )

        return feedback

    async def _update_inventory_ui(
        self,
        interaction: discord.Interaction,
        feedback_msg: str,
    ) -> None:
        """Refresh the inventory from current database state."""

        items = await self.cog.trading_repo.get_user_inventory(
            self.user_id,
            self.guild_id,
        )

        timeout_task = getattr(
            self.parent_view,
            "_timeout_task",
            None,
        )

        if timeout_task:
            timeout_task.cancel()

        registry = self.registry

        if not items:
            await interaction.edit_original_response(
                embed=None,
                view=None,
                content="🧯 Your inventory is now empty.",
            )

            registry.remove_inventory(self.guild_id, self.user_id)

            await interaction.followup.send(
                feedback_msg,
                ephemeral=True,
            )
            return

        inventory_text = "\n".join(
            f"{emoji} {name} x{qty}" for name, qty, emoji in items
        )

        embed = discord.Embed(
            title=(f"{interaction.user.display_name}'s Inventory"),
            description=inventory_text,
            color=discord.Color.dark_purple(),
        )

        embed.set_thumbnail(url=interaction.user.display_avatar.url)

        new_view = InventoryView(
            self.cog,
            self.user_id,
            self.guild_id,
            items,
            registry=registry,
        )

        updated_message = await interaction.edit_original_response(
            content=None,
            embed=embed,
            view=new_view,
        )

        new_view.message = updated_message

        registry.register_inventory(
            self.guild_id,
            self.user_id,
            new_view,
        )

        await interaction.followup.send(
            feedback_msg,
            ephemeral=True,
        )

    async def callback(self, interaction: discord.Interaction):
        """Process item usage, deduct from DB, and apply effects."""
        if hasattr(self.parent_view, "reset_timer"):
            self.parent_view.reset_timer()

        if interaction.user.id != self.user_id:
            return await interaction.response.send_message(
                "⚠️ This is not your inventory!", ephemeral=True
            )

        selected_item = self.values[0]
        await interaction.response.defer()

        # 1. Check Level Cap
        if await self._check_level_cap(interaction, selected_item):
            return

        # 2. Use Item (Deduct quantity)
        repo = self.cog.trading_repo
        new_qty = await repo.use_item(self.user_id, self.guild_id, selected_item)

        if new_qty is None:
            return await interaction.followup.send(
                "❌ You don't own this item anymore.", ephemeral=True
            )

        # 3. Apply Effects
        details = await repo.get_item_details(selected_item)
        selected_emoji = details["emoji"] if details else "📦"

        feedback_msg = await self._apply_item_effects(
            interaction, selected_item, selected_emoji
        )

        # 4. Refresh UI
        await self._update_inventory_ui(interaction, feedback_msg)


class InventoryView(discord.ui.View):
    """
    A view presenting the user's inventory with auto-timeout logic.
    """

    def __init__(
        self,
        cog,
        user_id,
        guild_id,
        items,
        *,
        registry: TradingViewRegistry,
        timeout=180,
    ):
        super().__init__(timeout=None)
        self.cog = cog
        self.registry = registry
        self.user_id = user_id
        self.guild_id = guild_id
        self.items = items
        self.message = None
        self.timeout_seconds = timeout
        self._timeout_task = None

        select = InventorySelect(cog, user_id, guild_id, items, self)
        self.add_item(select)
        close_button = CloseButton(
            owner_id=user_id,
            close_text="❌ Inventory closed.",
            label="Close Inventory",
            on_close=lambda: self.registry.remove_inventory(
                self.guild_id,
                self.user_id,
            ),
        )
        self.add_item(close_button)

        self.start_timeout()

    def start_timeout(self):
        """Initialize or reset the inactivity timeout task."""
        if self._timeout_task:
            self._timeout_task.cancel()
        self._timeout_task = asyncio.create_task(self._timeout_loop())

    async def _timeout_loop(self):
        """Wait for the timeout period, then close the view."""
        await asyncio.sleep(self.timeout_seconds)
        if self.message:
            try:
                await self.message.edit(
                    content="❌ Inventory closed.", embed=None, view=None
                )
            except (discord.HTTPException, discord.NotFound, discord.Forbidden):
                pass

        self.registry.remove_inventory(self.guild_id, self.user_id)

    def reset_timer(self):
        """Reset the internal timer to prevent premature closing."""
        self.start_timeout()
