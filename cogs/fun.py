import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import random
import json
import os
import time
from itertools import cycle
from typing import Dict, Optional, Any, List
from utils.pollings import PollInputModal
from constants.emojis import MinoriEmojis, ShopEmojis
from constants.configs import FunConstants as FC, ExternalAPIs as EC
from utils.gamble_helpers import GambleView


"""
fun.py

Purpose:
- Lightweight collection of user-facing entertainment commands and interactive views
  (gambling UI, quote lookup, waifu image fetch, and poll-creation helper).
- Encapsulates UI/state for a per-user "gamble" view that interacts with the Progression
  cog for coin balance/reservation. The view is stateful and must be attached to the
  message that presented it so users can continue interacting with it.

Design and operational notes (important):
- Concurrency: GambleView instances are tied to a guild_id,user_id pair and tracked in
  self.active_views to ensure only one view per user exists.
- Quote Management: Quote loading and balancing logic is encapsulated in QuoteManager.
  File I/O is performed asynchronously in cog_load to avoid blocking the event loop.
- Safety: The gambling flow reserves coins before attempting to settle a wager. On
  downstream errors the code attempts to refund or partially refund bets where possible.
- UX: The cog favors ephemeral responses for errors and uses interaction response/followup
  semantics to integrate both prefix and slash commands.
- Network: API calls (waifu) use self.bot.session to prevent socket exhaustion.
"""

