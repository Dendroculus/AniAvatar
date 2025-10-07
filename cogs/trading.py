from discord.ext import commands
import discord
import os
from cogs.utils.progUtils import *
from cogs.utils.constants import *
import random
from datetime import datetime, timedelta, timezone
import asyncio

COG_PATH = os.path.dirname(os.path.abspath(__file__))
ROOT_PATH = os.path.dirname(COG_PATH)
SHOP_ICON_URL = "https://cdn.discordapp.com/emojis/1415555390489366680.png"


def format_coins(coins: int) -> str:
    if coins < 1_000:
        return str(coins)
    elif coins < 1_000_000:
        return f"{coins / 1_000:.2f}K".rstrip("0").rstrip(".")
    elif coins < 1_000_000_000:
        return f"{coins / 1_000_000:.2f}M".rstrip("0").rstrip(".")
    else:
        return f"{coins / 1_000_000_000:.2f}B".rstrip("0").rstrip(".")
    
class CloseButton(discord.ui.Button):
    def __init__(self, owner_id: int, close_text: str, label: str = "Close", menu_type: str = None, cog=None):
        super().__init__(label=label, style=discord.ButtonStyle.danger)
        self.owner_id = owner_id
        self.close_text = close_text
        self.menu_type = menu_type
        self.cog = cog

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("⚠️ This is not your menu!", ephemeral=True)
            return

        stored = None
        if self.menu_type == "shop":
            stored = self.cog.open_shops.pop(self.owner_id, None)
        elif self.menu_type == "inventory":
            stored = self.cog.open_inventories.pop(self.owner_id, None)

        try:
            if getattr(stored, "_timeout_task", None):
                stored._timeout_task.cancel()
            elif hasattr(stored, "view") and getattr(stored.view, "_timeout_task", None):
                stored.view._timeout_task.cancel()
        except Exception:
            pass

        await interaction.response.edit_message(content=self.close_text, embed=None, view=None)

class InventorySelect(discord.ui.Select):
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
        for child in self.children:
            child.disabled = True
        if hasattr(self, "message") and self.message:
            await self.message.edit(view=self)

    async def callback(self, interaction: discord.Interaction):
        if hasattr(self.parent_view, "reset_timer"):
            self.parent_view.reset_timer()
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("⚠️ This is not your inventory!", ephemeral=True)
            return

        self.cog.user_locks[self.user_id] = True

        try:
            selected_item = self.values[0]
            await interaction.response.defer()
            c = self.cog.progression_cog.c
            
            c.execute("SELECT price, emoji FROM shop_items WHERE name = ?", (selected_item,))
            row = c.fetchone()
            selected_emoji = row[1] if row and row[1] else "📦"

            c.execute(
                "SELECT quantity FROM user_inventory WHERE user_id = ? AND guild_id = ? AND item_name = ?",
                (self.user_id, self.guild_id, selected_item)
            )
            row = c.fetchone()
            if not row or row[0] <= 0:
                await interaction.followup.send("❌ You don't own this item anymore.", ephemeral=True)
                return

            if selected_item in ["Small EXP Potion", "Medium EXP Potion", "Large EXP Potion", "Level Skip Token"]:
                c.execute("SELECT level FROM users WHERE user_id = ? AND guild_id = ?", (self.user_id, self.guild_id))
                row = c.fetchone()
                if row and row[0] >= self.cog.progression_cog.MAX_LEVEL:
                    await interaction.followup.send("<:MinoriWink:1414899695209418762> You’ve already reached the max level! You can’t use <:EXP:1415642038589984839> items anymore.", ephemeral=True)
                    return

            c.execute(
                "UPDATE user_inventory SET quantity = quantity - 1 WHERE user_id = ? AND guild_id = ? AND item_name = ?",
                (self.user_id, self.guild_id, selected_item)
            )
            c.execute(
                "DELETE FROM user_inventory WHERE user_id = ? AND guild_id = ? AND item_name = ? AND quantity <= 0",
                (self.user_id, self.guild_id, selected_item)
            )
            self.cog.progression_cog.conn.commit()

            feedback_msg = f"You used {selected_emoji} **{selected_item}**!"

            if selected_item in ["Small EXP Potion", "Medium EXP Potion", "Large EXP Potion", "Level Skip Token"]:
                gain, extra_msg = await self.cog.apply_potion_effect(
                    self.user_id, self.guild_id, selected_item, interaction.channel
                ) 
                feedback_msg = f"You used {selected_emoji} **{selected_item}** and gained {gain} <:EXP:1415642038589984839>!"
                if extra_msg:
                    feedback_msg += f"\n{extra_msg}" 
                    
            if selected_item == "Mystery Box":
                rewards = await self.cog.apply_mystery_box(self.user_id, self.guild_id)
                if rewards:
                    reward_lines = []
                    for item, qty in rewards:
                        c.execute("SELECT emoji FROM shop_items WHERE name = ?", (item,))
                        emoji = c.fetchone()
                        emoji = emoji[0] if emoji else "📦"
                        reward_lines.append(f"{qty}x {emoji} {item}")
                    feedback_msg = "<:MysteryBox:1415707555325415485> You opened a Mystery Box and got:\n" + "\n".join(reward_lines)

            c.execute("SELECT item_name, quantity FROM user_inventory WHERE user_id = ? AND guild_id = ?",
                    (self.user_id, self.guild_id))
            raw_items = c.fetchall()

            items = []
            for name, qty in raw_items:
                if qty <= 0:
                    continue
                c.execute("SELECT emoji FROM shop_items WHERE name = ?", (name,))
                emoji = c.fetchone()
                emoji = emoji[0] if emoji else "📦"
                items.append((name, qty, emoji))

            if not items:
                await interaction.edit_original_response(embed=None, view=None, content="📭 Your inventory is now empty.")
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
            asyncio.create_task(release_lock())

