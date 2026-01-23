from discord.ext import commands
import discord
import random
from datetime import datetime, timedelta, timezone
import asyncio

from constants.emojis import CustomEmojis, MinoriEmojis, ShopEmojis
from constants.configs import TradingConstants as TC, ProgressionConstants as PC
from utils.trading_ui import format_coins, ShopView, InventoryView
from utils.progression.profile_cards import get_title, get_title_emoji

from services.user_repository import UserRepository
from services.trading_repository import TradingRepository

"""
trading.py

Provides shop and inventory functionality for the AniAvatar bot.
Responsible for item purchasing, inventory management, and user-to-user item trading.
"""

class EconomyServiceWrapper:
    """
    Adapter class to expose UserRepository methods while mimicking the 
    structure expected by legacy UI components.
    """
    def __init__(self, user_repo: UserRepository, bot: commands.Bot):
        """
        Initialize the wrapper.

        Args:
            user_repo (UserRepository): The repository for user data access.
            bot (commands.Bot): The bot instance.
        """
        self.user_repo = user_repo
        self.bot = bot 

    async def get_coins(self, user_id: int, guild_id: int) -> int:
        """
        Retrieve the coin balance for a user.

        Args:
            user_id (int): The ID of the user.
            guild_id (int): The ID of the guild.

        Returns:
            int: The user's coin balance.
        """
        return await self.user_repo.get_coins(user_id, guild_id)

    async def remove_coins(self, user_id: int, guild_id: int, amount: int) -> bool:
        """
        Deduct coins from a user's balance.

        Args:
            user_id (int): The ID of the user.
            guild_id (int): The ID of the guild.
            amount (int): The amount of coins to remove.

        Returns:
            bool: True if the operation was successful, False otherwise.
        """
        return await self.user_repo.remove_coins(user_id, guild_id, amount)