class QuoteManager:
    """
    Manages loading and retrieving anime quotes with balancing logic.
    """
    def __init__(self, bot):
        self.bot = bot
        self.data_path = os.path.join(os.path.dirname(__file__), "..", "data", "quotes.json")
        self.quotes_dict: Dict[str, List[Dict[str, str]]] = {"Mixed": []}
        self.used_quotes = set()
        self.lock = asyncio.Lock()

    async def load_quotes(self):
        """
        Load quotes from JSON file asynchronously to avoid blocking the event loop.
        """
        def _read_json():
            try:
                with open(self.data_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except FileNotFoundError:
                return {}

        data = await self.bot.loop.run_in_executor(None, _read_json)

        if isinstance(data, dict):
            self.quotes_dict = data
        elif isinstance(data, list):
            self.quotes_dict = {"Mixed": data}
        else:
            self.quotes_dict = {"Mixed": []}

    async def get_balanced_quotes(self, num_quotes: int) -> List[Dict[str, Any]]:
        """
        Select a balanced set of random quotes, avoiding immediate repetition.
        Thread-safe.
        
        Args:
            num_quotes (int): Number of quotes to retrieve.

        Returns:
            list: A list of quote dictionaries containing 'anime', 'character', and 'quote'.
        """
        async with self.lock:
            titles = list(self.quotes_dict.keys())
            if not titles:
                return []

            random.shuffle(titles)
            quotes = []
            title_cycle = cycle(titles)

            while len(quotes) < num_quotes:
                title = next(title_cycle)
                cat_list = self.quotes_dict.get(title, [])
                available = [q for q in cat_list if q.get("quote") and q["quote"] not in self.used_quotes]
                if available:
                    q = random.choice(available)
                    self.used_quotes.add(q["quote"])
                    quotes.append({"anime": title, **q})

                total_quotes = sum(len(qs) for qs in self.quotes_dict.values())
                if total_quotes and len(self.used_quotes) >= total_quotes:
                    self.used_quotes.clear()

            return quotes

class Fun(commands.Cog):
    """
    Fun cog providing entertainment commands.

    Responsibilities:
    - Manage interactive gambling sessions (GambleView lifecycle).
    - Handle thread-safe anime quote retrieval via QuoteManager.
    - Perform API-based image fetching using the shared bot session.
    - Provide poll creation utilities.
    """
    def __init__(self, bot):
        self.bot = bot
        # Maps (guild_id, user_id) -> GambleView instance
        self.active_views: Dict[int, Dict[int, "GambleView"]] = {}
        
        # Internal tracking for gambling session limits
        self._gamble_counts: Dict[tuple, int] = {}
        self._gamble_cooldowns: Dict[tuple, float] = {}

        # Quote Manager instance
        self.quote_manager = QuoteManager(bot)

    async def cog_load(self):
        """
        Async initialization to load quotes without blocking.
        """
        await self.quote_manager.load_quotes()

    async def _send(
        self,
        ctx: commands.Context,
        interaction: Optional[discord.Interaction],
        content: Optional[str] = None,
        *,
        ephemeral: bool = False,
        **kwargs: Any,
    ) -> Optional[discord.Message]:
        """
        Unified send helper for Context and Interaction flows.

        Handles the complexity of responding to an interaction that might 
        already be deferred or responded to, falling back to standard context 
        sending if necessary.

        Args:
            ctx (commands.Context): The command context.
            interaction (Optional[discord.Interaction]): The interaction object, if available.
            content (Optional[str]): The message content to send.
            ephemeral (bool): Whether the response should be ephemeral (interaction only).
            **kwargs: Additional arguments for the send method (embeds, views, etc).

        Returns:
            Optional[discord.Message]: The sent message object, if retrievable.
        """
        if interaction:
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(content, ephemeral=ephemeral, **kwargs)
                    try:
                        return await interaction.original_response()
                    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                        return None
                return await interaction.followup.send(content, ephemeral=ephemeral, **kwargs)
            except (discord.HTTPException, discord.Forbidden, discord.NotFound):
                kwargs.pop("ephemeral", None)
                return await ctx.send(content, **kwargs)
        kwargs.pop("ephemeral", None)
        return await ctx.send(content, **kwargs)

    def _cooldown_remaining(self, guild_id: int, user_id: int) -> int:
        """
        Calculate remaining cooldown seconds for a user's gamble session.
        
        This tracks the specific 'session cooldown' triggered after max attempts,
        separate from the standard command rate limit.
        """
        key = (guild_id, user_id)
        now = time.time()
        expires = self._gamble_cooldowns.get(key)
        if expires and expires > now:
            return int(expires - now)
        return 0

    def _start_session_cooldown(self, guild_id: int, user_id: int) -> None:
        """Start the gamble session cooldown and reset the attempt counter."""
        key = (guild_id, user_id)
        self._gamble_cooldowns[key] = time.time() + FC.GAMBLE_COOLDOWN_SECONDS
        self._gamble_counts.pop(key, None)

    def _count_attempt(self, guild_id: int, user_id: int) -> int:
        """Increment and return the gamble attempt count for the current session."""
        key = (guild_id, user_id)
        new_val = self._gamble_counts.get(key, 0) + 1
        self._gamble_counts[key] = new_val
        return new_val

    def _clear_attempts(self, guild_id: int, user_id: int) -> None:
        """Clear the gamble attempt counter for a user."""
        self._gamble_counts.pop((guild_id, user_id), None)

    def _set_active_view(self, guild_id: int, user_id: int, view: Optional[GambleView]) -> None:
        """
        Register or remove the active GambleView for a user.
        
        Ensures we can locate the specific view instance later to update
        buttons or balances.
        """
        self.active_views.setdefault(guild_id, {})
        if view is None:
            self.active_views[guild_id].pop(user_id, None)
        else:
            self.active_views[guild_id][user_id] = view

    def _get_active_view(self, guild_id: int, user_id: int) -> Optional[GambleView]:
        """Retrieve the active GambleView for a user, if one exists."""
        return self.active_views.get(guild_id, {}).get(user_id)

    @commands.hybrid_command(name="waifu", description="Get a random waifu image")
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def waifu(self, ctx):
        """
        Fetch and display a random waifu image from external API.

        Uses the shared self.bot.session to execute the HTTP request efficiently.
        """
        async with self.bot.session.get(EC.WAIFU_API) as resp:
            if resp.status != 200:
                return await ctx.send("❌ Couldn't fetch a waifu image. Try again.")
            data = await resp.json()

        image_url = data.get("url")
        if not image_url:
            return await ctx.send("❌ No image found!")

        embed = discord.Embed(title="Here's a random waifu for you!")
        embed.set_image(url=image_url)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="poll", description="Create a poll with custom options")
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

    async def _send_insufficient_funds(
        self,
        ctx: commands.Context,
        interaction: discord.Interaction,
        progression_cog,
        guild_id: int,
        user_id: int,
        amount: int,
    ) -> None:
        """
        Notify user of insufficient funds and refresh the gambling UI 
        to show their actual balance.
        """
        await self._send(
            ctx,
            interaction,
            f"❌ Could not place bet of {amount} {ShopEmojis['Coins']}. You don't have enough coins.",
            ephemeral=True,
        )
        try:
            new_balance_inner = await progression_cog.get_coins(user_id, guild_id)
            vo_inner = self._get_active_view(guild_id, user_id)
            if vo_inner and vo_inner.message:
                await vo_inner.message.edit(
                    content=(
                        f"You have {new_balance_inner} {ShopEmojis['Coins']}. "
                        "Select amount to gamble:"
                    ),
                    view=vo_inner,
                )
        except (discord.HTTPException, discord.Forbidden, discord.NotFound):
            pass

    async def _settle_win(
        self,
        ctx: commands.Context,
        interaction: discord.Interaction,
        progression_cog,
        guild_id: int,
        user_id: int,
        amount: int,
        pre_balance_val: int,
    ) -> Optional[str]:
        """
        Credit winnings to the user's database balance.

        Returns:
            str: Success message if settlement worked.
            None: If an error occurred (attempts refund).
        """
        try:
            await progression_cog.add_coins(user_id, guild_id, amount * 2)
            if amount == pre_balance_val:
                return (
                    f"{MinoriEmojis['MinoriAmazed']} WOOOAA JACKPOT! "
                    "You just doubled everything you own!"
                )
            return (
                f"{MinoriEmojis['MinoriAmazed']} You won {amount} "
                f"{ShopEmojis['Coins']}!"
            )
        except Exception:
            try:
                await progression_cog.add_coins(user_id, guild_id, amount)
            except Exception:
                pass
            await self._send(
                ctx,
                interaction,
                (
                    "❌ An error occurred while settling your win. "
                    "We've attempted to refund your bet; contact an admin."
                ),
                ephemeral=True,
            )
            return None

    async def _refresh_gamble_prompt(
        self,
        progression_cog,
        guild_id: int,
        user_id: int,
    ) -> None:
        """
        Refetch user balance and update the active gamble message prompt.
        """
        try:
            vo_inner = self._get_active_view(guild_id, user_id)
            if not vo_inner or not vo_inner.message:
                return
            updated = await progression_cog.get_coins(user_id, guild_id)
            await vo_inner.message.edit(
                content=(
                    f"You have {updated} {ShopEmojis['Coins']}. "
                    "Select amount to gamble:"
                ),
                view=vo_inner,
            )
        except (discord.HTTPException, discord.Forbidden, discord.NotFound):
            pass

    async def _handle_gamble_cooldown_and_disable_view(
        self,
        ctx: commands.Context,
        interaction: discord.Interaction,
        guild_id: int,
        user_id: int,
    ) -> None:
        """
        Triggered when max attempts are reached. Applies internal session 
        cooldown and disables UI buttons.
        """
        self._start_session_cooldown(guild_id, user_id)
        await self._send(
            ctx,
            interaction,
            (
                f"{MinoriEmojis['MinoriConfused']} Woah woah you have been "
                "gambling for a while — I think it's time to stop for a while. "
                "You're on cooldown for 5 minutes."
            ),
            ephemeral=True,
        )
        vo = self._get_active_view(guild_id, user_id)
        if vo:
            try:
                await vo._disable_controls()
            except (discord.HTTPException, discord.Forbidden, discord.NotFound):
                pass
            self._set_active_view(guild_id, user_id, None)

    async def _enable_gamble_view_controls_if_any(
        self,
        guild_id: int,
        user_id: int,
    ) -> None:
        """Ensure controls are enabled (if they were previously disabled)."""
        vo = self._get_active_view(guild_id, user_id)
        if not vo:
            return
        try:
            await vo._enable_controls()
        except (discord.HTTPException, discord.Forbidden, discord.NotFound):
            pass

    async def _run_single_gamble(
        self,
        ctx: commands.Context,
        interaction: discord.Interaction,
        *,
        guild_id: int,
        user_id: int,
        progression_cog,
        amount: int,
    ) -> None:
        """
        Execute a single gambling round.

        Flow:
        1. Reserve coins (deduct from DB).
        2. Calculate win probability based on bet ratio.
        3. Determine win/loss.
        4. Settle transaction (Add coins if won).
        5. Update UI.
        """
        if amount <= 0:
            await self._send(ctx, interaction, "❌ Invalid bet amount.", ephemeral=True)
            return

        view_obj = self._get_active_view(guild_id, user_id)
        if view_obj:
            view_obj.reset_timeout()

        pre_balance = await progression_cog.get_coins(user_id, guild_id)
        reserved = await progression_cog.reserve_coins(user_id, guild_id, amount)
        if not reserved:
            await self._send_insufficient_funds(
                ctx, interaction, progression_cog, guild_id, user_id, amount
            )
            return

        bet_ratio = (amount / pre_balance) if pre_balance else 1
        win_chance = max(0.201, FC.DEFAULT_WIN_PROBABILITY - bet_ratio * 0.5) 
        won = random.random() < win_chance

        if won:
            result_text = await self._settle_win(
                ctx,
                interaction,
                progression_cog,
                guild_id,
                user_id,
                amount,
                pre_balance,
            )
            if result_text is None:
                return
        else:
            result_text = (
                f"{MinoriEmojis['MinoriDissapointed']} You lost {amount} "
                f"{ShopEmojis['Coins']}."
            )

        new_balance = await progression_cog.get_coins(user_id, guild_id)
        await self._send(
            ctx,
            interaction,
            (
                f"{result_text} Your new balance: {new_balance:,} "
                f"{ShopEmojis['Coins']}."
            ),
        )
        await self._refresh_gamble_prompt(progression_cog, guild_id, user_id)

    async def _process_gamble(
        self,
        ctx: commands.Context,
        interaction: discord.Interaction,
        *,
        guild_id: int,
        user_id: int,
        progression_cog,
        amount: int,
    ) -> None:
        """
        Orchestrate the gambling process, including cooldown management.
        
        Called by the GambleView when a bet button is clicked.
        """
        await self._run_single_gamble(
            ctx,
            interaction,
            guild_id=guild_id,
            user_id=user_id,
            progression_cog=progression_cog,
            amount=amount,
        )

        count = self._count_attempt(guild_id, user_id)
        if count >= FC.GAMBLE_MAX_ATTEMPTS:
            await self._handle_gamble_cooldown_and_disable_view(
                ctx, interaction, guild_id, user_id
            )
            return

        await self._enable_gamble_view_controls_if_any(guild_id, user_id)

    async def _send_gamble_cooldown_message(
        self,
        ctx: commands.Context,
        interaction: Optional[discord.Interaction],
        remaining: int,
    ) -> None:
        """Notify user that they are on gambling cooldown."""
        mins, secs = divmod(remaining, 60)
        await self._send(
            ctx,
            interaction,
            f"{MinoriEmojis['MinoriConfused']} Woah woah you have been gambling for a while, "
            f"please wait for `{mins}m {secs}s` before gambling again.",
            ephemeral=True,
        )

    async def _ensure_progression_cog(
        self,
        ctx: commands.Context,
        interaction: Optional[discord.Interaction],
    ):
        """Check availability of Progression cog."""
        progression_cog = self.bot.get_cog("Progression")
        if not progression_cog:
            await self._send(
                ctx,
                interaction,
                "❌ Progression cog not loaded. Coins unavailable.",
                ephemeral=True,
            )
            return None
        return progression_cog

    async def _ensure_user_has_coins(
        self,
        ctx: commands.Context,
        interaction: Optional[discord.Interaction],
        progression_cog,
        user_id: int,
        guild_id: int,
    ) -> Optional[int]:
        """Check if user has a positive coin balance."""
        user_coins = await progression_cog.get_coins(user_id, guild_id)
        if user_coins <= 0:
            await self._send(
                ctx,
                interaction,
                "❌ You don't have any coins to gamble!",
                ephemeral=True,
            )
            return None
        return user_coins

    async def _send_gamble_prompt(
        self,
        ctx: commands.Context,
        interaction: Optional[discord.Interaction],
        view: "GambleView",
        user_coins: int,
    ) -> Optional[discord.Message]:
        """Send the initial gambling UI prompt."""
        prompt = f"You have {user_coins} {ShopEmojis['Coins']}. Select amount to gamble:"

        if interaction:
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(prompt, view=view)
                    try:
                        return await interaction.original_response()
                    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                        return None
                return await interaction.followup.send(prompt, view=view)
            except (discord.HTTPException, discord.Forbidden, discord.NotFound):
                return await ctx.send(prompt, view=view)

        return await ctx.send(prompt, view=view)

    async def _attach_view_message_from_context(
        self,
        ctx: commands.Context,
        view: "GambleView",
        sent_message: Optional[discord.Message],
    ) -> None:
        """
        Associate the GambleView with the sent message.
        
        This allows the view to edit the message later (e.g. to update balances
        or disable buttons).
        """
        if isinstance(sent_message, discord.Message):
            view.message = sent_message
            return

        try:
            if ctx.channel:
                last = None
                async for m in ctx.channel.history(limit=1):
                    last = m
                if last:
                    view.message = last
        except (discord.HTTPException, discord.Forbidden):
            view.message = None


    @commands.hybrid_command(name="gamble", description="Gamble your coins!")
    @commands.guild_only()
    @commands.dynamic_cooldown(
        lambda i: commands.CooldownMapping.from_cooldown(1, 15, commands.BucketType.user)
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

        sent_message = await self._send_gamble_prompt(ctx, interaction, view, user_coins)
        await self._attach_view_message_from_context(ctx, view, sent_message)

    @commands.hybrid_command(name="animequotes", description="Give a random anime quote")
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

        embed = discord.Embed(title=f"{anime}", description=f"*“{quote_text}”*", color=discord.Color.blue())
        embed.set_footer(text=f"~ {character}")
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Fun(bot))