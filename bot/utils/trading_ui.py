import discord
import asyncio
from bot.config.configs import TradingConstants as TC, ProgressionConstants as PC
from bot.config.emojis import MinoriEmojis, ShopEmojis, CustomEmojis

"""
tradingUI.py

Provides the Discord UI components (Views, Selects, Buttons) for the
shop and inventory systems. Handles user interaction logic for buying
and using items.
"""


def format_coins(coins: int) -> str:
    """
    Format a coin integer into a compact human-readable string.
    """
    if coins < 1_000:
        return str(coins)
    elif coins < 1_000_000:
        return f"{coins / 1_000:.2f}K".rstrip("0").rstrip(".")
    elif coins < 1_000_000_000:
        return f"{coins / 1_000_000:.2f}M".rstrip("0").rstrip(".")
    else:
        return f"{coins / 1_000_000_000:.2f}B".rstrip("0").rstrip(".")


class CloseButton(discord.ui.Button):
    """
    A reusable 'Close' button for shop and inventory views.
    """

    def __init__(
        self,
        owner_id: int,
        close_text: str,
        label: str = "Close",
        menu_type: str = None,
        cog=None,
        guild_id: int = None,
    ):
        self.guild_id = guild_id
        super().__init__(label=label, style=discord.ButtonStyle.danger)
        self.owner_id = owner_id
        self.close_text = close_text
        self.menu_type = menu_type
        self.cog = cog

    async def callback(self, interaction: discord.Interaction):
        """Handle button click to close the menu."""
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "⚠️ This is not your menu!", ephemeral=True
            )
            return

        if self.menu_type == "shop":
            self.cog.open_shops.get(self.guild_id, {}).pop(self.owner_id, None)
        elif self.menu_type == "inventory":
            self.cog.open_inventories.get(self.guild_id, {}).pop(self.owner_id, None)

        t = getattr(self.view, "_timeout_task", None)
        if t:
            t.cancel()

        await interaction.response.edit_message(
            content=self.close_text, embed=None, view=None
        )


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
        self, interaction: discord.Interaction, feedback_msg: str
    ):
        """Helper to fetch updated inventory and refresh the Discord view."""
        items = await self.cog.trading_repo.get_user_inventory(
            self.user_id, self.guild_id
        )

        if not items:
            await interaction.edit_original_response(
                embed=None, view=None, content="🧯 Your inventory is now empty."
            )
            await interaction.followup.send(feedback_msg, ephemeral=True)
            return

        inventory_text = "\n".join(
            f"{emoji} {name} x{qty}" for name, qty, emoji in items
        )
        embed = discord.Embed(
            title=f"{interaction.user.display_name}'s Inventory",
            description=inventory_text,
            color=discord.Color.dark_purple(),
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)

        new_view = InventoryView(self.cog, self.user_id, self.guild_id, items)
        await interaction.edit_original_response(embed=embed, view=new_view)
        await interaction.followup.send(feedback_msg, ephemeral=True)

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

    def __init__(self, cog, user_id, guild_id, items, timeout=180):
        super().__init__(timeout=None)
        self.cog = cog
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
            menu_type="inventory",
            cog=self.cog,
            guild_id=self.guild_id,
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

        if self.cog:
            self.cog.open_inventories.get(self.guild_id, {}).pop(self.user_id, None)

    def reset_timer(self):
        """Reset the internal timer to prevent premature closing."""
        self.start_timeout()


