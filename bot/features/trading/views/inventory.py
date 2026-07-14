"""Inventory item-use Discord views."""

import asyncio

import discord

from bot.config.configs import TradingConstants as TC
from bot.config.emojis import (
    CustomEmojis,
    MinoriEmojis,
    ShopEmojis,
)
from bot.features.trading.inventory_workflow import (
    InventoryUseResult,
    InventoryWorkflow,
)
from bot.features.trading.view_registry import TradingViewRegistry
from bot.features.trading.views.common import CloseButton


class InventorySelect(discord.ui.Select):
    """
    A dropdown menu for selecting and using inventory items.
    """

    def __init__(
        self,
        workflow: InventoryWorkflow,
        user_id: int,
        guild_id: int,
        items,
        parent_view,
    ) -> None:
        self.workflow = workflow
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

    @staticmethod
    def _build_feedback(result: InventoryUseResult) -> str:
        """Build the existing user-facing item-use confirmation."""

        feedback = f"You used {result.emoji} **{result.item_name}**!"

        if result.item_name in TC.POTION_ITEMS:
            feedback = (
                f"You used {result.emoji} "
                f"**{result.item_name}** and gained "
                f"{result.exp_gain} {CustomEmojis['EXP']}!"
            )

            if result.extra_message:
                feedback += f"\n{result.extra_message}"

        elif result.item_name == TC.MYSTERY_BOX_NAME and result.rewards:
            lines = [
                f"{quantity}x {emoji} {item_name}"
                for item_name, quantity, emoji in result.rewards
            ]
            feedback = (
                f"{ShopEmojis['MysteryBox']} You opened a "
                f"{TC.MYSTERY_BOX_NAME} and got:\n" + "\n".join(lines)
            )

        return feedback

    async def _update_inventory_ui(
        self,
        interaction: discord.Interaction,
        items: tuple[tuple[str, int, str], ...],
        feedback_msg: str,
    ) -> None:
        """Refresh the inventory from workflow-provided database state."""

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

            registry.remove_inventory(
                self.guild_id,
                self.user_id,
            )

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
            self.workflow,
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

    async def callback(
        self,
        interaction: discord.Interaction,
    ) -> None:
        """Process item usage through the inventory workflow."""

        if hasattr(
            self.parent_view,
            "reset_timer",
        ):
            self.parent_view.reset_timer()

        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "⚠️ This is not your inventory!",
                ephemeral=True,
            )
            return

        selected_item = self.values[0]
        await interaction.response.defer()

        result = await self.workflow.use_item(
            user_id=self.user_id,
            guild_id=self.guild_id,
            item_name=selected_item,
            channel=interaction.channel,
        )

        if result.status == "max_level":
            await interaction.followup.send(
                (
                    f"{MinoriEmojis['MinoriWink']} "
                    "You’ve already reached the max level! "
                    "You can’t use "
                    f"{CustomEmojis['EXP']} items anymore."
                ),
                ephemeral=True,
            )
            return

        if result.status == "missing":
            await interaction.followup.send(
                "❌ You don't own this item anymore.",
                ephemeral=True,
            )
            return

        feedback_msg = self._build_feedback(result)

        await self._update_inventory_ui(
            interaction,
            result.inventory,
            feedback_msg,
        )


class InventoryView(discord.ui.View):
    """
    A view presenting the user's inventory with auto-timeout logic.
    """

    def __init__(
        self,
        workflow: InventoryWorkflow,
        user_id,
        guild_id,
        items,
        *,
        registry: TradingViewRegistry,
        timeout=180,
    ) -> None:
        super().__init__(timeout=None)
        self.workflow = workflow
        self.registry = registry
        self.user_id = user_id
        self.guild_id = guild_id
        self.items = items
        self.message = None
        self.timeout_seconds = timeout
        self._timeout_task = None

        select = InventorySelect(
            workflow,
            user_id,
            guild_id,
            items,
            self,
        )
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