class InventoryView(discord.ui.View):
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
        close_button = CloseButton(owner_id=user_id, close_text="❌ Inventory closed.", label="Close Inventory", menu_type="inventory", cog=self.cog)
        self.add_item(close_button)

        self.start_timeout()

    def start_timeout(self):
        if self._timeout_task:
            self._timeout_task.cancel()
        self._timeout_task = asyncio.create_task(self._timeout_loop())

    async def _timeout_loop(self):
        try:
            await asyncio.sleep(self.timeout_seconds)
            if self.message:
                try:
                    await self.message.edit(content="❌ Inventory closed.", embed=None, view=None)
                except Exception:
                    pass
            try:
                if self.cog:
                    self.cog.open_inventories.pop(self.user_id, None)
            except Exception:
                pass
        except asyncio.CancelledError:
            return

    def reset_timer(self):
        self.start_timeout()

class ShopSelect(discord.ui.Select):
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
            
        selected_item = self.values[0]

        c = self.progression_cog.c
        c.execute("SELECT price, emoji FROM shop_items WHERE name = ?", (selected_item,))
        row = c.fetchone()
        selected_emoji = row[1] if row and row[1] else "📦"
        if not row:
            await interaction.response.send_message("❌ This item no longer exists in the shop.", ephemeral=True)
            return
        price, emoji = row

        coins = await self.progression_cog.get_coins(self.user_id, self.guild_id)
        if coins < price:
            await interaction.response.send_message("❌ You don't have enough coins.", ephemeral=True)
            return

        await self.progression_cog.remove_coins(self.user_id, self.guild_id, price)
        c.execute("""
            INSERT INTO user_inventory (user_id, guild_id, item_name, quantity)
            VALUES (?, ?, ?, 1)
            ON CONFLICT(user_id, guild_id, item_name) DO UPDATE SET quantity = quantity + 1
        """, (self.user_id, self.guild_id, selected_item))
        self.progression_cog.conn.commit()

        new_balance = await self.progression_cog.get_coins(self.user_id, self.guild_id)
        c.execute("SELECT price, emoji FROM shop_items WHERE name = ?", (selected_item,))
        row = c.fetchone()
        if not row:
            await interaction.response.send_message("❌ This item no longer exists in the shop.", ephemeral=True)
            return

        price, selected_emoji = row  
        
        c.execute("SELECT name, price, emoji FROM shop_items")
        items = c.fetchall()

        embed = discord.Embed(
            title="🛒 Minori Bargains",
            description=f"Your Coins: **{format_coins(new_balance)}**",
            color=discord.Color.dark_purple()
        )
        embed.set_thumbnail(url=SHOP_ICON_URL)
        for name, price, emoji in items:
            embed.add_field(name=f"{emoji} {name}", value=f"{price} coins", inline=False)

        new_options = []
        for name, price, emoji in items:
            new_options.append(discord.SelectOption(
                label=name,
                description=f"Buy {name} for {price} coins",
                emoji=emoji,
                value=name,
            ))
        self.options = new_options

        msg_to_edit = getattr(self, "message", None) or getattr(self.parent_view, "message", None)
        await interaction.response.defer()
        
        if msg_to_edit:
            await msg_to_edit.edit(embed=embed, view=self.parent_view)
        else:
            await interaction.followup.edit_message(interaction.message.id, embed=embed, view=self.parent_view)
            
        await interaction.followup.send(f"You bought **1x {selected_item}** {selected_emoji}!", ephemeral=True)


