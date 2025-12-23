import discord
import asyncio
from constants.configs import TradingConstants as TC
from constants.emojis import MinoriEmojis, ShopEmojis

def format_coins(coins: int) -> str:
    """
    Format a coin integer into a compact human-readable string.

    Examples:
    - 532 -> "532"
    - 12500 -> "12.5K"
    - 2000000 -> "2M"

    Args:
        coins: integer number of coins.

    Returns:
        A string with suffix K/M/B as appropriate and trimmed trailing zeros.
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
    A reusable 'Close' button for views (shop/inventory).

    Attributes:
        owner_id: ID of the user who opened the menu (only they may close it).
        close_text: message to display after closing.
        menu_type: "shop" or "inventory" to allow the cog to update open_shops/open_inventories.
        cog: reference to the Trading cog for state updates.
        guild_id: guild id used as key to manage open menus.
    """
    def __init__(self, owner_id: int, close_text: str, label: str = "Close", menu_type: str = None, cog=None, guild_id: int = None):
        self.guild_id = guild_id
        super().__init__(label=label, style=discord.ButtonStyle.danger)
        self.owner_id = owner_id
        self.close_text = close_text
        self.menu_type = menu_type
        self.cog = cog

    async def callback(self, interaction: discord.Interaction):
        """
        Close the menu if invoked by the original owner; otherwise send an ephemeral error.
        Cancels any view timeout task and edits the message to display close_text.
        """
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("⚠️ This is not your menu!", ephemeral=True)
            return

        if self.menu_type == "shop":
            self.cog.open_shops.get(self.guild_id, {}).pop(self.owner_id, None)
        elif self.menu_type == "inventory":
            self.cog.open_inventories.get(self.guild_id, {}).pop(self.owner_id, None)

        t = getattr(self.view, "_timeout_task", None)
        if t:
            t.cancel()

        await interaction.response.edit_message(content=self.close_text, embed=None, view=None)


