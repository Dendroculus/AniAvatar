"""Discord command handlers for entertainment features."""

from __future__ import annotations

from typing import Dict, Optional

import discord
from discord import app_commands
from discord.ext import commands

from bot.config.configs import (
    ExternalAPIs as EC,
)
from bot.config.emojis import MinoriEmojis
from bot.features.fun.gambling import GamblingMixin
from bot.features.fun.quotes import QuoteManager
from bot.features.fun.responses import ResponseMixin
from bot.features.fun.waifu import (
    WaifuAPIError,
    WaifuClient,
    WaifuImageMissing,
)
from bot.features.polling.modals import PollInputModal
from bot.utils.gamble_helpers import GambleView


class Fun(
    ResponseMixin,
    GamblingMixin,
    commands.Cog,
):
    """Entertainment commands with feature logic delegated to services."""

    def __init__(self, bot):
        self.bot = bot
        # Maps (guild_id, user_id) -> GambleView instance
        self.active_views: Dict[int, Dict[int, "GambleView"]] = {}

        # Internal tracking for gambling session limits
        self._gamble_counts: Dict[tuple, int] = {}
        self._gamble_cooldowns: Dict[tuple, float] = {}

        # Quote Manager instance
        self.quote_manager = QuoteManager(bot)
        self.waifu_client = WaifuClient(
            bot,
            EC.WAIFU_API,
        )

    async def cog_load(self):
        """
        Async initialization to load quotes without blocking.
        """
        await self.quote_manager.load_quotes()

    @commands.hybrid_command(
        name="poll", description="Create a poll with custom options"
    )
    @commands.guild_only()
    @app_commands.describe(duration="How long should the poll last in minutes?")
    async def poll(self, ctx: commands.Context, duration: int):
        """
        Open a modal to create a new poll.

        Args:
            duration (int): Duration of the poll in minutes (Max 1 week).
        """
        if not getattr(ctx, "interaction", None):
            return await ctx.send(
                f"{MinoriEmojis['MinoriConfused']} Please use the slash (/) version of this command so the bot can open modals."
            )

        if duration < 1:
            return await ctx.interaction.response.send_message(
                f"{MinoriEmojis['MinoriDisapointed']} Duration must be at least 1 minute.",
                ephemeral=True,
            )
        if duration > 7 * 24 * 60:
            return await ctx.interaction.response.send_message(
                f"{MinoriEmojis['MinoriDisapointed']} Duration cannot exceed 7 days.",
                ephemeral=True,
            )

        timeout_seconds = duration * 60
        poll_modal = PollInputModal(ctx, timeout_seconds=timeout_seconds)
        await ctx.interaction.response.send_modal(poll_modal)

    @commands.hybrid_command(name="gamble", description="Gamble your coins!")
    @commands.guild_only()
    @commands.dynamic_cooldown(
        lambda i: commands.CooldownMapping.from_cooldown(
            1, 15, commands.BucketType.user
        )
        .get_bucket(i)
        .update_rate_limit(),
        type=commands.BucketType.user,
    )
    async def gamble(self, ctx: commands.Context):
        """
        Start a new interactive gambling session.

        Checks session cooldowns, active views, and coin balances before
        launching the GambleView UI.
        """
        user_id = ctx.author.id
        guild_id = ctx.guild.id
        interaction: Optional[discord.Interaction] = getattr(ctx, "interaction", None)

        remaining = self._cooldown_remaining(guild_id, user_id)
        if remaining > 0:
            ctx.command.reset_cooldown(ctx)
            await self._send_gamble_cooldown_message(ctx, interaction, remaining)
            return

        if self._get_active_view(guild_id, user_id) is not None:
            await self._send(
                ctx,
                interaction,
                "⚠️ You already have the gamble view open!",
                ephemeral=True,
            )
            return

        progression_cog = await self._ensure_progression_cog(ctx, interaction)
        if not progression_cog:
            return

        user_coins = await self._ensure_user_has_coins(
            ctx, interaction, progression_cog, user_id, guild_id
        )
        if user_coins is None:
            return

        view = GambleView(
            fun=self,
            ctx=ctx,
            user_id=user_id,
            guild_id=guild_id,
            progression_cog=progression_cog,
            initial_coins=user_coins,
        )
        self._set_active_view(guild_id, user_id, view)

        sent_message = await self._send_gamble_prompt(
            ctx, interaction, view, user_coins
        )
        await self._attach_view_message_from_context(ctx, view, sent_message)

    @commands.hybrid_command(
        name="animequotes", description="Give a random anime quote"
    )
    async def animequotes(self, ctx: commands.Context):
        """
        Display a random anime quote from the local database.

        Uses a lock to ensure the 'balanced' quote selection logic
        (avoiding repeats) remains thread-safe.
        """
        # Delegated to thread-safe manager
        results = await self.quote_manager.get_balanced_quotes(1)
        if not results:
            return await ctx.send("❌ No quotes available.")
        q = results[0]

        quote_text = q.get("quote", "")[:1900]
        character = q.get("character", "Unknown")
        anime = q.get("anime", "Unknown")

        embed = discord.Embed(
            title=f"{anime}",
            description=f"*“{quote_text}”*",
            color=discord.Color.blue(),
        )
        embed.set_footer(text=f"~ {character}")
        await ctx.send(embed=embed)

    @commands.hybrid_command(
        name="waifu",
        description="Get a random waifu image",
    )
    @commands.cooldown(
        1,
        5,
        commands.BucketType.user,
    )
    async def waifu(
        self,
        ctx: commands.Context,
    ) -> None:
        """Fetch and display a random waifu image."""

        try:
            image_url = await self.waifu_client.fetch_image_url()
        except WaifuAPIError:
            await ctx.send("? Couldn't fetch a waifu image. Try again.")
            return
        except WaifuImageMissing:
            await ctx.send("? No image found!")
            return

        embed = discord.Embed(title="Here's a random waifu for you!")
        embed.set_image(url=image_url)

        await ctx.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    """Register the entertainment cog."""

    await bot.add_cog(Fun(bot))