class ShopView(discord.ui.View):
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

        self.select = ShopSelect(self.progression_cog, self.user_id, self.guild_id, self.options, self)
        self.add_item(self.select)

        close_button = CloseButton(
            owner_id=self.user_id,
            close_text="❌ Shop closed.",
            label="Close Shop",
            menu_type="shop",
            cog=self.parent_cog
        )
        self.add_item(close_button)

        self.start_timeout()

    def start_timeout(self):
        if self._timeout_task:
            self._timeout_task.cancel()
        self._timeout_task = asyncio.create_task(self._timeout_loop())

    async def _timeout_loop(self):
        try:
            await asyncio.sleep(self.timeout_seconds)
            if self.message:
                try:
                    await self.message.edit(content="❌ Shop closed.", embed=None, view=None)
                except Exception:
                    pass
            try:
                if self.parent_cog:
                    self.parent_cog.open_shops.pop(self.user_id, None)
            except Exception:
                pass
        except asyncio.CancelledError:
            return


    def reset_timer(self):
        self.start_timeout()


class Trading(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.progression_cog = None
        self.user_locks = {}
        self.donate_cooldowns = {}
        self.open_inventories = {}
        self.open_shops = {} 


    async def cog_load(self):
        self.progression_cog = self.bot.get_cog("Progression")
        if not self.progression_cog:
            print("[Shop] Progression cog not loaded! Coins won't work properly.")
            return

        c = self.progression_cog.c
        c.execute("""
            CREATE TABLE IF NOT EXISTS shop_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE,
                type TEXT,
                price INTEGER,
                emoji TEXT
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS user_inventory (
                user_id INTEGER,
                guild_id INTEGER,
                item_name TEXT,
                quantity INTEGER,
                PRIMARY KEY(user_id, guild_id, item_name)
            )
        """)
        self.progression_cog.conn.commit()

        default_items = [
            ("Small EXP Potion", "consumable", 125, "<:SmallExpBoostPotion:1415347886186561628>"),
            ("Medium EXP Potion", "consumable", 250, "<:MediumExpBoostPotion:1415347878343217266>"),
            ("Large EXP Potion", "consumable", 500, "<:LargeExpBoostPotion:1415347869493493781>"),
            ("Level Skip Token", "consumable", 1500, "<:LevelSkipToken:1415349457511383161>"),
            ("Mystery Box", "consumable", 3000, "<:MysteryBox:1415707555325415485>"),
        ]
        for name, type_, price, emoji in default_items:
            c.execute(
                "INSERT OR IGNORE INTO shop_items (name, type, price, emoji) VALUES (?, ?, ?, ?)",
                (name, type_, price, emoji)
            )
        self.progression_cog.conn.commit()

    async def apply_potion_effect(self, user_id: int, guild_id: int, item_name: str, channel: discord.TextChannel = None):
        potion_effects = {
            "Small EXP Potion": 0.03,
            "Medium EXP Potion": 0.12,
            "Large EXP Potion": 0.225,
        }

        exp, level = self.progression_cog.get_user(user_id, guild_id)
        if level >= self.progression_cog.MAX_LEVEL:
            return 0, ""

        
        required_exp = 50 * level + 20 * level**2

        if item_name == "Level Skip Token":
            remaining = required_exp - exp
            gain = remaining if remaining > 0 else required_exp
        elif item_name in potion_effects:
            gain = int(required_exp * potion_effects[item_name])
        else:
            return 0, ""

        old_level = level
        new_level, new_exp, leveled_up = self.progression_cog.add_exp(user_id, guild_id, gain)

        extra_msg = ""
        if leveled_up and channel:
            guild = self.progression_cog.bot.get_guild(guild_id)
            if guild:
                member = guild.get_member(user_id)
                if member:
                    old_title = get_title(old_level)
                    new_title = get_title(new_level)
                    old_emoji = get_title_emoji(old_level)
                    new_emoji = get_title_emoji(new_level)

                    if new_title != old_title:
                        embed_title = f"{member.display_name} <:LEVELUP:1413479714428948551> {new_level}    {old_emoji} <:RIGHTWARDARROW:1414227272302334062> {new_emoji}"
                        embed_description = (
                            f"```Congratulations {member.display_name}! You have reached level {new_level} and ascended to {new_title}. ```\n"
                            f"Title: `{new_title}` {new_emoji}"
                        )
                    else:
                        embed_title = f"{member.display_name} <:LEVELUP:1413479714428948551> {new_level}"
                        embed_description = (
                            f"```Congratulations {member.display_name}! You have reached level {new_level}.``` \n"
                            f"Title: `{new_title}` {new_emoji}"
                        )

                    embed = discord.Embed(title=embed_title, description=embed_description, color=discord.Color.dark_purple())
                    embed.set_thumbnail(url=member.display_avatar.url)
                    lvlup_msg = await channel.send(embed=embed)

                    coins_amount = random.randint(30, 50)
                    await self.progression_cog.add_coins(user_id, guild_id, coins_amount)
                    await channel.send(
                        f"{member.display_name} received <:Coins:1415353285270966403> {coins_amount} coins for leveling up!",
                        reference=discord.MessageReference(
                            message_id=lvlup_msg.id,
                            channel_id=lvlup_msg.channel.id,
                            guild_id=lvlup_msg.guild.id
                        )
                    )
                    extra_msg = ""  

        return gain, extra_msg
    
    async def apply_mystery_box(self, user_id: int, guild_id: int):
        c = self.progression_cog.c
        rewards = []

        # Level Skip Token (15%)
        if random.random() < 0.15:
            amount = random.randint(1, 3)
            c.execute("""
                INSERT INTO user_inventory (user_id, guild_id, item_name, quantity)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id, guild_id, item_name) DO UPDATE SET quantity = quantity + ?
            """, (user_id, guild_id, "Level Skip Token", amount, amount))
            rewards.append(("Level Skip Token", amount))

        # Large EXP Potion (20%)
        if random.random() < 0.20:
            amount = random.randint(1, 3)
            c.execute("""
                INSERT INTO user_inventory (user_id, guild_id, item_name, quantity)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id, guild_id, item_name) DO UPDATE SET quantity = quantity + ?
            """, (user_id, guild_id, "Large EXP Potion", amount, amount))
            rewards.append(("Large EXP Potion", amount))

        # Medium EXP Potion (50%)
        if random.random() < 0.50:
            amount = random.randint(1, 3)
            c.execute("""
                INSERT INTO user_inventory (user_id, guild_id, item_name, quantity)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id, guild_id, item_name) DO UPDATE SET quantity = quantity + ?
            """, (user_id, guild_id, "Medium EXP Potion", amount, amount))
            rewards.append(("Medium EXP Potion", amount))

        # Small EXP Potion (always 3)
        c.execute("""
            INSERT INTO user_inventory (user_id, guild_id, item_name, quantity)
            VALUES (?, ?, ?, 3)
            ON CONFLICT(user_id, guild_id, item_name) DO UPDATE SET quantity = quantity + 3
        """, (user_id, guild_id, "Small EXP Potion"))
        rewards.append(("Small EXP Potion", 3))

        self.progression_cog.conn.commit()
        return rewards


    @commands.hybrid_command(name="shop", description="View the shop and buy items!")
    @commands.guild_only()
    async def shop(self, ctx):
        if not self.progression_cog:
            await ctx.send("Progression cog not loaded. Shop unavailable.")
            return

        user_id = ctx.author.id
        guild_id = ctx.guild.id

        if self.open_shops.get(guild_id, {}).get(user_id):
            await ctx.send("⚠️ You already have a shop open! Close it first.", ephemeral=True)
            return

        c = self.progression_cog.c
        c.execute("SELECT name, price, emoji FROM shop_items")
        items = c.fetchall()
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
        for name, price, emoji in items:
            embed.add_field(name=f"{emoji} {name}", value=f"{price} coins", inline=False)

        options = [
            discord.SelectOption(label=name,
                                description=f"Buy {name} for {price} coins",
                                emoji=emoji,
                                value=name)
            for name, price, emoji in items
        ]

        view = ShopView(self.progression_cog, user_id, guild_id, options, parent_cog=self, timeout=180)
        msg = await ctx.send(embed=embed, view=view)

        view.message = msg
        view.select.message = msg  
        self.open_shops.setdefault(guild_id, {})[user_id] = view

        
    @commands.hybrid_command(name="inventory", description="Check your inventory and items")
    @commands.guild_only()
    async def inventory(self, ctx):
        if not self.progression_cog:
            await ctx.send("Progression cog not loaded. Inventory unavailable.")
            return

        user_id = ctx.author.id
        guild_id = ctx.guild.id
        if self.open_inventories.get(guild_id, {}).get(user_id):
            await ctx.send("⚠️ You already have an inventory open! Close it first.", ephemeral=True)
            return
    
        c = self.progression_cog.c
        c.execute("SELECT item_name, quantity FROM user_inventory WHERE user_id = ? AND guild_id = ?", (user_id, guild_id))
        raw_items = c.fetchall()

        items = []
        for name, qty in raw_items:
            if qty <= 0:
                continue
            c.execute("SELECT emoji FROM shop_items WHERE name = ?", (name,))
            emoji = c.fetchone()
            emoji = emoji[0] if emoji else "📦"
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
        if member.bot:
            await ctx.send("<:MinoriConfused:1415707082988060874> You cannot donate to bots.")
            return
        
        donor_id = ctx.author.id
        receiver_id = member.id
        
        if donor_id == receiver_id:
            await ctx.send("<:MinoriConfused:1415707082988060874> You cannot donate to yourself.")
            return
        
        guild_id = ctx.guild.id
        c = self.progression_cog.c

        now = datetime.now(timezone.utc)
        if donor_id in self.donate_cooldowns and now < self.donate_cooldowns[donor_id]:
            remaining = self.donate_cooldowns[donor_id] - now
            await ctx.send(f"<:TIME:1415961777912545341> You can donate again in {str(remaining).split('.')[0]}")
            return

        c.execute("SELECT item_name, quantity FROM user_inventory WHERE user_id = ? AND guild_id = ?", (donor_id, guild_id))
        items = [(name, qty) for name, qty in c.fetchall() if qty > 0]
        if not items:
            await ctx.send("📭 Your inventory is empty, cannot donate.")
            return

        c.execute("SELECT name, emoji FROM shop_items")
        emoji_map = {name: emoji for name, emoji in c.fetchall()}

        
        caps = {
            "Mystery Box": 1,
            "Level Skip Token": 1,
            "Large EXP Potion": 2,
            "Medium EXP Potion": 3,
            "Small EXP Potion": 5
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
                except:
                    await interaction.response.send_message("❌ Invalid number.", ephemeral=True)

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
            c.execute("SELECT quantity FROM user_inventory WHERE user_id = ? AND guild_id = ? AND item_name = ?", (donor_id, guild_id, item_name))
            row = c.fetchone()
            if not row or row[0] < amount:
                await interaction.response.send_message("❌ You don't have enough of this item.", ephemeral=True)
                return

            c.execute("UPDATE user_inventory SET quantity = quantity - ? WHERE user_id = ? AND guild_id = ? AND item_name = ?",
                    (amount, donor_id, guild_id, item_name))
            c.execute("DELETE FROM user_inventory WHERE user_id = ? AND guild_id = ? AND item_name = ? AND quantity <= 0",
                    (donor_id, guild_id, item_name))

            c.execute("""INSERT INTO user_inventory (user_id, guild_id, item_name, quantity)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(user_id, guild_id, item_name) DO UPDATE SET quantity = quantity + ?""",
                    (receiver_id, guild_id, item_name, amount, amount))
            self.progression_cog.conn.commit()

            # 2-hour cooldown to donate
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
    print("📦 Loaded shop cog.")