class ShopSelect(discord.ui.Select):
    """
    A dropdown menu for purchasing items from the shop.
    """

    def __init__(self, progression_cog, user_id, guild_id, options, parent_view):
        self.progression_cog = progression_cog
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

    async def callback(self, interaction: discord.Interaction):
        """Handle purchase logic: validate funds, deduct cost, add item."""
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "⚠️ You can only buy items for yourself.", ephemeral=True
            )
            return

        if hasattr(self.parent_view, "reset_timer"):
            self.parent_view.reset_timer()

        if getattr(self.parent_view, "processing", False):
            await interaction.response.send_message(
                "A purchase is already being processed. Please wait.", ephemeral=True
            )
            return

        self.parent_view.processing = True
        self.disabled = True
        msg_to_edit = getattr(self, "message", None) or getattr(
            self.parent_view, "message", None
        )

        await interaction.response.defer()
        if msg_to_edit:
            await msg_to_edit.edit(view=self.parent_view)

        try:
            selected_item = self.values[0]
            # Access Repo via Parent Cog
            repo = self.parent_view.parent_cog.trading_repo

            # Fetch Price/Emoji via Repo
            details = await repo.get_item_details(selected_item)

            if not details:
                await interaction.followup.send(
                    "❌ This item no longer exists in the shop.", ephemeral=True
                )
                return
            price, selected_emoji = details["price"], details["emoji"]

            # Check coins using the wrapper passed in __init__ (EconomyServiceWrapper)
            coins = await self.progression_cog.get_coins(self.user_id, self.guild_id)
            if coins < price:
                await interaction.followup.send(TC.NOT_ENOUGH_COINS_MSG, ephemeral=True)
                return

            ok = await self.progression_cog.remove_coins(
                self.user_id, self.guild_id, price
            )
            if not ok:
                await interaction.followup.send(TC.NOT_ENOUGH_COINS_MSG, ephemeral=True)
                return

            # Add Item via Repo
            await repo.add_item(self.user_id, self.guild_id, selected_item, 1)

            # Refresh Data
            new_balance = await self.progression_cog.get_coins(
                self.user_id, self.guild_id
            )
            items = await repo.get_shop_items()

            embed = discord.Embed(
                title="🛒 Minori Bargains",
                description=f"Your Coins: **{format_coins(new_balance)}**",
                color=discord.Color.dark_purple(),
            )
            embed.set_thumbnail(url=TC.SHOP_ICON_URL)

            new_options = []
            for r in items:
                name, item_price, item_emoji = r["name"], r["price"], r["emoji"]
                embed.add_field(
                    name=f"{item_emoji} {name}",
                    value=f"{item_price} coins",
                    inline=False,
                )
                new_options.append(
                    discord.SelectOption(
                        label=name,
                        description=f"Buy {name} for {item_price} coins",
                        emoji=item_emoji,
                        value=name,
                    )
                )
            self.options = new_options

            if msg_to_edit:
                await msg_to_edit.edit(embed=embed, view=self.parent_view)
            else:
                await interaction.followup.edit_message(
                    interaction.message.id, embed=embed, view=self.parent_view
                )

            await interaction.followup.send(
                f"You bought **1x {selected_item}** {selected_emoji}!", ephemeral=True
            )

        finally:
            self.disabled = False
            self.parent_view.processing = False
            if msg_to_edit:
                await msg_to_edit.edit(view=self.parent_view)


class ShopView(discord.ui.View):
    """
    A view for the shop interface, managing timeouts and close logic.
    """

    def __init__(
        self, progression_cog, user_id, guild_id, options, parent_cog, timeout=180
    ):
        super().__init__(timeout=None)
        self.progression_cog = progression_cog
        self.user_id = user_id
        self.guild_id = guild_id
        self.options = options
        self.parent_cog = parent_cog
        self.message = None
        self.timeout_seconds = timeout
        self._timeout_task = None
        self.processing = False

        self.select = ShopSelect(
            self.progression_cog, self.user_id, self.guild_id, self.options, self
        )
        self.add_item(self.select)

        close_button = CloseButton(
            owner_id=self.user_id,
            close_text="❌ Shop closed.",
            label="Close Shop",
            menu_type="shop",
            cog=self.parent_cog,
            guild_id=self.guild_id,
        )

        self.add_item(close_button)
        self.start_timeout()

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
                    content="❌ Shop closed.", embed=None, view=None
                )
            except (discord.HTTPException, discord.NotFound, discord.Forbidden):
                pass

        if self.parent_cog:
            self.parent_cog.open_shops.get(self.guild_id, {}).pop(self.user_id, None)

    def reset_timer(self):
        """Reset the internal timer."""
        self.start_timeout()
