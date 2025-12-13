from discord.ext import commands
import discord
import os
import random
from datetime import datetime, timedelta, timezone
import asyncio

from cogs.utils.emojis import CustomEmojis, MinoriEmojis, ShopEmojis

"""
trading.py

Provides shop and inventory functionality for the AniAvatar bot.

Contents:
- Constants for items and SQL statements used by the shop/inventory.
- Utility: format_coins(coins) -> human-friendly coin string.
- UI components:
  - CloseButton: button used to close shop/inventory views.
  - InventorySelect: select menu for using items from inventory.
  - InventoryView: view that contains the inventory select and close button.
  - ShopSelect: select menu for buying items from the shop.
  - ShopView: view that contains the shop select and close button.
- Trading Cog:
  - Initializes DB tables for shop and inventory on load.
  - apply_potion_effect: apply consumable effects that grant exp or skip levels.
  - apply_mystery_box: randomly awards items to a user.
  - Commands:
    - shop: shows shop and allows purchases.
    - inventory: shows inventory and allows usage.
    - donate: allows giving items to another user with cooldown and caps.

Notes:
- This module expects a Progression cog to be present with:
  - pool: asyncpg pool
  - db_lock: an asyncio lock to serialize DB writes.
  - get_user, add_exp, get_coins, remove_coins, announce_level_up, MAX_LEVEL attributes/methods.
- All behavioral code is left unchanged; only the storage layer now uses asyncpg/PostgreSQL.
"""

COG_PATH = os.path.dirname(os.path.abspath(__file__))
ROOT_PATH = os.path.dirname(COG_PATH)
SHOP_ICON_URL = "https://cdn.discordapp.com/emojis/1415555390489366680.png"

MYSTERY_BOX_NAME = "Mystery Box"
SMALL_EXP_POTION = "Small EXP Potion"
MEDIUM_EXP_POTION = "Medium EXP Potion"
LARGE_EXP_POTION = "Large EXP Potion"
LEVEL_SKIP_TOKEN = "Level Skip Token"
EXP_EMOJI = f"{CustomEmojis['EXP']}"

POTION_ITEMS = (SMALL_EXP_POTION, MEDIUM_EXP_POTION, LARGE_EXP_POTION, LEVEL_SKIP_TOKEN)