class Trading(commands.Cog):
    """
    Cog responsible for shop, inventory, and item trading functionality.
    """

    def __init__(self, bot: commands.Bot):
        """
        Initialize the Trading Cog.

        Args:
            bot (commands.Bot): The bot instance.
        """
        self.bot = bot
        self.user_repo: UserRepository = None
        self.trading_repo: TradingRepository = None
        self.economy_service: EconomyServiceWrapper = None
        
        self.donate_cooldowns = {}
        self.open_inventories = {}
        self.open_shops = {} 
        self._maintenance_task = None

    async def _start_maintenance_loop(self):
        """
        Start the background maintenance loop for cleaning up invalid items.
        """
        async def _loop():
            await self.bot.wait_until_ready()
            while not self.bot.is_closed():
                try:
                    if self.trading_repo:
                        await self.trading_repo.cleanup_zero_quantity_items()
                except Exception as e:
                    print(f"[Shop] maintenance loop error: {e}")
                await asyncio.sleep(TC.MAINTENANCE_INTERVAL)
        self._maintenance_task = asyncio.create_task(_loop())

    async def cog_load(self):
        """
        Initialize repositories, database schema, and seed default items.
        """
        if not self.bot.pool:
            raise RuntimeError("Bot database pool is not initialized.")

        self.user_repo = UserRepository(self.bot.pool)
        self.trading_repo = TradingRepository(self.bot.pool)
        
        self.economy_service = EconomyServiceWrapper(self.user_repo, self.bot)

        await self.trading_repo.initialize_schema()

        default_items = [
            (TC.SMALL_EXP_POTION, "consumable", 125, f"{ShopEmojis['SmallExpBoostPotion']}"),
            (TC.MEDIUM_EXP_POTION, "consumable", 250, f"{ShopEmojis['MediumExpBoostPotion']}"),
            (TC.LARGE_EXP_POTION, "consumable", 500, f"{ShopEmojis['LargeExpBoostPotion']}"),
            (TC.LEVEL_SKIP_TOKEN, "consumable", 1500, f"{ShopEmojis['LevelSkipToken']}"),
            (TC.MYSTERY_BOX_NAME, "consumable", 3000, f"{ShopEmojis['MysteryBox']}"),
        ]
        await self.trading_repo.seed_default_items(default_items)

        await self._start_maintenance_loop()

    async def cog_unload(self):
        """
        Cleanup tasks when the cog is unloaded.
        """
        if self._maintenance_task:
            self._maintenance_task.cancel()

    async def _send_level_up_announcement(self, guild_id: int, user_id: int, new_level: int, old_level: int, channel: discord.TextChannel):
        """
        Send a level-up announcement to the specified channel.

        Args:
            guild_id (int): The ID of the guild.
            user_id (int): The ID of the user.
            new_level (int): The user's new level.
            old_level (int): The user's previous level.
            channel (discord.TextChannel): The channel to send the announcement to.
        """
        guild = self.bot.get_guild(guild_id)
        if not guild:
             return
        member = guild.get_member(user_id)
        if not member:
             return

        old_title = get_title(old_level)
        new_title = get_title(new_level)
        old_emoji = get_title_emoji(old_level)
        new_emoji = get_title_emoji(new_level)

        if new_title != old_title:
            embed_title = f"{member.display_name} {CustomEmojis['UPWARDARROW']} {new_level}    {old_emoji} {CustomEmojis['RIGHTWARDARROW']} {new_emoji}"
            embed_description = (
                f"```Congratulations {member.display_name}! You have reached level {new_level} and ascended to {new_title}. ```\n"
                f"Title: `{new_title}` {new_emoji}"
            )
        else:
            embed_title = f"{member.display_name} {CustomEmojis['UPWARDARROW']} {new_level}"
            embed_description = (
                f"```Congratulations {member.display_name}! You have reached level {new_level}.```\n"
                f"Title: `{new_title}` {new_emoji}"
            )
        
        embed = discord.Embed(
            title=embed_title,
            description=embed_description,
            color=discord.Color.green()
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            pass

    async def apply_potion_effect(self, user_id: int, guild_id: int, item_name: str, channel: discord.TextChannel = None) -> tuple[int, str]:
        """
        Apply the effect of a potion or level skip token to a user.

        Args:
            user_id (int): The ID of the user.
            guild_id (int): The ID of the guild.
            item_name (str): The name of the item being used.
            channel (discord.TextChannel, optional): The channel for level-up announcements.

        Returns:
            tuple[int, str]: A tuple containing the amount of EXP gained and an optional extra message.
        """
        if not self.user_repo:
            return 0, "System unavailable."

        potion_effects = {
            TC.SMALL_EXP_POTION: 0.03,
            TC.MEDIUM_EXP_POTION: 0.12,
            TC.LARGE_EXP_POTION: 0.225,
        }

        exp, level = await self.user_repo.get_user(user_id, guild_id)
        if level >= PC.MAX_LEVEL:
            return 0, ""

        required_exp = 50 * level + 20 * level**2

        if item_name == TC.LEVEL_SKIP_TOKEN:
            remaining = required_exp - exp
            gain = remaining if remaining > 0 else required_exp
        elif item_name in potion_effects:
            gain = int(required_exp * potion_effects[item_name])
        else:
            return 0, ""

        old_level = level
        new_level, _, leveled_up = await self.user_repo.add_exp(user_id, guild_id, gain)

        extra_msg = ""
        if leveled_up and channel:
            await self._send_level_up_announcement(guild_id, user_id, new_level, old_level, channel)

        return gain, extra_msg

    async def apply_mystery_box(self, user_id: int, guild_id: int) -> list[tuple[str, int]]:
        """
        Open a Mystery Box and randomly award items to the user.

        Args:
            user_id (int): The ID of the user.
            guild_id (int): The ID of the guild.

        Returns:
            list[tuple[str, int]]: A list of tuples containing item names and quantities awarded.
        """
        rewards = []
        if random.random() < 0.15:
            amt = random.randint(1, 3)
            rewards.append((TC.LEVEL_SKIP_TOKEN, amt))
        if random.random() < 0.20:
            amt = random.randint(1, 3)
            rewards.append((TC.LARGE_EXP_POTION, amt))
        if random.random() < 0.50:
            amt = random.randint(1, 3)
            rewards.append((TC.MEDIUM_EXP_POTION, amt))
        
        rewards.append((TC.SMALL_EXP_POTION, 3))

        for item, qty in rewards:
            await self.trading_repo.add_item(user_id, guild_id, item, qty)
            
        return rewards

    @commands.hybrid_command(name="shop", description="View the shop and buy items!")
    @commands.guild_only()
    async def shop(self, ctx: commands.Context):
        """
        Display the shop interface and allow users to purchase items.

        Args:
            ctx (commands.Context): The command context.
        """
        if not self.user_repo:
            await ctx.send("Services unavailable.")
            return

        user_id = ctx.author.id
        guild_id = ctx.guild.id

        if self.open_shops.get(guild_id, {}).get(user_id):
            await ctx.send("⚠️ You already have a shop open! Close it first.", ephemeral=True)
            return

        items = await self.trading_repo.get_shop_items()
        if not items:
            await ctx.send("Shop is empty.")
            return

        user_coins = await self.user_repo.get_coins(user_id, guild_id)
        embed = discord.Embed(
            title="Minori Bargains",
            description=f"Your Coins: **{format_coins(user_coins)}**",
            color=discord.Color.dark_purple()
        )
        embed.set_thumbnail(url=TC.SHOP_ICON_URL)
        for r in items:
            embed.add_field(name=f"{r['emoji']} {r['name']}", value=f"{r['price']} coins", inline=False)

        options = [
            discord.SelectOption(label=r["name"],
                                description=f"Buy {r['name']} for {r['price']} coins",
                                emoji=r["emoji"],
                                value=r["name"])
            for r in items
        ]

        view = ShopView(self.economy_service, user_id, guild_id, options, parent_cog=self, timeout=180)
        msg = await ctx.send(embed=embed, view=view)

        view.message = msg
        view.select.message = msg
        self.open_shops.setdefault(guild_id, {})[user_id] = view

    @commands.hybrid_command(name="inventory", description="Check your inventory and items")
    @commands.guild_only()
    async def inventory(self, ctx: commands.Context):
        """
        Display the user's inventory and items.

        Args:
            ctx (commands.Context): The command context.
        """
        if not self.user_repo:
            await ctx.send("Services unavailable.")
            return

        user_id = ctx.author.id
        guild_id = ctx.guild.id
        if self.open_inventories.get(guild_id, {}).get(user_id):
            await ctx.send("⚠️ You already have an inventory open! Close it first.", ephemeral=True)
            return

        items = await self.trading_repo.get_user_inventory(user_id, guild_id)

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
    async def donate(self, ctx: commands.Context, member: discord.Member):
        """
        Donate an item from the user's inventory to another member.

        Args:
            ctx (commands.Context): The command context.
            member (discord.Member): The member to donate the item to.
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
        
        now = datetime.now(timezone.utc)
        if donor_id in self.donate_cooldowns and now < self.donate_cooldowns[donor_id]:
            remaining = self.donate_cooldowns[donor_id] - now
            await ctx.send(f"{CustomEmojis['TIME']} You can donate again in {str(remaining).split('.')[0]}")
            return

        items = await self.trading_repo.get_user_inventory(donor_id, guild_id)
        if not items:
            await ctx.send("🧯 Your inventory is empty, cannot donate.")
            return

        caps = {
            TC.MYSTERY_BOX_NAME: 1,
            TC.LEVEL_SKIP_TOKEN: 1,
            TC.LARGE_EXP_POTION: 2,
            TC.MEDIUM_EXP_POTION: 3,
            TC.SMALL_EXP_POTION: 5
        }

        options = [
            discord.SelectOption(
                label=name,
                description=f"You have {qty}",
                emoji=emoji,
                value=name
            ) for name, qty, emoji in items
        ]

        class DonateView(discord.ui.View):
            """View for handling donation interaction."""
            def __init__(self, author_id, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.author_id = author_id

            async def interaction_check(self, interaction: discord.Interaction) -> bool:
                """Ensure only the command author can interact."""
                if interaction.user.id != self.author_id:
                    await interaction.response.send_message(
                        "⚠️ This is not your donate menu!", ephemeral=True
                    )
                    return False
                return True

        class DonateAmountModal(discord.ui.Modal):
            """Modal for entering donation amount."""
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
                """Handle modal submission."""
                try:
                    amt = int(self.amount_input.value)
                except (ValueError, TypeError):
                    await interaction.response.edit_message(content="❌ Invalid number.", view=view)
                    return

                if amt <= 0:
                    await interaction.response.edit_message(content="❌ Amount must be at least 1.", view=view)
                    return
                if self.max_amount is not None and amt > self.max_amount:
                    await interaction.response.edit_message(
                        content=f"❌ You can only donate up to {self.max_amount} of this item.", 
                        view=view
                    )
                    return

                await finalize_donate(self.item_name, amt, interaction)

        class DonateSelect(discord.ui.Select):
            """Dropdown menu for selecting donation item."""
            def __init__(self):
                super().__init__(placeholder="Select an item to donate", min_values=1, max_values=1, options=options)

            async def callback(self, interaction: discord.Interaction):
                """Handle item selection."""
                selected_item = self.values[0]
                max_cap = caps.get(selected_item, None)

                if max_cap == 1:
                    await finalize_donate(selected_item, 1, interaction)
                else:
                    await interaction.response.send_modal(DonateAmountModal(selected_item, max_cap))

        message: discord.Message = None

        async def finalize_donate(item_name: str, amount: int, interaction: discord.Interaction):
            """
            Execute the donation transaction and update the UI.

            Args:
                item_name (str): The name of the item to donate.
                amount (int): The quantity to donate.
                interaction (discord.Interaction): The interaction context.
            """
            async with self.bot.pool.acquire() as conn:
                try:
                    await conn.execute(f"SET LOCAL statement_timeout = {TC.STMT_TIMEOUT_MS}")
                except Exception:
                    pass
                    
                async with conn.transaction():
                    row = await conn.fetchrow(
                        "SELECT quantity FROM user_inventory WHERE user_id = $1 AND guild_id = $2 AND item_name = $3 FOR UPDATE",
                        donor_id, guild_id, item_name
                    )
                    
                    if not row or row["quantity"] < amount:
                        error_text = "❌ You don't have enough of this item."
                        try:
                            await interaction.response.edit_message(content=error_text, view=view)
                        except discord.errors.InteractionResponded:
                            if message:
                                await message.edit(content=error_text, view=view)
                            else:
                                await interaction.followup.send(error_text, ephemeral=True)
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
            
            emoji = next((em for nm, _, em in items if nm == item_name), '📦')
            
            try:
                await interaction.response.edit_message(
                    content=f"You donated {amount}x {emoji} {item_name} to {member.display_name}!",
                    view=view
                )
            except Exception:
                if not interaction.response.is_done():
                    await interaction.response.defer()
                if message:
                    await message.edit(
                        content=f"You donated {amount}x {emoji} {item_name} to {member.display_name}!",
                        view=view
                    )

        view = DonateView(ctx.author.id, timeout=180)
        view.add_item(DonateSelect())
        message = await ctx.send(f"Select an item to donate to {member.display_name}:", view=view)

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: discord.Guild):
        """
        Clean up inventory data when the bot leaves a guild.

        Args:
            guild (discord.Guild): The guild the bot has left.
        """
        if self.trading_repo:
            await self.trading_repo.cleanup_guild_inventory(guild.id)
        print(f"[Shop] Cleaned up inventory DB for guild {guild.id} ({guild.name})")


async def setup(bot):
    await bot.add_cog(Trading(bot))