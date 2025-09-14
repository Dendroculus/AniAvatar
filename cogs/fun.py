import discord
from discord import app_commands
from discord.ext import commands
import aiohttp
from datetime import datetime, timedelta, timezone
import asyncio
import random

class PollView(discord.ui.View):
    def __init__(self, question: str, options: list[str], author: discord.Member, timeout: int = 60):
        super().__init__(timeout=timeout)
        self.question = question
        self.options = options
        self.votes = {opt: set() for opt in options}
        self.author = author
        self.message: discord.Message | None = None
        self.end_time = datetime.now(timezone.utc) + timedelta(seconds=timeout)
        self.updater_task: asyncio.Task | None = None

        select = discord.ui.Select(
            placeholder="Select one answer",
            options=[discord.SelectOption(label=opt, value=opt) for opt in options],  # ✅ force value = opt
            custom_id="poll_select"
        )

        select.callback = self.select_callback
        self.add_item(select)

        remove_button = discord.ui.Button(
            label="Remove Vote",
            style=discord.ButtonStyle.danger,
            custom_id="remove_vote"
        )
        remove_button.callback = self.remove_vote
        self.add_item(remove_button)
        
        end_button = discord.ui.Button(
            label="End Poll",
            style=discord.ButtonStyle.red,
            custom_id="end_poll"
        )
        end_button.callback = self.end_poll
        self.add_item(end_button)

    async def select_callback(self, interaction: discord.Interaction):
        choice = interaction.data["values"][0]

        if choice not in self.votes:
            return await interaction.response.send_message(
                "⚠️ Invalid choice, please try again.", ephemeral=True
            )

        for opt in self.votes:
            self.votes[opt].discard(interaction.user.id)

        self.votes[choice].add(interaction.user.id)
        await self.update_poll(interaction, f"✅ You voted for **{choice}**")


    async def remove_vote(self, interaction: discord.Interaction):
        removed = False
        for opt in self.votes:
            if interaction.user.id in self.votes[opt]:
                self.votes[opt].remove(interaction.user.id)
                removed = True
        if removed:
            await self.update_poll(interaction, "❌ Your vote was removed.")
        else:
            await interaction.response.send_message("⚠️ You haven't voted yet.", ephemeral=True)
            
    async def end_poll(self, interaction: discord.Interaction):
        if interaction.user.id != self.author.id:
            return await interaction.response.send_message(
                "⚠️ Only the poll creator can end this poll.", ephemeral=True
            )
        if self.updater_task and not self.updater_task.done():
            self.updater_task.cancel()
        await self.on_timeout()
        await interaction.response.send_message("✅ Poll ended.", ephemeral=True)

    async def update_poll(self, interaction: discord.Interaction, ephemeral_msg: str):
        embed = self.make_poll_embed(interaction.user.id)
        await self.message.edit(embed=embed, view=self)
        await interaction.response.send_message(ephemeral_msg, ephemeral=True)

    def make_poll_embed(self, user_id: int):
        total_votes = sum(len(users) for users in self.votes.values())
        lines = []

        # ✅ find the longest option length
        max_len = max(len(opt) for opt in self.options)

        for opt, users in self.votes.items():
            count = len(users)
            percent = (count / total_votes * 100) if total_votes > 0 else 0
            blocks = int(percent // 10)
            bar = "█" * blocks + "▬" * (10 - blocks)
            check = "[x]" if user_id in users else "[ ]"

            # pad options dynamically
            lines.append(
                f"```{check} {opt.ljust(max_len)} | {bar} | {count:>2} votes ({percent:>3.0f}%)```"
            )

        remaining = max(0, int((self.end_time - datetime.utcnow()).total_seconds()))
        mins, secs = divmod(remaining, 60)
        hours, mins = divmod(mins, 60)

        if remaining > 0:
            if hours > 0:
                timer = f"{hours}h {mins}m {secs}s left"
            elif mins > 0:
                timer = f"{mins}m {secs}s left"
            else:
                timer = f"{secs}s left"
            footer = f"{total_votes} vote(s) • {timer}"
        else:
            footer = f"{total_votes} vote(s) • Poll closed"

        embed = discord.Embed(
            title=f"{self.question}",
            description="\n".join(lines) + f"\n\n{footer}",
            color=discord.Color.blurple()
        )
        return embed

    async def start_updater(self):
        """Background task to auto-update poll timer."""
        try:
            while datetime.utcnow() < self.end_time and self.message:
                await asyncio.sleep(0.5)  
                embed = self.make_poll_embed(0)
                await self.message.edit(embed=embed, view=self)
        except Exception as e:
            print(f"[Poll Updater Error] {e}")

        await self.on_timeout()

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message:
            final_embed = self.make_poll_embed(0)
            final_embed.title = f"Poll Ended — {self.question}"
            desc = final_embed.description.rsplit("•", 1)[0] + "• Poll closed"
            final_embed.description = desc
            await self.message.edit(embed=final_embed, view=self)

            results = {opt: len(users) for opt, users in self.votes.items()}
            if results:
                max_votes = max(results.values())
                winners = [opt for opt, count in results.items() if count == max_votes]

                if len(winners) == 1:
                    winner_text = f"<:CHAMPION:1414508304448749568> The winner is **{winners[0]}** with {max_votes} vote(s)!"
                else:
                    winner_text = f"🤝 It's a tie between: {', '.join(winners)} ({max_votes} vote(s) each)."

                await self.message.channel.send(winner_text)
                
class Fun(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.gamble_cooldowns = {}
        self.active_views = {}

    @commands.hybrid_command(name="waifu", description="Get a random waifu image")
    async def waifu(self, ctx):
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
    @app_commands.describe(
        question="The question to ask",
        duration="How long should the poll last?",
        custom_minutes="(Only if you selected Custom) Enter duration in minutes",
        options="Options separated by commas (e.g. A, B, C)"
    )
    @app_commands.choices(duration=[
        app_commands.Choice(name="5 minutes", value=300),
        app_commands.Choice(name="20 minutes", value=1200),
        app_commands.Choice(name="1 hour", value=3600),
        app_commands.Choice(name="1 day", value=86400),
        app_commands.Choice(name="Half a day", value=43200),
        app_commands.Choice(name="Custom", value=-1),  
    ])
    async def poll(self, ctx, question: str, duration: app_commands.Choice[int], custom_minutes: int = None, *, options: str):
        options = options.split(", ")
        if len(options) < 2:
            return await ctx.send("❌ Please provide at least two options.")
        if len(options) > 5:
            return await ctx.send("⚠️ Max 5 options allowed.")

        if duration.value == -1:  # custom
            if not custom_minutes or custom_minutes <= 0:
                return await ctx.send("⚠️ Please provide a valid custom duration in minutes.")
            time = custom_minutes * 60
        else:
            time = duration.value
            
        if time > 604800:  
            return await ctx.send("⚠️ Poll duration cannot exceed 7 days.")

        view = PollView(question, options, ctx.author, timeout=time)
        embed = view.make_poll_embed(ctx.author.id)
        msg = await ctx.send(embed=embed, view=view)
        view.message = msg
        view.updater_task = ctx.bot.loop.create_task(view.start_updater())

    @commands.hybrid_command(name="gamble", description="Gamble your coins!")
    @commands.guild_only()
    async def gamble(self, ctx: commands.Context):
        user_id = ctx.author.id
        guild_id = ctx.guild.id
        
        if self.active_views.get(user_id, {}).get("gamble"):
            return await ctx.send("⚠️ You already have the gamble view open!", ephemeral=True)
        
        progression_cog = self.bot.get_cog("Progression")
        if not progression_cog:
            return await ctx.send("❌ Progression cog not loaded. Coins unavailable.")

        user_coins = await progression_cog.get_coins(user_id, guild_id)
        if user_coins <= 0:
            return await ctx.send("❌ You don't have any coins to gamble!")

        class GambleSelect(discord.ui.View):
            def __init__(self, bot, user_id, guild_id, active_views, timeout=120):
                super().__init__(timeout=None)  # we'll use our own timeout_task
                self.bot = bot
                self.user_id = user_id
                self.guild_id = guild_id
                self.active_views = active_views
                self.timeout_task = None
                self.timeout_seconds = timeout
                self.message = None

                # Dropdown options
                self.options_list = [
                    ("100", 100, discord.PartialEmoji(name="Coins", id=1415353285270966403)),
                    ("250", 250, discord.PartialEmoji(name="Coins", id=1415353285270966403)),
                    ("500", 500, discord.PartialEmoji(name="Coins", id=1415353285270966403)),
                    ("All In", -2, discord.PartialEmoji(name="Coins", id=1415353285270966403)),
                    ("Custom", -1, None)
                ]
                self.select = self.create_select()
                self.add_item(self.select)

                # Exit button
                self.exit_button = discord.ui.Button(
                    label="Exit Gamble",
                    style=discord.ButtonStyle.danger
                )
                self.exit_button.callback = self.exit_callback
                self.add_item(self.exit_button)

                # start timeout
                self.reset_timeout()

            def create_select(self):
                select = discord.ui.Select(
                    placeholder="Select amount to gamble",
                    options=[
                        discord.SelectOption(label=label, value=str(value), emoji=emoji)
                        for label, value, emoji in self.options_list
                    ],
                    min_values=1, max_values=1
                )
                select.callback = self.select_callback
                return select

            async def select_callback(self, interaction: discord.Interaction):
                if interaction.user.id != self.user_id:
                    return await interaction.response.send_message(
                        "⚠️ This is not your gamble session.", ephemeral=True
                    )

                # restart timeout on interaction
                self.reset_timeout()

                user_coins = await progression_cog.get_coins(self.user_id, self.guild_id)
                value = int(self.select.values[0])

                if value == -2:  # All In
                    value = user_coins

                if value == -1:  # Custom modal
                    class CustomModal(discord.ui.Modal):
                        def __init__(self):
                            super().__init__(title="Custom Gamble")
                            self.amount_input = discord.ui.TextInput(
                                label="Enter amount",
                                placeholder=f"Max {user_coins} Coins",
                                style=discord.TextStyle.short
                            )
                            self.add_item(self.amount_input)

                        async def on_submit(self, modal_interaction: discord.Interaction):
                            try:
                                amount = int(self.amount_input.value)
                                if amount <= 0 or amount > user_coins:
                                    return await modal_interaction.response.send_message(
                                        f"❌ Invalid amount. You have {user_coins} <:Coins:1415353285270966403>.",
                                        ephemeral=True
                                    )
                                await process_gamble(modal_interaction, amount)
                            except ValueError:
                                await modal_interaction.response.send_message("❌ Invalid number.", ephemeral=True)

                    await interaction.response.send_modal(CustomModal())
                else:
                    if value > user_coins:
                        await interaction.response.send_message(
                            f"❌ Not enough coins. You have {user_coins} <:Coins:1415353285270966403>.",
                            ephemeral=True
                        )
                    else:
                        await process_gamble(interaction, value)

                # Reset the dropdown UI so the user can choose again
                self.remove_item(self.select)
                self.select = self.create_select()
                self.add_item(self.select)

                new_coins = await progression_cog.get_coins(self.user_id, self.guild_id)
                try:
                    await interaction.message.edit(
                        content=f"You have {new_coins} <:Coins:1415353285270966403>. Select amount to gamble:",
                        view=self
                    )
                except Exception:
                    # fallback: attempt to edit via response if the interaction still allows it
                    try:
                        await interaction.response.edit_message(
                            content=f"You have {new_coins} <:Coins:1415353285270966403>. Select amount to gamble:",
                            view=self
                        )
                    except Exception:
                        pass

            async def exit_callback(self, interaction: discord.Interaction):
                if interaction.user.id != self.user_id:
                    return await interaction.response.send_message(
                        "⚠️ This is not your gamble session.", ephemeral=True
                    )

                # pop stored view so user can reopen
                try:
                    self.active_views.get(self.user_id, {}).pop("gamble", None)
                except Exception:
                    pass

                # cancel timeout task if running
                try:
                    if self.timeout_task:
                        self.timeout_task.cancel()
                except Exception:
                    pass

                # replace message with clean closed message
                try:
                    await interaction.response.edit_message(content="❌ Gamble exited.", embed=None, view=None)
                except Exception:
                    # if edit_message isn't available, fall back
                    try:
                        await interaction.message.edit(content="❌ Gamble exited.", embed=None, view=None)
                    except Exception:
                        pass

                # stop the view
                self.stop()

            def reset_timeout(self):
                # cancel previous task
                try:
                    if self.timeout_task:
                        self.timeout_task.cancel()
                except Exception:
                    pass
                # schedule a new one
                self.timeout_task = self.bot.loop.create_task(self.timeout_handler())

            async def timeout_handler(self):
                try:
                    await asyncio.sleep(self.timeout_seconds)
                    # on timeout, auto-close message and remove lock
                    try:
                        if hasattr(self, "message") and self.message:
                            await self.message.edit(content="❌ Gamble timed out.", embed=None, view=None)
                    except Exception:
                        pass

                    try:
                        self.active_views.get(self.user_id, {}).pop("gamble", None)
                    except Exception:
                        pass

                    self.stop()
                except asyncio.CancelledError:
                    return


        async def process_gamble(interaction: discord.Interaction, amount: int):
            user_total_coins = await progression_cog.get_coins(user_id, guild_id)
            base_chance = 0.5
            bet_ratio = amount / user_total_coins
            win_chance = max(0.13, base_chance - bet_ratio * 0.5)

            if random.random() < win_chance:
                await progression_cog.add_coins(user_id, guild_id, amount)
                if amount == user_total_coins:
                    result_text = f"<:MinoriAmazed:1416024121837490256> WOOOAA JACKPOT! You just doubled everything you own!"
                else :
                    result_text = f"<:MinoriAmazed:1416024121837490256> You won {amount} <:Coins:1415353285270966403>!"
            else:
                await progression_cog.remove_coins(user_id, guild_id, amount)
                result_text = f"<:MinoriDissapointed:1416016691430821958> You lost {amount} <:Coins:1415353285270966403>."

            new_balance = await progression_cog.get_coins(user_id, guild_id)
            try:
                await interaction.response.send_message(
                    f"{result_text} Your new balance: {new_balance} <:Coins:1415353285270966403>."
                )
            except discord.errors.InteractionResponded:
                await interaction.followup.send(
                    f"{result_text} Your new balance: {new_balance} <:Coins:1415353285270966403>."
                )

        view = GambleSelect(self.bot, user_id, guild_id, self.active_views)
        self.active_views.setdefault(user_id, {})["gamble"] = view
        
        message = await ctx.send(
            f"You have {user_coins} <:Coins:1415353285270966403>. Select amount to gamble:",
            view=view
        )
        view.message = message

async def setup(bot):
    await bot.add_cog(Fun(bot))
    print("📦 Loaded fun cog.")