SQL_USER_INV_SELECT = "SELECT item_name, quantity FROM user_inventory WHERE user_id = $1 AND guild_id = $2"
SQL_UPSERT_USER_INV = """
INSERT INTO user_inventory (user_id, guild_id, item_name, quantity)
VALUES ($1, $2, $3, $4)
ON CONFLICT(user_id, guild_id, item_name) DO UPDATE SET quantity = user_inventory.quantity + EXCLUDED.quantity
"""
SQL_SELECT_PRICE_EMOJI = "SELECT price, emoji FROM shop_items WHERE name = $1"

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
        self._release_lock_task = None  

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

        self.cog.user_locks[self.user_id] = True

        try:
            selected_item = self.values[0]
            await interaction.response.defer()
            pool = self.cog.progression_cog.pool
            lock = self.cog.progression_cog.db_lock

            async with lock, pool.acquire() as conn:
                row = await conn.fetchrow(SQL_SELECT_PRICE_EMOJI, selected_item)
                selected_emoji = row["emoji"] if row and row["emoji"] else "📦"

                row_qty = await conn.fetchrow(
                    "SELECT quantity FROM user_inventory WHERE user_id = $1 AND guild_id = $2 AND item_name = $3",
                    self.user_id, self.guild_id, selected_item
                )
                if not row_qty or row_qty["quantity"] <= 0:
                    await interaction.followup.send("❌ You don't own this item anymore.", ephemeral=True)
                    return

                if selected_item in POTION_ITEMS:
                    row_lvl = await conn.fetchrow(
                        "SELECT level FROM users WHERE user_id = $1 AND guild_id = $2",
                        self.user_id, self.guild_id
                    )
                    if row_lvl and row_lvl["level"] >= self.cog.progression_cog.MAX_LEVEL:
                        await interaction.followup.send(f"{MinoriEmojis['MinoriWink']} You’ve already reached the max level! You can’t use {EXP_EMOJI} items anymore.", ephemeral=True)
                        return

                await conn.execute(
                    "UPDATE user_inventory SET quantity = quantity - 1 WHERE user_id = $1 AND guild_id = $2 AND item_name = $3",
                    self.user_id, self.guild_id, selected_item
                )
                await conn.execute(
                    "DELETE FROM user_inventory WHERE user_id = $1 AND guild_id = $2 AND item_name = $3 AND quantity <= 0",
                    self.user_id, self.guild_id, selected_item
                )

            feedback_msg = f"You used {selected_emoji} **{selected_item}**!"

            if selected_item in POTION_ITEMS:
                gain, extra_msg = await self.cog.apply_potion_effect(
                    self.user_id, self.guild_id, selected_item, interaction.channel
                )
                feedback_msg = f"You used {selected_emoji} **{selected_item}** and gained {gain} {EXP_EMOJI}!"
                if extra_msg:
                    feedback_msg += f"\n{extra_msg}" 
                    
            if selected_item == MYSTERY_BOX_NAME:
                rewards = await self.cog.apply_mystery_box(self.user_id, self.guild_id)
                if rewards:
                    reward_lines = []
                    # fetch emojis mapping
                    async with self.cog.progression_cog.pool.acquire() as conn:
                        emap_rows = await conn.fetch("SELECT name, emoji FROM shop_items")
                        emap = {r["name"]: r["emoji"] for r in emap_rows}
                    for item, qty in rewards:
                        emoji = emap.get(item, "📦")
                        reward_lines.append(f"{qty}x {emoji} {item}")
                    feedback_msg = f"{ShopEmojis['MysteryBox']} You opened a {MYSTERY_BOX_NAME} and got:\n" + "\n".join(reward_lines)

            # reload inventory
            async with self.cog.progression_cog.db_lock, self.cog.progression_cog.pool.acquire() as conn:
                raw_items = await conn.fetch(SQL_USER_INV_SELECT, self.user_id, self.guild_id)

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
            async def release_lock():
                await asyncio.sleep(2)
                self.cog.user_locks[self.user_id] = False
            self._release_lock_task = asyncio.create_task(release_lock())

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
                row = await conn.fetchrow(SQL_SELECT_PRICE_EMOJI, selected_item)

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

            async with self.progression_cog.db_lock, self.progression_cog.pool.acquire() as conn:
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
                items = await conn.fetch("SELECT name, price, emoji FROM shop_items")

            embed = discord.Embed(
                title="🛒 Minori Bargains",
                description=f"Your Coins: **{format_coins(new_balance)}**",
                color=discord.Color.dark_purple(),
            )
            embed.set_thumbnail(url=SHOP_ICON_URL)

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


