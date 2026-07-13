import discord
import asyncio

from typing import Optional
from discord.ext import commands

from bot.config.emojis import CustomEmojis, MinoriEmojis, ShopEmojis
from bot.config.configs import TradingConstants as TC
from bot.utils.trading_ui import format_coins, ShopView, InventoryView
from bot.utils.donate import DonateView, DonateSelect
from bot.services.user_repository import UserRepository
from bot.services.trading_repository import TradingRepository
from bot.features.trading.item_effects import ItemEffectService
from bot.features.trading.inventory_workflow import InventoryWorkflow
from bot.features.trading.shop_workflow import ShopPurchaseWorkflow
from bot.features.trading.donation_service import DonationService
from bot.features.trading.view_registry import TradingViewRegistry

"""
trading.py

Provides shop and inventory functionality for the AniAvatar bot.
Responsible for item purchasing, inventory management, and user-to-user item trading.
"""


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

        self.item_effect_service: Optional[ItemEffectService] = None
        self.inventory_workflow: Optional[InventoryWorkflow] = None
        self.shop_workflow: Optional[ShopPurchaseWorkflow] = None
        self.donation_service: Optional[DonationService] = None

        self.view_registry = TradingViewRegistry()
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

        self.item_effect_service = ItemEffectService(
            bot=self.bot,
            user_repository=self.user_repo,
            trading_repository=self.trading_repo,
        )
        self.inventory_workflow = InventoryWorkflow(
            user_repository=self.user_repo,
            trading_repository=self.trading_repo,
            item_effect_service=self.item_effect_service,
        )
        self.shop_workflow = ShopPurchaseWorkflow(
            user_repository=self.user_repo,
            trading_repository=self.trading_repo,
        )
        self.donation_service = DonationService(
            pool=self.bot.pool,
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

        current_view = self.view_registry.get_inventory(
            guild_id,
            user_id,
        )

        if current_view is None:
            return

        message = getattr(
            current_view,
            "message",
            None,
        )

        if message is None:
            self.view_registry.remove_inventory(guild_id, user_id)
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
                content="🧯 Your inventory is now empty.",
                embed=None,
                view=None,
            )

            self.view_registry.remove_inventory(guild_id, user_id)
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
            self.inventory_workflow,
            user_id,
            guild_id,
            items,
            registry=self.view_registry,
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

        self.view_registry.register_inventory(
            guild_id,
            user_id,
            new_view,
        )

    @commands.hybrid_command(name="shop", description="View the shop and buy items!")
    @commands.guild_only()
    async def shop(self, ctx: commands.Context):
        """
        Display the shop interface and allow users to purchase items.

        Args:
            ctx (commands.Context): The command context.
        """

        if self.shop_workflow is None:
            await ctx.send("Services unavailable.")
            return

        user_id = ctx.author.id
        guild_id = ctx.guild.id

        if (
            self.view_registry.get_shop(
                guild_id,
                user_id,
            )
            is not None
        ):
            await ctx.send(
                "⚠️ You already have a shop open! Close it first.",
                ephemeral=True,
            )
            return

        state = await self.shop_workflow.load_shop(
            user_id=user_id,
            guild_id=guild_id,
        )
        items = state.items

        if not items:
            await ctx.send("Shop is empty.")
            return

        embed = discord.Embed(
            title="Minori Bargains",
            description=(f"Your Coins: **{format_coins(state.balance)}**"),
            color=discord.Color.dark_purple(),
        )
        embed.set_thumbnail(url=TC.SHOP_ICON_URL)

        for item in items:
            embed.add_field(
                name=f"{item.emoji} {item.name}",
                value=f"{item.price} coins",
                inline=False,
            )

        options = [
            discord.SelectOption(
                label=item.name,
                description=(f"Buy {item.name} for {item.price} coins"),
                emoji=item.emoji,
                value=item.name,
            )
            for item in items
        ]

        view = ShopView(
            self.shop_workflow,
            user_id,
            guild_id,
            options,
            refresh_inventory=self.refresh_open_inventory,
            registry=self.view_registry,
            timeout=180,
        )
        msg = await ctx.send(
            embed=embed,
            view=view,
        )

        view.message = msg
        view.select.message = msg
        self.view_registry.register_shop(
            guild_id,
            user_id,
            view,
        )

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
        if self.view_registry.get_inventory(guild_id, user_id) is not None:
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

        view = InventoryView(
            self.inventory_workflow,
            user_id,
            guild_id,
            items,
            registry=self.view_registry,
        )
        msg = await ctx.send(embed=embed, view=view)
        view.message = msg
        self.view_registry.register_inventory(guild_id, user_id, view)

    @commands.hybrid_command(
        name="donate",
        description="Give an item to another user",
    )
    @commands.guild_only()
    async def donate(
        self,
        ctx: commands.Context,
        member: discord.Member,
    ):
        """Donate an inventory item to another member."""
        if self.trading_repo is None or self.donation_service is None:
            await ctx.send("Services unavailable.")
            return

        if member.bot:
            await ctx.send(
                f"{MinoriEmojis['MinoriConfused']} You cannot donate to a bot."
            )
            return

        if ctx.author.id == member.id:
            await ctx.send(
                f"{MinoriEmojis['MinoriConfused']} You cannot donate to yourself."
            )
            return

        donor_id = ctx.author.id
        guild_id = ctx.guild.id

        remaining = self.donation_service.remaining_cooldown(donor_id)

        if remaining is not None:
            await ctx.send(
                f"{CustomEmojis['TIME']} "
                "You can donate again in "
                f"{str(remaining).split('.')[0]}"
            )
            return

        items = await self.trading_repo.get_user_inventory(
            donor_id,
            guild_id,
        )

        if not items:
            await ctx.send("🧯 Your inventory is empty, cannot donate.")
            return

        caps = {
            TC.MYSTERY_BOX_NAME: 1,
            TC.LEVEL_SKIP_TOKEN: 1,
            TC.LARGE_EXP_POTION: 2,
            TC.MEDIUM_EXP_POTION: 3,
            TC.SMALL_EXP_POTION: 5,
        }

        options = [
            discord.SelectOption(
                label=name,
                description=f"You have {quantity}",
                emoji=emoji,
                value=name,
            )
            for name, quantity, emoji in items
        ]

        view = DonateView(
            author_id=ctx.author.id,
            donation_service=(self.donation_service),
            donor_id=donor_id,
            receiver_id=member.id,
            guild_id=guild_id,
            items=items,
            timeout=180,
        )

        view.add_item(
            DonateSelect(
                options,
                caps,
            )
        )

        view.message = await ctx.send(
            (f"Select an item to donate to {member.display_name}:"),
            view=view,
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