class InventorySelect(discord.ui.Select):
    """
    A Select UI component representing the user's inventory items.

    When an item is selected:
    - Verifies the user and locks their actions.
    - Validates that they still own the item.
    - Applies item effects (potion or mystery box) by calling cog helper methods.
    - Updates the DB inventory and returns an updated InventoryView or a message if empty.

    Parameters:
        cog: reference to Trading cog.
        user_id: the user who owns this inventory.
        guild_id: guild id.
        items: iterable of tuples (name, qty, emoji).
        parent_view: the parent InventoryView for timer resets.
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
                value=name
            )
            for name, qty, emoji in items if qty > 0
        ]
        super().__init__(placeholder="Choose an item to use...", min_values=1, max_values=1, options=options)
        
    async def on_timeout(self):
        """
        Disable children and edit the message when the select times out.
        """
        for child in self.children:
            child.disabled = True
        if hasattr(self, "message") and self.message:
            await self.message.edit(view=self)

    async def callback(self, interaction: discord.Interaction):
        """
        Handle the selection of an inventory item:
        - Ensures only the owner can interact.
        - Deducts the item from DB and applies effects if applicable.
        - Rebuilds and sends an updated inventory embed or a message if empty.
        """
        if hasattr(self.parent_view, "reset_timer"):
            self.parent_view.reset_timer()
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("⚠️ This is not your inventory!", ephemeral=True)
            return

        try:
            selected_item = self.values[0]
            await interaction.response.defer()
            pool = self.cog.progression_cog.pool

            async with pool.acquire() as conn:
                await self.cog._set_stmt_timeout(conn)
                row = await conn.fetchrow(TC.SQL_SELECT_PRICE_EMOJI, selected_item)
                selected_emoji = row["emoji"] if row and row["emoji"] else "📦"

                # Atomic decrement; prevents race conditions without Python locks
                async with conn.transaction():
                    deducted = await conn.fetchrow(
                        """
                        UPDATE user_inventory
                        SET quantity = quantity - 1
                        WHERE user_id = $1 AND guild_id = $2 AND item_name = $3 AND quantity > 0
                        RETURNING quantity
                        """,
                        self.user_id, self.guild_id, selected_item
                    )
                    if not deducted:
                        await interaction.followup.send("❌ You don't own this item anymore.", ephemeral=True)
                        return

                    if selected_item in TC.POTION_ITEMS:
                        row_lvl = await conn.fetchrow(
                            "SELECT level FROM users WHERE user_id = $1 AND guild_id = $2",
                            self.user_id, self.guild_id
                        )
                        if row_lvl and row_lvl["level"] >= self.cog.progression_cog.MAX_LEVEL:
                            await interaction.followup.send(f"{MinoriEmojis['MinoriWink']} You’ve already reached the max level! You can’t use {TC.EXP_EMOJI} items anymore.", ephemeral=True)
                            return

                    if deducted["quantity"] <= 0:
                        await conn.execute(
                            "DELETE FROM user_inventory WHERE user_id = $1 AND guild_id = $2 AND item_name = $3",
                            self.user_id, self.guild_id, selected_item
                        )

            feedback_msg = f"You used {selected_emoji} **{selected_item}**!"

            if selected_item in TC.POTION_ITEMS:
                gain, extra_msg = await self.cog.apply_potion_effect(
                    self.user_id, self.guild_id, selected_item, interaction.channel
                )
                feedback_msg = f"You used {selected_emoji} **{selected_item}** and gained {gain} {TC.EXP_EMOJI}!"
                if extra_msg:
                    feedback_msg += f"\n{extra_msg}" 
                    
            if selected_item == TC.MYSTERY_BOX_NAME:
                rewards = await self.cog.apply_mystery_box(self.user_id, self.guild_id)
                if rewards:
                    reward_lines = []
                    # fetch emojis mapping
                    async with self.cog.progression_cog.pool.acquire() as conn:
                        await self.cog._set_stmt_timeout(conn)
                        emap_rows = await conn.fetch("SELECT name, emoji FROM shop_items")
                        emap = {r["name"]: r["emoji"] for r in emap_rows}
                    for item, qty in rewards:
                        emoji = emap.get(item, "📦")
                        reward_lines.append(f"{qty}x {emoji} {item}")
                    feedback_msg = f"{ShopEmojis['MysteryBox']} You opened a {TC.MYSTERY_BOX_NAME} and got:\n" + "\n".join(reward_lines)

            # reload inventory
            async with self.cog.progression_cog.pool.acquire() as conn:
                await self.cog._set_stmt_timeout(conn)
                raw_items = await conn.fetch(TC.SQL_USER_INV_SELECT, self.user_id, self.guild_id)

                items = []
                for name, qty in raw_items:
                    if qty <= 0:
                        continue
                    erow = await conn.fetchrow("SELECT emoji FROM shop_items WHERE name = $1", name)
                    emoji = erow["emoji"] if erow else "📦"
                    items.append((name, qty, emoji))

            if not items:
                await interaction.edit_original_response(embed=None, view=None, content="🧯 Your inventory is now empty.")
                await interaction.followup.send(feedback_msg, ephemeral=True)
                return

            inventory_text = "\n".join(f"{emoji} {name} x{qty}" for name, qty, emoji in items)
            embed = discord.Embed(
                title=f"{interaction.user.display_name}'s Inventory",
                description=inventory_text,
                color=discord.Color.dark_purple()
            )
            embed.set_thumbnail(url=interaction.user.display_avatar.url)

            new_view = InventoryView(self.cog, self.user_id, self.guild_id, items)
            await interaction.edit_original_response(embed=embed, view=new_view)
            await interaction.followup.send(feedback_msg)

        finally:
            # no Python lock release needed; DB handled concurrency
            pass


class InventoryView(discord.ui.View):
    """
    A view that shows a user's inventory and handles automatic timeout.

    Attributes:
        cog: reference to the Trading cog.
        user_id: ID of inventory owner.
        guild_id: ID of the guild.
        items: list of (name, qty, emoji).
        timeout_seconds: seconds before the view auto-closes.
        _timeout_task: background task that enforces the timeout.
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
        close_button = CloseButton(owner_id=user_id, close_text="❌ Inventory closed.", label="Close Inventory", menu_type="inventory", cog=self.cog, guild_id=self.guild_id)
        self.add_item(close_button)

        self.start_timeout()

    def start_timeout(self):
        """
        Start or restart the background timeout loop.
        """
        if self._timeout_task:
            self._timeout_task.cancel()
        self._timeout_task = asyncio.create_task(self._timeout_loop())

    async def _timeout_loop(self):
        """
        Sleep for timeout_seconds then close the view and remove it from the cog tracking.
        """
        await asyncio.sleep(self.timeout_seconds)
        if self.message:
            try:
                await self.message.edit(content="❌ Inventory closed.", embed=None, view=None)
            except (discord.HTTPException, discord.NotFound, discord.Forbidden):
                pass
            
        if self.cog:
            self.cog.open_inventories.get(self.guild_id, {}).pop(self.user_id, None)

    def reset_timer(self):
        """
        External callers (selects) can reset the timeout to keep the view alive.
        """
        self.start_timeout()


