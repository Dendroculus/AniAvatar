from discord.ext import commands
import discord
import os
from .progression import get_title, get_title_emoji
import random
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

        if not any(opt.value == "__exit__" for opt in options):
            options.append(discord.SelectOption(
                label="Close Inventory",
                emoji="❌",
                value="__exit__"
            ))

        super().__init__(placeholder="Choose an item to use...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("⚠️ This is not your inventory!", ephemeral=True)
            return

        if not hasattr(self.cog, "user_locks"):
            self.cog.user_locks = {}

        if self.cog.user_locks.get(self.user_id, False):
            await interaction.response.send_message("⚠️ Please wait before using another item.", ephemeral=True)
            return

        self.cog.user_locks[self.user_id] = True

        try:
            selected_item = self.values[0]

            if selected_item == "__exit__": 
                self.parent_view.clear_items()
                await interaction.response.edit_message(content="❌ Inventory closed.", embed=None, view=None)
                return

            await interaction.response.defer()

            c = self.cog.progression_cog.c
            c.execute(
                "SELECT quantity FROM user_inventory WHERE user_id = ? AND guild_id = ? AND item_name = ?",
                (self.user_id, self.guild_id, selected_item)
            )
            row = c.fetchone()
            if not row or row[0] <= 0:
                await interaction.followup.send("❌ You don't own this item anymore.", ephemeral=True)
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

            feedback_msg = f"You used `{selected_item}`!"

            if selected_item in ["Small EXP Potion", "Medium EXP Potion", "Large EXP Potion", "Level Skip Token"]:
                gain, extra_msg = await self.cog.apply_potion_effect(
                    self.user_id, self.guild_id, selected_item, interaction.channel
                )
                feedback_msg = f"You used `{selected_item}` and gained {gain} <:EXP:1415642038589984839>!"
                if extra_msg:
                    feedback_msg += f"\n{extra_msg}"

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

            # Rebuild embed
            inventory_text = "\n".join(f"{emoji} {name} x{qty}" for name, qty, emoji in items)
            embed = discord.Embed(
                title=f"{interaction.user.display_name}'s Inventory",
                description=inventory_text,
                color=discord.Color.dark_purple()
            )
            embed.set_thumbnail(url=interaction.user.display_avatar.url)

            new_view = InventoryView(self.cog, self.user_id, self.guild_id, items)
            await interaction.edit_original_response(embed=embed, view=new_view)
            await interaction.followup.send(feedback_msg, ephemeral=True)

        finally:
            # ==============================
            #   cooldown release
            # ==============================
            async def release_lock():
                await asyncio.sleep(2)  # 2 sec cooldown
                self.cog.user_locks[self.user_id] = False
            asyncio.create_task(release_lock())



class InventoryView(discord.ui.View):
    def __init__(self, cog, user_id, guild_id, items):
        super().__init__(timeout=180)
        self.add_item(InventorySelect(cog, user_id, guild_id, items, self))


class ShopSelect(discord.ui.Select):
    def __init__(self, progression_cog, user_id, guild_id, options, parent_view):
        self.progression_cog = progression_cog
        self.user_id = user_id
        self.guild_id = guild_id
        self.parent_view = parent_view

        if not any(opt.value == "__exit__" for opt in options):
            options.append(discord.SelectOption(
                label="Close Shop",
                emoji="❌",
                value="__exit__"
            ))

        super().__init__(placeholder="Select an item to buy...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("⚠️ You can only buy items for yourself.", ephemeral=True)
            return

        selected_item = self.values[0]
        if selected_item == "__exit__":
            self.parent_view.clear_items()
            await interaction.response.edit_message(content="❌ Shop closed.", embed=None, view=None)
            return

        c = self.progression_cog.c
        c.execute("SELECT price, emoji FROM shop_items WHERE name = ?", (selected_item,))
        row = c.fetchone()
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

        embed = discord.Embed(
            title="🛒 Minori Bargains",
            description=f"Your Coins: **{format_coins(new_balance)}**",
            color=discord.Color.dark_purple()
        )
        embed.set_thumbnail(url=SHOP_ICON_URL)

        c.execute("SELECT name, price, emoji FROM shop_items")
        items = c.fetchall()
        for name, price, emoji in items:
            embed.add_field(name=f"{emoji} {name}", value=f"{price} coins", inline=False)

        options = [
            discord.SelectOption(
                label=name,
                description=f"Buy {name} for {price} coins",
                emoji=emoji,
                value=name
            ) for name, price, emoji in items
        ]
        if not any(opt.value == "__exit__" for opt in options):
            options.append(discord.SelectOption(label="Close Shop", emoji="❌", value="__exit__"))

        new_view = discord.ui.View(timeout=120)
        new_view.add_item(ShopSelect(self.progression_cog, self.user_id, self.guild_id, options, new_view))

        await interaction.response.edit_message(embed=embed, view=new_view)

        c.execute("SELECT emoji FROM shop_items WHERE name = ?", (selected_item,))
        row = c.fetchone()
        item_emoji = row[0] if row else "📦"

        await interaction.followup.send(
            f"You bought **1x {selected_item}** {item_emoji}!",
            ephemeral=True
        )


class Shop(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.progression_cog = None

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
            ("Small EXP Potion", "consumable", 50, "<:SmallExpBoostPotion:1415347886186561628>"),
            ("Medium EXP Potion", "consumable", 100, "<:MediumExpBoostPotion:1415347878343217266>"),
            ("Large EXP Potion", "consumable", 200, "<:LargeExpBoostPotion:1415347869493493781>"),
            ("Level Skip Token", "consumable", 500, "<:LevelSkipToken:1415349457511383161>")
        ]
        for name, type_, price, emoji in default_items:
            c.execute(
                "INSERT OR IGNORE INTO shop_items (name, type, price, emoji) VALUES (?, ?, ?, ?)",
                (name, type_, price, emoji)
            )
        self.progression_cog.conn.commit()

    async def apply_potion_effect(self, user_id: int, guild_id: int, item_name: str, channel: discord.TextChannel = None):
        potion_effects = {
            "Small EXP Potion": 0.05,
            "Medium EXP Potion": 0.12,
            "Large EXP Potion": 0.25,
        }

        exp, level = self.progression_cog.get_user(user_id, guild_id)
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




    @commands.hybrid_command(name="shop", description="View the shop and buy items!")
    @commands.guild_only()
    async def shop(self, ctx):
        if not self.progression_cog:
            await ctx.send("Progression cog not loaded. Shop unavailable.")
            return

        user_id = ctx.author.id
        guild_id = ctx.guild.id
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
            discord.SelectOption(
                label=name,
                description=f"Buy {name} for {price} coins",
                emoji=emoji,
                value=name
            ) for name, price, emoji in items
        ]
        if not any(opt.value == "__exit__" for opt in options):
            options.append(discord.SelectOption(label="Close Shop", emoji="❌", value="__exit__"))

        view = discord.ui.View(timeout=120)
        view.add_item(ShopSelect(self.progression_cog, user_id, guild_id, options, view))
        await ctx.send(embed=embed, view=view)

    @commands.hybrid_command(name="inventory", description="Check your inventory and items")
    @commands.guild_only()
    async def inventory(self, ctx):
        if not self.progression_cog:
            await ctx.send("Progression cog not loaded. Inventory unavailable.")
            return

        user_id = ctx.author.id
        guild_id = ctx.guild.id
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
            await ctx.send("📭 Your inventory is empty.")
            return

        inventory_text = "\n".join(f"{emoji} {name} x{qty}" for name, qty, emoji in items)
        embed = discord.Embed(
            title=f"{ctx.author.display_name}'s Inventory",
            description=inventory_text,
            color=discord.Color.dark_purple()
        )
        embed.set_thumbnail(url=ctx.author.display_avatar.url)

        view = InventoryView(self, user_id, guild_id, items)
        await ctx.send(embed=embed, view=view)


async def setup(bot):
    await bot.add_cog(Shop(bot))
    print("📦 Loaded shop cog.")