class Trading(commands.Cog):
    """
    Cog responsible for shop, inventory, and item trading functionality.

    Responsibilities:
    - Ensure DB tables for shop and inventory exist on cog load.
    - Seed default shop items.
    - Provide helper methods to apply item effects.
    - Expose commands: shop, inventory, donate.

    Important attributes created at init:
    - progression_cog: reference to the Progression cog (set during cog_load).
    - user_locks: used to rate-limit or serialize per-user item actions.
    - donate_cooldowns: map donor_id -> datetime when they can next donate.
    - open_inventories / open_shops: map guild_id -> map[user_id -> view/message] to prevent duplicates.
    """
    def __init__(self, bot):
        self.bot = bot
        self.progression_cog = None
        self.user_locks = {}
        self.donate_cooldowns = {}
        self.open_inventories = {}
        self.open_shops = {} 

    async def cog_load(self):
        """
        Called when the cog is loaded. Attaches to the Progression cog, creates DB tables,
        and seeds a set of default shop items. Logs a warning if Progression isn't loaded.
        """
        self.progression_cog = self.bot.get_cog("Progression")
        if not self.progression_cog:
            print("[Shop] Progression cog not loaded! Coins won't work properly.")
            return

        # ensure pool exists
        if self.progression_cog.pool is None:
            await self.progression_cog._ensure_pool()

        async with self.progression_cog.pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS shop_items (
                    id BIGSERIAL PRIMARY KEY,
                    name TEXT UNIQUE,
                    type TEXT,
                    price BIGINT,
                    emoji TEXT
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS user_inventory (
                    user_id BIGINT,
                    guild_id BIGINT,
                    item_name TEXT,
                    quantity BIGINT,
                    PRIMARY KEY(user_id, guild_id, item_name)
                )
            """)

            default_items = [
                (SMALL_EXP_POTION, "consumable", 125, f"{ShopEmojis['SmallExpBoostPotion']}"),
                (MEDIUM_EXP_POTION, "consumable", 250, f"{ShopEmojis['MediumExpBoostPotion']}"),
                (LARGE_EXP_POTION, "consumable", 500, f"{ShopEmojis['LargeExpBoostPotion']}"),
                (LEVEL_SKIP_TOKEN, "consumable", 1500, f"{ShopEmojis['LevelSkipToken']}"),
                (MYSTERY_BOX_NAME, "consumable", 3000, f"{ShopEmojis['MysteryBox']}"),
            ]
            for name, type_, price, emoji in default_items:
                await conn.execute(
                    "INSERT INTO shop_items (name, type, price, emoji) VALUES ($1, $2, $3, $4) ON CONFLICT (name) DO NOTHING",
                    name, type_, price, emoji
                )

    async def apply_potion_effect(self, user_id: int, guild_id: int, item_name: str, channel: discord.TextChannel = None):
        """
        Apply the effect of a potion or level skip token.

        Args:
            user_id: ID of the user using the item.
            guild_id: guild ID.
            item_name: one of the potion constants or LEVEL_SKIP_TOKEN.
            channel: optional channel to announce level-ups.

        Returns:
            (gain, extra_msg) where gain is the amount of EXP granted, and extra_msg is any extra string.
        """
        potion_effects = {
            SMALL_EXP_POTION: 0.03,
            MEDIUM_EXP_POTION: 0.12,
            LARGE_EXP_POTION: 0.225,
        }

        exp, level = await self.progression_cog.get_user(user_id, guild_id)
        if level >= self.progression_cog.MAX_LEVEL:
            return 0, ""

        required_exp = 50 * level + 20 * level**2

        if item_name == LEVEL_SKIP_TOKEN:
            remaining = required_exp - exp
            gain = remaining if remaining > 0 else required_exp
        elif item_name in potion_effects:
            gain = int(required_exp * potion_effects[item_name])
        else:
            return 0, ""

        old_level = level
        new_level, _, leveled_up = await self.progression_cog.add_exp(user_id, guild_id, gain)

        extra_msg = ""
        if leveled_up and channel:
            await self.progression_cog.announce_level_up(guild_id, user_id, new_level, old_level, channel)

        return gain, extra_msg

    async def apply_mystery_box(self, user_id: int, guild_id: int):
        """
        Open a Mystery Box and randomly award items to the user, writing to DB.

        Returns:
            List of (item_name, amount) awarded to the user.
        """
        rewards = []
        async with self.progression_cog.db_lock, self.progression_cog.pool.acquire() as conn:
            if random.random() < 0.15:
                amount = random.randint(1, 3)
                await conn.execute(SQL_UPSERT_USER_INV, user_id, guild_id, LEVEL_SKIP_TOKEN, amount)
                rewards.append((LEVEL_SKIP_TOKEN, amount))

            if random.random() < 0.20:
                amount = random.randint(1, 3)
                await conn.execute(SQL_UPSERT_USER_INV, user_id, guild_id, LARGE_EXP_POTION, amount)
                rewards.append((LARGE_EXP_POTION, amount))

            if random.random() < 0.50:
                amount = random.randint(1, 3)
                await conn.execute(SQL_UPSERT_USER_INV, user_id, guild_id, MEDIUM_EXP_POTION, amount)
                rewards.append((MEDIUM_EXP_POTION, amount))

            await conn.execute(SQL_UPSERT_USER_INV, user_id, guild_id, SMALL_EXP_POTION, 3)
            rewards.append((SMALL_EXP_POTION, 3))

        return rewards

    @commands.hybrid_command(name="shop", description="View the shop and buy items!")
    @commands.guild_only()
    async def shop(self, ctx):
        """
        Shows the list of shop items and opens a ShopView for the invoking user.
        Prevents opening multiple shops per user per guild.
        """
        if not self.progression_cog:
            await ctx.send("Progression cog not loaded. Shop unavailable.")
            return

        user_id = ctx.author.id
        guild_id = ctx.guild.id

        if self.open_shops.get(guild_id, {}).get(user_id):
            await ctx.send("⚠️ You already have a shop open! Close it first.", ephemeral=True)
            return

        async with self.progression_cog.pool.acquire() as conn:
            items = await conn.fetch("SELECT name, price, emoji FROM shop_items")
        if not items:
            await ctx.send("Shop is empty.")
            return

        user_coins = await self.progression_cog.get_coins(user_id, guild_id)
        embed = discord.Embed(
            title="Minori Bargains",
            description=f"Your Coins: **{format_coins(user_coins)}**",
            color=discord.Color.dark_purple()
        )
        embed.set_thumbnail(url=SHOP_ICON_URL)
        for r in items:
            embed.add_field(name=f"{r['emoji']} {r['name']}", value=f"{r['price']} coins", inline=False)

        options = [
            discord.SelectOption(label=r["name"],
                                description=f"Buy {r['name']} for {r['price']} coins",
                                emoji=r["emoji"],
                                value=r["name"])
            for r in items
        ]

        view = ShopView(self.progression_cog, user_id, guild_id, options, parent_cog=self, timeout=180)
        msg = await ctx.send(embed=embed, view=view)

        view.message = msg
        view.select.message = msg
        self.open_shops.setdefault(guild_id, {})[user_id] = view

    @commands.hybrid_command(name="inventory", description="Check your inventory and items")
    @commands.guild_only()
    async def inventory(self, ctx):
        """
        Displays the user's current inventory items and opens an InventoryView.
        Prevents opening multiple inventories per user per guild.
        """
        if not self.progression_cog:
            await ctx.send("Progression cog not loaded. Inventory unavailable.")
            return

        user_id = ctx.author.id
        guild_id = ctx.guild.id
        if self.open_inventories.get(guild_id, {}).get(user_id):
            await ctx.send("⚠️ You already have an inventory open! Close it first.", ephemeral=True)
            return

        async with self.progression_cog.pool.acquire() as conn:
            raw_items = await conn.fetch(SQL_USER_INV_SELECT, user_id, guild_id)

        items = []
        async with self.progression_cog.pool.acquire() as conn:
            for name, qty in raw_items:
                if qty <= 0:
                    continue
                erow = await conn.fetchrow("SELECT emoji FROM shop_items WHERE name = $1", name)
                emoji = erow["emoji"] if erow else "📦"
                items.append((name, qty, emoji))

        if not items:
            await ctx.send("Your inventory is empty.")
            return

        inventory_text = "\n".join(f"{emoji} {name} x{qty}" for name, qty, emoji in items)
        embed = discord.Embed(
            title=f"{ctx.author.display_name}'s Inventory",
            description=inventory_text,
            color=discord.Color.dark_purple()
        )
        embed.set_thumbnail(url=ctx.author.display_avatar.url)

        view = InventoryView(self, user_id, guild_id, items)
        msg = await ctx.send(embed=embed, view=view)
        view.message = msg
        self.open_inventories.setdefault(guild_id, {})[user_id] = msg

    @commands.hybrid_command(name="donate", description="Give an item to another user")
    @commands.guild_only()
    async def donate(self, ctx, member: discord.Member):
        """
         /donate <member>
        Allows the invoking user to give an item from their inventory to another user, subject
        to caps for certain items and a donor cooldown (2 hours).
        """
        if member.bot:
            await ctx.send(f"{MinoriEmojis['MinoriConfused']} You cannot donate to bots.")
            return

        donor_id = ctx.author.id
        receiver_id = member.id

        if donor_id == receiver_id:
            await ctx.send(f"{MinoriEmojis['MinoriConfused']} You cannot donate to yourself.")
            return

        guild_id = ctx.guild.id
        conn_pool = self.progression_cog.pool

        now = datetime.now(timezone.utc)
        if donor_id in self.donate_cooldowns and now < self.donate_cooldowns[donor_id]:
            remaining = self.donate_cooldowns[donor_id] - now
            await ctx.send(f"{CustomEmojis['TIME']} You can donate again in {str(remaining).split('.')[0]}")
            return

        async with conn_pool.acquire() as conn:
            raw_inv = await conn.fetch(SQL_USER_INV_SELECT, donor_id, guild_id)
            items = [(r["item_name"], r["quantity"]) for r in raw_inv if r["quantity"] > 0]
        if not items:
            await ctx.send("🧯 Your inventory is empty, cannot donate.")
            return

        async with conn_pool.acquire() as conn:
            emap_rows = await conn.fetch("SELECT name, emoji FROM shop_items")
            emoji_map = {r["name"]: r["emoji"] for r in emap_rows}

        caps = {
            MYSTERY_BOX_NAME: 1,
            LEVEL_SKIP_TOKEN: 1,
            LARGE_EXP_POTION: 2,
            MEDIUM_EXP_POTION: 3,
            SMALL_EXP_POTION: 5
        }

        options = [
            discord.SelectOption(
                label=name,
                description=f"You have {qty}",
                emoji=emoji_map.get(name, "📦"),
                value=name
            ) for name, qty in items
        ]

        class DonateView(discord.ui.View):
            def __init__(self, author_id, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.author_id = author_id

            async def interaction_check(self, interaction: discord.Interaction) -> bool:
                if interaction.user.id != self.author_id:
                    await interaction.response.send_message(
                        "⚠️ This is not your donate menu!", ephemeral=True
                    )
                    return False
                return True

        class DonateAmountModal(discord.ui.Modal):
            def __init__(self, item_name, max_amount=None):
                super().__init__(title=f"Donate {item_name}")
                self.item_name = item_name
                self.max_amount = max_amount
                self.amount_input = discord.ui.TextInput(
                    label="Amount",
                    placeholder=f"Max {max_amount}" if max_amount else "Enter amount",
                    style=discord.TextStyle.short
                )
                self.add_item(self.amount_input)

            async def on_submit(self, interaction: discord.Interaction):
                try:
                    amt = int(self.amount_input.value)
                except (ValueError, TypeError):
                    await interaction.response.send_message("❌ Invalid number.", ephemeral=True)
                    return

                if amt <= 0:
                    await interaction.response.send_message("❌ Amount must be at least 1.", ephemeral=True)
                    return
                if self.max_amount is not None and amt > self.max_amount:
                    await interaction.response.send_message(
                        f"❌ You can only donate up to {self.max_amount} of this item.", ephemeral=True
                    )
                    view = discord.ui.View()
                    view.add_item(DonateSelect())
                    await interaction.edit_original_response(view=view)
                    return

                await finalize_donate(self.item_name, amt, interaction)

        class DonateSelect(discord.ui.Select):
            def __init__(self):
                super().__init__(placeholder="Select an item to donate", min_values=1, max_values=1, options=options)

            async def callback(self, interaction: discord.Interaction):
                selected_item = self.values[0]
                max_cap = caps.get(selected_item, None)

                if max_cap == 1:
                    await finalize_donate(selected_item, 1, interaction)
                else:
                    await interaction.response.send_modal(DonateAmountModal(selected_item, max_cap))

        async def finalize_donate(item_name, amount, interaction):
            lock = self.progression_cog.db_lock
            async with lock, conn_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT quantity FROM user_inventory WHERE user_id = $1 AND guild_id = $2 AND item_name = $3",
                    donor_id, guild_id, item_name
                )
                if not row or row["quantity"] < amount:
                    await interaction.response.send_message("❌ You don't have enough of this item.", ephemeral=True)
                    return

                await conn.execute(
                    "UPDATE user_inventory SET quantity = quantity - $1 WHERE user_id = $2 AND guild_id = $3 AND item_name = $4",
                    amount, donor_id, guild_id, item_name
                )
                await conn.execute(
                    "DELETE FROM user_inventory WHERE user_id = $1 AND guild_id = $2 AND item_name = $3 AND quantity <= 0",
                    donor_id, guild_id, item_name
                )

                await conn.execute(
                    """
                    INSERT INTO user_inventory (user_id, guild_id, item_name, quantity)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT(user_id, guild_id, item_name) DO UPDATE SET quantity = user_inventory.quantity + EXCLUDED.quantity
                    """,
                    receiver_id, guild_id, item_name, amount
                )

            self.donate_cooldowns[donor_id] = datetime.now(timezone.utc) + timedelta(hours=2)

            for child in view.children:
                child.disabled = True
            await interaction.response.edit_message(
                content=f"You donated {amount}x {emoji_map.get(item_name, '📦')} {item_name} to {member.display_name}!",
                view=view
            )

        view = DonateView(ctx.author.id, timeout=180)
        view.add_item(DonateSelect())
        await ctx.send(f"Select an item to donate to {member.display_name}:", view=view)

async def setup(bot):
    await bot.add_cog(Trading(bot))