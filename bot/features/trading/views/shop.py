"""Shop purchasing Discord views."""

import asyncio
from typing import Awaitable, Callable

import discord

from bot.config.configs import TradingConstants as TC
from bot.features.trading.shop_workflow import (
    ShopPurchaseWorkflow,
)
from bot.features.trading.view_registry import TradingViewRegistry
from bot.features.trading.views.common import (
    CloseButton,
    format_coins,
)

InventoryRefreshCallback = Callable[
    [int, int, object],
    Awaitable[None],
]


class ShopSelect(discord.ui.Select):
    """
    A dropdown menu for purchasing items from the shop.
    """

    def __init__(
        self,
        user_id: int,
        guild_id: int,
        options,
        parent_view,
    ) -> None:
        self.user_id = user_id
        self.guild_id = guild_id
        self.parent_view = parent_view
        self.message = None
        super().__init__(
            placeholder="Select an item to buy...",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(
        self,
        interaction: discord.Interaction,
    ) -> None:
        """Purchase exactly one freshly selected shop item."""

        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "⚠️ You can only buy items for yourself.",
                ephemeral=True,
            )
            return

        if hasattr(
            self.parent_view,
            "reset_timer",
        ):
            self.parent_view.reset_timer()

        if getattr(
            self.parent_view,
            "processing",
            False,
        ):
            await interaction.response.send_message(
                "A purchase is already being processed. Please wait.",
                ephemeral=True,
            )
            return

        selected_item = self.values[0]

        self.parent_view.processing = True
        self.disabled = True

        message = (
            getattr(self, "message", None)
            or getattr(
                self.parent_view,
                "message",
                None,
            )
            or interaction.message
        )

        await interaction.response.defer()

        if message:
            await message.edit(
                view=self.parent_view,
            )

        try:
            result = await self.parent_view.workflow.purchase(
                user_id=self.user_id,
                guild_id=self.guild_id,
                item_name=selected_item,
            )

            if result.status == "missing":
                await interaction.followup.send(
                    "❌ This item no longer exists in the shop.",
                    ephemeral=True,
                )
                return

            if result.status == "insufficient":
                await interaction.followup.send(
                    TC.NOT_ENOUGH_COINS_MSG,
                    ephemeral=True,
                )
                return

            await interaction.followup.send(
                (f"You bought **1x {result.item_name}** {result.emoji}!"),
                ephemeral=True,
            )

        finally:
            self.parent_view.processing = False

            try:
                await self.parent_view.refresh()
            except (
                discord.HTTPException,
                discord.Forbidden,
                discord.NotFound,
            ):
                self.disabled = False

                if message:
                    try:
                        await message.edit(
                            view=self.parent_view,
                        )
                    except (
                        discord.HTTPException,
                        discord.Forbidden,
                        discord.NotFound,
                    ):
                        pass

            try:
                await self.parent_view.refresh_inventory(
                    self.user_id,
                    self.guild_id,
                    interaction.user,
                )
            except (
                discord.HTTPException,
                discord.Forbidden,
                discord.NotFound,
            ):
                pass


class ShopView(discord.ui.View):
    """
    A view for the shop interface, managing timeouts and close logic.
    """

    def __init__(
        self,
        workflow: ShopPurchaseWorkflow,
        user_id: int,
        guild_id: int,
        options,
        *,
        refresh_inventory: InventoryRefreshCallback,
        registry: TradingViewRegistry,
        timeout: int = 180,
    ) -> None:
        super().__init__(timeout=None)
        self.workflow = workflow
        self.user_id = user_id
        self.guild_id = guild_id
        self.options = options
        self.refresh_inventory = refresh_inventory
        self.registry = registry
        self.message = None
        self.timeout_seconds = timeout
        self._timeout_task = None
        self.processing = False

        self.select = ShopSelect(
            self.user_id,
            self.guild_id,
            self.options,
            self,
        )
        self.add_item(self.select)

        close_button = CloseButton(
            owner_id=self.user_id,
            close_text="❌ Shop closed.",
            label="Close Shop",
            on_close=lambda: self.registry.remove_shop(
                self.guild_id,
                self.user_id,
            ),
        )

        self.add_item(close_button)
        self.start_timeout()

    def reset_select(
        self,
        options: list[discord.SelectOption],
    ) -> None:
        """Replace the select to clear its interaction state."""

        old_select = getattr(
            self,
            "select",
            None,
        )

        if old_select is not None:
            self.remove_item(old_select)

        self.options = options

        self.select = ShopSelect(
            self.user_id,
            self.guild_id,
            options,
            self,
        )

        self.select.message = self.message

        self.add_item(self.select)

    async def refresh(self) -> None:
        """Reload shop balance, items, and dropdown state."""

        state = await self.workflow.load_shop(
            user_id=self.user_id,
            guild_id=self.guild_id,
        )
        items = state.items

        if not items:
            timeout_task = getattr(
                self,
                "_timeout_task",
                None,
            )

            if timeout_task:
                timeout_task.cancel()

            self.registry.remove_shop(
                self.guild_id,
                self.user_id,
            )

            if self.message:
                await self.message.edit(
                    content="Shop is empty.",
                    embed=None,
                    view=None,
                )

            return

        embed = discord.Embed(
            title="🛒 Minori Bargains",
            description=(f"Your Coins: **{format_coins(state.balance)}**"),
            color=discord.Color.dark_purple(),
        )

        embed.set_thumbnail(url=TC.SHOP_ICON_URL)

        options = []

        for item in items:
            embed.add_field(
                name=f"{item.emoji} {item.name}",
                value=f"{item.price} coins",
                inline=False,
            )

            options.append(
                discord.SelectOption(
                    label=item.name,
                    description=(f"Buy {item.name} for {item.price} coins"),
                    emoji=item.emoji,
                    value=item.name,
                )
            )

        self.reset_select(options)

        if self.message:
            await self.message.edit(
                content=None,
                embed=embed,
                view=self,
            )

    def start_timeout(self):
        """Initialize or restart the timeout task."""
        if self._timeout_task:
            self._timeout_task.cancel()
        self._timeout_task = asyncio.create_task(self._timeout_loop())

    async def _timeout_loop(self):
        """Close the shop after inactivity."""
        await asyncio.sleep(self.timeout_seconds)
        if self.message:
            try:
                await self.message.edit(
                    content="❌ Shop closed.",
                    embed=None,
                    view=None,
                )
            except (
                discord.HTTPException,
                discord.NotFound,
                discord.Forbidden,
            ):
                pass

        self.registry.remove_shop(
            self.guild_id,
            self.user_id,
        )

    def reset_timer(self):
        """Reset the internal timer."""
        self.start_timeout()
