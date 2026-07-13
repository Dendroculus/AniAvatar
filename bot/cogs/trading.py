import discord
import asyncio

from typing import Optional
from discord.ext import commands
from datetime import datetime, timedelta, timezone

from bot.config.emojis import CustomEmojis, MinoriEmojis, ShopEmojis
from bot.config.configs import TradingConstants as TC
from bot.utils.trading_ui import format_coins, ShopView, InventoryView
from bot.utils.donate import DonateView, DonateSelect
from bot.services.user_repository import UserRepository
from bot.services.trading_repository import TradingRepository
from bot.features.trading.item_effects import ItemEffectService

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
        self.user_repo: Optional[UserRepository] = None
        self.trading_repo: Optional[TradingRepository] = None
        self.economy_service: Optional[EconomyServiceWrapper] = None
        self.item_effect_service: Optional[ItemEffectService] = None

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
        self.item_effect_service = ItemEffectService(
            bot=self.bot,
            user_repository=self.user_repo,
            trading_repository=self.trading_repo,
        )

        await self.trading_repo.initialize_schema()

        default_items = [
            (
                TC.SMALL_EXP_POTION,
                "consumable",
                125,
                f"{ShopEmojis['SmallExpBoostPotion']}",
            ),
            (
                TC.MEDIUM_EXP_POTION,
                "consumable",
                250,
                f"{ShopEmojis['MediumExpBoostPotion']}",
            ),
            (
                TC.LARGE_EXP_POTION,
                "consumable",
                500,
                f"{ShopEmojis['LargeExpBoostPotion']}",
            ),
            (
                TC.LEVEL_SKIP_TOKEN,
                "consumable",
                1500,
                f"{ShopEmojis['LevelSkipToken']}",
            ),
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

    async def apply_potion_effect(
        self,
        user_id: int,
        guild_id: int,
        item_name: str,
        channel: discord.TextChannel = None,
    ) -> tuple[int, str]:
        """Delegate consumable EXP effects."""
        if self.item_effect_service is None:
            return 0, "System unavailable."

        return await self.item_effect_service.apply_potion_effect(
            user_id,
            guild_id,
            item_name,
            channel,
        )

    async def apply_mystery_box(
        self,
        user_id: int,
        guild_id: int,
    ) -> list[tuple[str, int]]:
        """Delegate mystery-box reward generation."""
        if self.item_effect_service is None:
            return []

        return await self.item_effect_service.apply_mystery_box(
            user_id,
            guild_id,
        )

    async def refresh_open_inventory(
        self,
        user_id: int,
        guild_id: int,
        user,
    ) -> None:
        """Refresh an existing inventory view from database state."""

        inventory_views = self.open_inventories.get(
            guild_id,
            {},
        )

        current_view = inventory_views.get(user_id)

        if current_view is None:
            return

        message = getattr(
            current_view,
            "message",
            None,
        )

        if message is None:
            inventory_views.pop(
                user_id,
                None,
            )
            return

        items = await self.trading_repo.get_user_inventory(
            user_id,
            guild_id,
        )

        old_timeout = getattr(
            current_view,
            "_timeout_task",
            None,
        )

        if old_timeout:
            old_timeout.cancel()

        if not items:
            await message.edit(
                content="?? Your inventory is now empty.",
                embed=None,
                view=None,
            )

            inventory_views.pop(
                user_id,
                None,
            )
            return

        inventory_text = "\n".join(
            f"{emoji} {name} x{qty}" for name, qty, emoji in items
        )

        embed = discord.Embed(
            title=(f"{user.display_name}'s Inventory"),
            description=inventory_text,
            color=discord.Color.dark_purple(),
        )

        embed.set_thumbnail(url=user.display_avatar.url)

        new_view = InventoryView(
            self,
            user_id,
            guild_id,
            items,
        )

        new_view.message = message

        try:
            await message.edit(
                content=None,
                embed=embed,
                view=new_view,
            )
        except Exception:
            timeout_task = getattr(
                new_view,
                "_timeout_task",
                None,
            )

            if timeout_task:
                timeout_task.cancel()

            if hasattr(
                current_view,
                "start_timeout",
            ):
                current_view.start_timeout()

            raise

        inventory_views[user_id] = new_view

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
            await ctx.send(
                "⚠️ You already have a shop open! Close it first.", ephemeral=True
            )
            return

        items = await self.trading_repo.get_shop_items()
        if not items:
            await ctx.send("Shop is empty.")
            return

        user_coins = await self.user_repo.get_coins(user_id, guild_id)
        embed = discord.Embed(
            title="Minori Bargains",
            description=f"Your Coins: **{format_coins(user_coins)}**",
            color=discord.Color.dark_purple(),
        )
        embed.set_thumbnail(url=TC.SHOP_ICON_URL)
        for r in items:
            embed.add_field(
                name=f"{r['emoji']} {r['name']}",
                value=f"{r['price']} coins",
                inline=False,
            )

        options = [
            discord.SelectOption(
                label=r["name"],
                description=f"Buy {r['name']} for {r['price']} coins",
                emoji=r["emoji"],
                value=r["name"],
            )
            for r in items
        ]

        view = ShopView(
            self.economy_service,
            user_id,
            guild_id,
            options,
            parent_cog=self,
            timeout=180,
        )
        msg = await ctx.send(embed=embed, view=view)

        view.message = msg
        view.select.message = msg
        self.open_shops.setdefault(guild_id, {})[user_id] = view

    @commands.hybrid_command(
        name="inventory", description="Check your inventory and items"
    )
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
            await ctx.send(
                "⚠️ You already have an inventory open! Close it first.", ephemeral=True
            )
            return

        items = await self.trading_repo.get_user_inventory(user_id, guild_id)

        if not items:
            await ctx.send("Your inventory is empty.")
            return

        inventory_text = "\n".join(
            f"{emoji} {name} x{qty}" for name, qty, emoji in items
        )
        embed = discord.Embed(
            title=f"{ctx.author.display_name}'s Inventory",
            description=inventory_text,
            color=discord.Color.dark_purple(),
        )
        embed.set_thumbnail(url=ctx.author.display_avatar.url)

        view = InventoryView(self, user_id, guild_id, items)
        msg = await ctx.send(embed=embed, view=view)
        view.message = msg
        self.open_inventories.setdefault(guild_id, {})[user_id] = view

    async def _execute_donation(
        self,
        interaction,
        view,
        item_name,
        amount,
        donor_id,
        receiver_id,
        guild_id,
        items,
    ):
        """
        Executes the donation DB transaction.
        Args:
            interaction: The interaction object.
            view: The DonateView instance.
            item_name: The name of the item being donated.
            amount: The amount of the item being donated.
            donor_id: The ID of the donor.
            receiver_id: The ID of the receiver.
            guild_id: The ID of the guild.
            items: The list of items in the donor's inventory.

        Returns:
            None
        """
        async with self.bot.pool.acquire() as conn:
            try:
                await conn.execute(
                    f"SET LOCAL statement_timeout = {TC.STMT_TIMEOUT_MS}"
                )
            except Exception:
                pass

            async with conn.transaction():
                row = await conn.fetchrow(
                    "SELECT quantity FROM user_inventory WHERE user_id = $1 AND guild_id = $2 AND item_name = $3 FOR UPDATE",
                    donor_id,
                    guild_id,
                    item_name,
                )

                if not row or row["quantity"] < amount:
                    error_text = "❌ You don't have enough of this item."
                    if interaction.response.is_done():
                        if view.message:
                            await view.message.edit(content=error_text, view=view)
                    else:
                        await interaction.response.edit_message(
                            content=error_text, view=view
                        )
                    return

                await conn.execute(
                    "UPDATE user_inventory SET quantity = quantity - $1 WHERE user_id = $2 AND guild_id = $3 AND item_name = $4",
                    amount,
                    donor_id,
                    guild_id,
                    item_name,
                )
                await conn.execute(
                    "DELETE FROM user_inventory WHERE user_id = $1 AND guild_id = $2 AND item_name = $3 AND quantity <= 0",
                    donor_id,
                    guild_id,
                    item_name,
                )
                await conn.execute(
                    """
                    INSERT INTO user_inventory (user_id, guild_id, item_name, quantity)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT(user_id, guild_id, item_name) DO UPDATE SET quantity = user_inventory.quantity + EXCLUDED.quantity
                    """,
                    receiver_id,
                    guild_id,
                    item_name,
                    amount,
                )

        self.donate_cooldowns[donor_id] = datetime.now(timezone.utc) + timedelta(
            hours=2
        )
        for child in view.children:
            child.disabled = True

        emoji = next((em for nm, _, em in items if nm == item_name), "📦")
        member = interaction.guild.get_member(receiver_id)
        name = member.display_name if member else "User"

        success_msg = f"You donated {amount}x {emoji} {item_name} to {name}!"

        try:
            if not interaction.response.is_done():
                await interaction.response.edit_message(content=success_msg, view=view)
            elif view.message:
                await view.message.edit(content=success_msg, view=view)
        except Exception:
            pass

    @commands.hybrid_command(name="donate", description="Give an item to another user")
    @commands.guild_only()
    async def donate(self, ctx: commands.Context, member: discord.Member):
        """
        Donate an item from the user's inventory to another member.
        """
        if member.bot or ctx.author.id == member.id:
            return await ctx.send(f"{MinoriEmojis['MinoriConfused']} Invalid target.")

        donor_id, guild_id = ctx.author.id, ctx.guild.id

        now = datetime.now(timezone.utc)
        if donor_id in self.donate_cooldowns and now < self.donate_cooldowns[donor_id]:
            remaining = self.donate_cooldowns[donor_id] - now
            return await ctx.send(
                f"{CustomEmojis['TIME']} You can donate again in {str(remaining).split('.')[0]}"
            )

        items = await self.trading_repo.get_user_inventory(donor_id, guild_id)
        if not items:
            return await ctx.send("🧯 Your inventory is empty, cannot donate.")

        caps = {
            TC.MYSTERY_BOX_NAME: 1,
            TC.LEVEL_SKIP_TOKEN: 1,
            TC.LARGE_EXP_POTION: 2,
            TC.MEDIUM_EXP_POTION: 3,
            TC.SMALL_EXP_POTION: 5,
        }

        options = [
            discord.SelectOption(
                label=name, description=f"You have {qty}", emoji=emoji, value=name
            )
            for name, qty, emoji in items
        ]

        view = DonateView(
            ctx.author.id, self, donor_id, member.id, guild_id, items, timeout=180
        )
        view.add_item(DonateSelect(options, caps))

        view.message = await ctx.send(
            f"Select an item to donate to {member.display_name}:", view=view
        )

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
