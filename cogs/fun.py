import discord
from discord import app_commands
from discord.ext import commands
import aiohttp
import asyncio
import random
import json
import os
import time
from itertools import cycle
from typing import Dict, Optional, Any
from utils.pollUtils import PollInputModal
from utils.emojis import MinoriEmojis, ShopEmojis

FALSE_GAMBLE_SESSION = "⚠️ This is not your gamble session."


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
  self.active_views to ensure only one view per user exists. Access to quote selection
  and other small shared state is protected by an asyncio.Lock where appropriate.
- Safety: The gambling flow reserves coins before attempting to settle a wager. On
  downstream errors the code attempts to refund or partially refund bets where possible.
- UX: The cog favors ephemeral responses for errors and uses interaction response/followup
  semantics to integrate both prefix and slash invocations.
- Extensibility: The gambling logic is intentionally split into small helper methods
  (_run_single_gamble, _process_gamble, etc.) so operators can change win odds, cooldowns,
  or maximum attempts without touching UI code.
- Persistence: This module relies on an external Progression cog for coin storage and
  atomic reserve/add operations; ensure that cog provides the methods used here.
"""

class Fun(commands.Cog):
    """
    Fun cog providing entertainment commands.

    Key responsibilities:
    - Provide image/quote commands (e.g., waifu, animequotes).
    - Expose a slash-only poll creator that uses PollInputModal for long-form input.
    - Manage the lifecycle of interactive GambleView objects and enforce per-user cooldowns.

    Important attributes:
    - active_views: nested mapping guild_id -> user_id -> GambleView to ensure a single
      active gamble UI per user.
    - _gamble_counts/_gamble_cooldowns: per-session attempt counters and cooldown timers
      used to protect users from excessive gambling attempts.
    """
    def __init__(self, bot):
        self.bot = bot
        self.gamble_cooldowns = {}
        self.active_views: Dict[int, Dict[int, "Fun.GambleView"]] = {}
        self.lock = asyncio.Lock()
        self._gamble_counts: Dict[tuple, int] = {}
        self._gamble_cooldowns: Dict[tuple, float] = {}
        self.GAMBLE_MAX_ATTEMPTS = 20
        self.GAMBLE_COOLDOWN_SECONDS = 5 * 60

        self.data_path = os.path.join(os.path.dirname(__file__), "..", "data", "quotes.json")
        try:
            with open(self.data_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            data = {}

        if isinstance(data, dict):
            self.quotes_dict = data
        elif isinstance(data, list):
            self.quotes_dict = {"Mixed": data}
        else:
            self.quotes_dict = {"Mixed": []}

        self.used_quotes = set()

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
        Unified send helper that works with both prefix Context and Interaction flows.

        Behavior:
        - If an Interaction is provided prefer interaction.response / followup semantics
          to preserve slash-command UX. Fall back to ctx.send when interaction responses
          fail (permissions, message not found).
        - Returns the sent Message when available; returns None when the message could
          not be retrieved (e.g., original_response not accessible).
        - Ephemeral flag is removed when falling back to ctx.send because that concept
          is not applicable to prefix messages.
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
        Return remaining cooldown seconds for a user's gamble session in a guild.

        Uses self._gamble_cooldowns keyed by (guild_id, user_id).
        """
        key = (guild_id, user_id)
        now = time.time()
        expires = self._gamble_cooldowns.get(key)
        if expires and expires > now:
            return int(expires - now)
        return 0

    def _start_session_cooldown(self, guild_id: int, user_id: int) -> None:
        """
        Begin the configured gamble cooldown for the given user, and clear the attempt counter.
        """
        key = (guild_id, user_id)
        self._gamble_cooldowns[key] = time.time() + self.GAMBLE_COOLDOWN_SECONDS
        self._gamble_counts.pop(key, None)

    def _count_attempt(self, guild_id: int, user_id: int) -> int:
        """
        Increment and return the number of gamble attempts in the current session.
        """
        key = (guild_id, user_id)
        new_val = self._gamble_counts.get(key, 0) + 1
        self._gamble_counts[key] = new_val
        return new_val

    def _clear_attempts(self, guild_id: int, user_id: int) -> None:
        """
        Clear the per-session attempt counter for a user.
        """
        self._gamble_counts.pop((guild_id, user_id), None)

    def _set_active_view(self, guild_id: int, user_id: int, view: Optional["Fun.GambleView"]) -> None:
        """
        Register or unregister an active GambleView for a specific user in a guild.

        If view is None the mapping is removed; otherwise the view is set.
        """
        self.active_views.setdefault(guild_id, {})
        if view is None:
            self.active_views[guild_id].pop(user_id, None)
        else:
            self.active_views[guild_id][user_id] = view

    def _get_active_view(self, guild_id: int, user_id: int) -> Optional["Fun.GambleView"]:
        """
        Return the active GambleView for a user if present; otherwise None.
        """
        return self.active_views.get(guild_id, {}).get(user_id)

    def get_balanced_quotes(self, num_quotes: int):
        """
        Return up to num_quotes quotes balancing across categories to avoid repeats.

        Notes:
        - Maintains a per-instance `used_quotes` set to reduce immediate repetition.
        - When all quotes are exhausted the used set is cleared and selection resumes.
        """
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

    @commands.hybrid_command(name="waifu", description="Get a random waifu image")
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def waifu(self, ctx):
        """
        Fetch a safe-for-work image from the waifu.pics API and send it as an embed.
        """
        url = "https://api.waifu.pics/sfw/waifu"

        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
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
        Slash-only entrypoint to create a poll using a modal (PollInputModal).

        The command validates duration bounds and opens the Modal via interaction response.
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

    # ===== Gamble helpers (logic split out to reduce complexity) =====

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
        Inform the user they don't have enough coins and attempt to refresh the gamble prompt.

        If the active view exists we also edit the prompt with the latest balance to keep UI state consistent.
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
        Credit winnings to the user and return a localized success message fragment.

        On failures the function attempts a minimal refund and returns None indicating
        an unrecoverable error occurred and the caller should abort further processing.
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
        Update the active gamble view prompt with the user's current balance.

        This keeps UI accurate when external events (other commands) modify balance.
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
        When a user exceeds the maximum allowed attempts, start a cooldown and disable the view.

        The function also attempts to persistently disable controls on the view so the UI
        is no longer actionable.
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
        """
        Re-enable UI controls for a user's active GambleView, if present.

        This is used to re-allow the user to continue gambling after a round completes.
        """
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
        Execute a single gamble attempt:
        - Validate amount
        - Reserve coins via progression_cog
        - Compute win probability based on bet ratio
        - Settle win or loss and update user with the result and new balance

        This function intentionally performs minimal UI changes (uses helper methods to
        inform about insufficient funds and to refresh prompts).
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

        base_chance = 0.5
        bet_ratio = (amount / pre_balance) if pre_balance else 1
        win_chance = max(0.201, base_chance - bet_ratio * 0.5)
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
        Orchestrate a full gamble cycle:
        - Run one gamble
        - Increment the attempt counter and apply session cooldown if threshold exceeded
        - Re-enable the GambleView controls for subsequent interactions
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
        if count >= self.GAMBLE_MAX_ATTEMPTS:
            await self._handle_gamble_cooldown_and_disable_view(
                ctx, interaction, guild_id, user_id
            )
            return

        await self._enable_gamble_view_controls_if_any(guild_id, user_id)

    # ===== View for gamble =====

    class GambleView(discord.ui.View):
        """
        Interactive view presented to users to select gamble amounts.

        Lifecycle:
        - Constructed with references to the parent Fun instance and progression cog.
        - The view maintains a short-lived timeout_task to auto-timeout the UI.
        - The view manipulates its own disabled state to prevent double submissions.
        """
        def __init__(
            self,
            *,
            fun: "Fun",
            ctx: commands.Context,
            user_id: int,
            guild_id: int,
            progression_cog,
            initial_coins: Optional[int],
            timeout: int = 120,
        ):
            super().__init__(timeout=None)
            self.fun = fun
            self.ctx = ctx
            self.bot = fun.bot
            self.user_id = user_id
            self.guild_id = guild_id
            self.progression_cog = progression_cog
            self.timeout_seconds = timeout
            self.timeout_task: Optional[asyncio.Task] = None
            self.message: Optional[discord.Message] = None
            self.initial_coins = initial_coins

            self.options_list = [
                ("100", 100, discord.PartialEmoji(name="Coins", id=1415353285270966403)),
                ("250", 250, discord.PartialEmoji(name="Coins", id=1415353285270966403)),
                ("500", 500, discord.PartialEmoji(name="Coins", id=1415353285270966403)),
                ("All In", -2, discord.PartialEmoji(name="Coins", id=1415353285270966403)),
                ("Custom", -1, None),
            ]
            self.select = self._create_select()
            self.add_item(self.select)

            self.exit_button = discord.ui.Button(label="Exit Gamble", style=discord.ButtonStyle.danger)
            self.exit_button.callback = self.exit_callback
            self.add_item(self.exit_button)

            self.reset_timeout()

        def _create_select_options(self):
            """
            Helper to build discord.SelectOption objects for the current options_list.
            """
            return [
                discord.SelectOption(label=label, value=str(value), emoji=emoji)
                for label, value, emoji in self.options_list
            ]

        def _create_select(self):
            """
            Construct and return a Select UI element wired to the view's select_callback.
            """
            select = discord.ui.Select(
                placeholder="Select amount to gamble",
                options=self._create_select_options(),
                min_values=1,
                max_values=1,
            )
            select.callback = self.select_callback
            return select

        def reset_timeout(self):
            """
            Restart the view's inactivity timeout task. Used to extend the UI lifetime
            after user interactions.
            """
            if self.timeout_task:
                self.timeout_task.cancel()
            self.timeout_task = self.bot.loop.create_task(self._timeout_handler())

        async def _timeout_handler(self):
            """
            Background coroutine that marks the view timed-out and clears active view mapping.
            """
            await asyncio.sleep(self.timeout_seconds)
            if self.message:
                try:
                    await self.message.edit(content="❌ Gamble timed out.", embed=None, view=None)
                except (discord.HTTPException, discord.Forbidden, discord.NotFound):
                    pass
            self.fun._set_active_view(self.guild_id, self.user_id, None)
            self.stop()

        async def _disable_controls(self):
            """
            Disable all interactive children and attempt to persist the disabled state to the message.
            """
            for item in self.children:
                if hasattr(item, "disabled"):
                    item.disabled = True
            if self.message:
                try:
                    await self.message.edit(view=self)
                except (discord.HTTPException, discord.Forbidden, discord.NotFound):
                    pass

        async def _enable_controls(self):
            """
            Re-enable interactive children and update the message view where possible.
            """
            for item in self.children:
                if hasattr(item, "disabled"):
                    item.disabled = False
            if self.message:
                try:
                    await self.message.edit(view=self)
                except (discord.HTTPException, discord.Forbidden, discord.NotFound):
                    pass

        async def _clear_selection(self):
            """
            Reset the Select to its original set of options and update the message.
            """
            self.select.options = self._create_select_options()
            if self.message:
                try:
                    await self.message.edit(view=self)
                except (discord.HTTPException, discord.Forbidden, discord.NotFound):
                    pass

        def _parse_value_from_interaction(self, interaction: discord.Interaction) -> Optional[int]:
            """
            Parse an integer selection value from the interaction payload or the Select state.

            Returns None for invalid or missing values.
            """
            try:
                value_raw = None
                if isinstance(getattr(interaction, "data", None), dict):
                    value_raw = interaction.data.get("values", [None])[0]
                if value_raw is None:
                    value_raw = self.select.values[0] if getattr(self.select, "values", None) else None
                if value_raw is None:
                    return None
                return int(value_raw)
            except (ValueError, TypeError, KeyError, AttributeError):
                return None

        async def _send_invalid_selection(self, interaction: discord.Interaction) -> None:
            """
            Notify the user that their selection was invalid and reset the selection UI.
            """
            await self.fun._send(self.ctx, interaction, "❌ Invalid selection.", ephemeral=True)
            await self._clear_selection()

        async def _edit_view_after_disable(self, interaction: discord.Interaction) -> None:
            """
            Attempt to persist the view state after controls have been disabled.

            Uses interaction.response.edit_message when possible, otherwise edits the stored message.
            """
            try:
                if not interaction.response.is_done():
                    await interaction.response.edit_message(view=self)
                elif self.message:
                    await self.message.edit(view=self)
            except (discord.HTTPException, discord.Forbidden, discord.NotFound):
                pass

        async def _show_custom_modal(self, interaction: discord.Interaction) -> None:
            """
            Present a small inline Modal for entering a custom gamble amount.

            The inner CustomModal enforces that only the session owner may submit and
            validates the provided amount against the user's current balance.
            """
            await self._clear_selection()

            parent = self

            class CustomModal(discord.ui.Modal):
                def __init__(inner_self):
                    title_text = (
                        "Custom Gamble"
                        if parent.initial_coins is None
                        else f"Custom Gamble (Max {parent.initial_coins})"
                    )
                    super().__init__(title=title_text)
                    inner_self.amount_input = discord.ui.TextInput(
                        label="Enter amount",
                        placeholder="Enter a positive number",
                        style=discord.TextStyle.short,
                    )
                    inner_self.add_item(inner_self.amount_input)

                async def on_submit(inner_self, inter: discord.Interaction):
                    if inter.user.id != parent.user_id:
                        await parent.fun._send(parent.ctx, inter, FALSE_GAMBLE_SESSION, ephemeral=True)
                        return
                    try:
                        amount = int(inner_self.amount_input.value)
                    except (ValueError, TypeError):
                        await parent.fun._send(parent.ctx, inter, "❌ Invalid number.", ephemeral=True)
                        await parent._clear_selection()
                        return
                    latest = await parent.progression_cog.get_coins(parent.user_id, parent.guild_id)
                    if amount <= 0 or amount > latest:
                        await parent.fun._send(
                            parent.ctx,
                            inter,
                            f"❌ Invalid amount. You have {latest} {ShopEmojis['Coins']}.",
                            ephemeral=True,
                        )
                        await parent._clear_selection()
                        return
                    await parent.fun._process_gamble(
                        parent.ctx,
                        inter,
                        guild_id=parent.guild_id,
                        user_id=parent.user_id,
                        progression_cog=parent.progression_cog,
                        amount=amount,
                    )
                    await parent._clear_selection()

            await interaction.response.send_modal(CustomModal())

        async def _handle_bet_value(self, interaction: discord.Interaction, value: int) -> None:
            """
            Core handler for numeric bet values including "All In" (-2) semantics.

            Disables controls during processing to avoid duplicate submissions.
            """
            await self._disable_controls()
            await self._edit_view_after_disable(interaction)

            bet = value
            if value == -2:
                bet = await self.progression_cog.get_coins(self.user_id, self.guild_id)

            if bet <= 0:
                await self.fun._send(self.ctx, interaction, "❌ Invalid bet amount.", ephemeral=True)
                await self._clear_selection()
                await self._enable_controls()
                return

            await self.fun._process_gamble(
                self.ctx,
                interaction,
                guild_id=self.guild_id,
                user_id=self.user_id,
                progression_cog=self.progression_cog,
                amount=bet,
            )
            await self._clear_selection()

        async def select_callback(self, interaction: discord.Interaction):
            """
            Select callback invoked when a user chooses a gamble option.

            Validates session ownership, parses the selection and dispatches to the appropriate handler.
            """
            if interaction.user.id != self.user_id:
                await self.fun._send(self.ctx, interaction, FALSE_GAMBLE_SESSION, ephemeral=True)
                return

            self.reset_timeout()

            value = self._parse_value_from_interaction(interaction)
            if value is None:
                return await self._send_invalid_selection(interaction)

            if value == -1:
                await self._show_custom_modal(interaction)
                return

            await self._handle_bet_value(interaction, value)

        async def exit_callback(self, interaction: discord.Interaction):
            """
            Exit the gamble UI. Only the session owner may exit; cleans up active view mapping.
            """
            if interaction.user.id != self.user_id:
                await self.fun._send(self.ctx, interaction, FALSE_GAMBLE_SESSION, ephemeral=True)
                return
            self.fun._set_active_view(self.guild_id, self.user_id, None)
            if self.timeout_task:
                self.timeout_task.cancel()
            try:
                if not interaction.response.is_done():
                    await interaction.response.edit_message(content="❌ Gamble exited.", embed=None, view=None)
                else:
                    await interaction.message.edit(content="❌ Gamble exited.", embed=None, view=None)
            except (discord.HTTPException, discord.Forbidden, discord.NotFound):
                pass
            self.stop()

    async def _send_gamble_cooldown_message(
        self,
        ctx: commands.Context,
        interaction: Optional[discord.Interaction],
        remaining: int,
    ) -> None:
        """
        Notify the user of remaining session cooldown in a user-friendly minutes:seconds format.
        """
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
        """
        Ensure the Progression cog is loaded and return it.

        The gamble flow depends on the Progression cog; if missing the user is informed.
        """
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
        """
        Verify the user has a positive coin balance before starting a gamble session.

        Returns the coin balance or None if the user cannot gamble.
        """
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
        view: "Fun.GambleView",
        user_coins: int,
    ) -> Optional[discord.Message]:
        """
        Present the gamble prompt and attach the provided view.

        Returns the message object when possible to allow the caller to tie the view to the message.
        """
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
        view: "Fun.GambleView",
        sent_message: Optional[discord.Message],
    ) -> None:
        """
        Attach the given view to the message returned by _send_gamble_prompt.

        When the send helper could not provide the Message object the function attempts
        to find the last message in the channel as a best-effort fallback.
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
        Entrypoint to open a GambleView for the invoking user.

        Flow:
        - Check per-session cooldown
        - Ensure Progression cog is available and the user has coins
        - Create and display a GambleView and register it in active_views
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

        view = Fun.GambleView(
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
        Send a single balanced anime quote wrapped in an embed.

        The selection is guarded by a lock to avoid concurrent modification of used_quotes.
        """
        async with self.lock:
            result = self.get_balanced_quotes(1)
            if not result:
                return await ctx.send("❌ No quotes available.")
            q = result[0]

        quote_text = q.get("quote", "")[:1900]
        character = q.get("character", "Unknown")
        anime = q.get("anime", "Unknown")

        embed = discord.Embed(title=f"{anime}", description=f"*“{quote_text}”*", color=discord.Color.blue())
        embed.set_footer(text=f"~ {character}")
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Fun(bot)) 