class ShopSelect(discord.ui.Select):
    """
    A Select UI component used in the shop view that lets a user buy one of the available items.

    When an item is selected:
    - Validates ownership of the menu.
    - Checks price and user's coins via progression_cog.
    - Deducts coins and adds the item to the user's inventory.
    - Updates the shop embed/options and notifies the buyer.
    """
    def __init__(self, progression_cog, user_id, guild_id, options, parent_view):
        self.progression_cog = progression_cog
        self.user_id = user_id
        self.guild_id = guild_id
        self.parent_view = parent_view
        self.message = None
        super().__init__(placeholder="Select an item to buy...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("⚠️ You can only buy items for yourself.", ephemeral=True)
            return

        if hasattr(self.parent_view, "reset_timer"):
            self.parent_view.reset_timer()

        if getattr(self.parent_view, "processing", False):
            await interaction.response.send_message("A purchase is already being processed. Please wait.", ephemeral=True)
            return

        self.parent_view.processing = True
        self.disabled = True
        msg_to_edit = getattr(self, "message", None) or getattr(self.parent_view, "message", None)

        await interaction.response.defer()
        if msg_to_edit:
            await msg_to_edit.edit(view=self.parent_view)

        try:
            selected_item = self.values[0]

            async with self.progression_cog.pool.acquire() as conn:
                await self.parent_view.parent_cog._set_stmt_timeout(conn)
                row = await conn.fetchrow(TC.SQL_SELECT_PRICE_EMOJI, selected_item)

            if not row:
                await interaction.followup.send("❌ This item no longer exists in the shop.", ephemeral=True)
                return
            price, selected_emoji = row["price"], row["emoji"]

            NOT_ENOUGH_COINS_MSG = "❌ You don't have enough coins, nothing purchased."
            coins = await self.progression_cog.get_coins(self.user_id, self.guild_id)
            if coins < price:
                await interaction.followup.send(NOT_ENOUGH_COINS_MSG, ephemeral=True)
                return

            ok = await self.progression_cog.remove_coins(self.user_id, self.guild_id, price)
            if not ok:
                await interaction.followup.send(NOT_ENOUGH_COINS_MSG, ephemeral=True)
                return

            async with self.progression_cog.pool.acquire() as conn:
                await self.parent_view.parent_cog._set_stmt_timeout(conn)
                async with conn.transaction():
                    await conn.execute(
                        """
                        INSERT INTO user_inventory (user_id, guild_id, item_name, quantity)
                        VALUES ($1, $2, $3, 1)
                        ON CONFLICT(user_id, guild_id, item_name) DO UPDATE SET quantity = user_inventory.quantity + 1
                        """,
                        self.user_id, self.guild_id, selected_item
                    )

            new_balance = await self.progression_cog.get_coins(self.user_id, self.guild_id)
            async with self.progression_cog.pool.acquire() as conn:
                await self.parent_view.parent_cog._set_stmt_timeout(conn)
                items = await conn.fetch("SELECT name, price, emoji FROM shop_items")

            embed = discord.Embed(
                title="🛒 Minori Bargains",
                description=f"Your Coins: **{format_coins(new_balance)}**",
                color=discord.Color.dark_purple(),
            )
            embed.set_thumbnail(url=TC.SHOP_ICON_URL)

            new_options = []
            for r in items:
                name, item_price, item_emoji = r["name"], r["price"], r["emoji"]
                embed.add_field(name=f"{item_emoji} {name}", value=f"{item_price} coins", inline=False)
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
                await interaction.followup.edit_message(interaction.message.id, embed=embed, view=self.parent_view)

            await interaction.followup.send(f"You bought **1x {selected_item}** {selected_emoji}!", ephemeral=True)

        finally:
            self.disabled = False
            self.parent_view.processing = False
            if msg_to_edit:
                await msg_to_edit.edit(view=self.parent_view)


class ShopView(discord.ui.View):
    """
    A shop view that presents available items and handles closure/timeouts.

    Attributes:
        progression_cog: reference to the Progression cog for coins/db access.
        user_id: ID of the user that opened the shop.
        guild_id: guild id.
        options: initial select options for the shop.
        parent_cog: the Trading cog reference for state updates.
        timeout_seconds: how long before the shop auto-closes.
    """
    def __init__(self, progression_cog, user_id, guild_id, options, parent_cog, timeout=180):
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

        self.select = ShopSelect(self.progression_cog, self.user_id, self.guild_id, self.options, self)
        self.add_item(self.select)

        close_button = CloseButton(
            owner_id=self.user_id,
            close_text="❌ Shop closed.",
            label="Close Shop",
            menu_type="shop",
            cog=self.parent_cog,
            guild_id=self.guild_id
        )

        self.add_item(close_button)
        self.start_timeout()

    def start_timeout(self):
        if self._timeout_task:
            self._timeout_task.cancel()
        self._timeout_task = asyncio.create_task(self._timeout_loop())

    async def _timeout_loop(self):
        await asyncio.sleep(self.timeout_seconds)
        if self.message:
            try:
                await self.message.edit(content="❌ Shop closed.", embed=None, view=None)
            except (discord.HTTPException, discord.NotFound, discord.Forbidden):
                pass
            
        if self.parent_cog:
            self.parent_cog.open_shops.get(self.guild_id, {}).pop(self.user_id, None)
                
    def reset_timer(self):
        self.start_timeout()