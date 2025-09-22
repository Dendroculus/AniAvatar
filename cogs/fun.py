import discord
from discord import app_commands, ui
from discord.ext import commands
import aiohttp
from datetime import datetime, timedelta, timezone 
import asyncio
import random
from typing import List, Optional
import json
import os
from itertools import cycle

class PollView(discord.ui.View):
    def __init__(self, question: str, options: List[str], author: discord.Member, timeout: Optional[int] = None):
        super().__init__(timeout=timeout)
        self.question = question
        self.options = options
        self.votes = {opt: set() for opt in options}
        self.author = author
        self.message: Optional[discord.Message] = None
        self.updater_task: Optional[asyncio.Task] = None
        self.ended = False
        self.end_time = (datetime.now(timezone.utc) + timedelta(seconds=timeout)) if timeout else None

        add_button = discord.ui.Button(label="Add Option", style=discord.ButtonStyle.green)
        add_button.callback = self.add_option
        self.add_item(add_button)
            
        select = discord.ui.Select(
            placeholder="Select one answer",
            options=[discord.SelectOption(label=opt, value=str(i)) for i, opt in enumerate(options)],
            min_values=1,
            max_values=1
        )
        select.callback = self.select_callback
        self.add_item(select)

        remove_button = discord.ui.Button(label="Remove Vote", style=discord.ButtonStyle.danger)
        remove_button.callback = self.remove_vote
        self.add_item(remove_button)

        end_button = discord.ui.Button(label="End Poll", style=discord.ButtonStyle.red)
        end_button.callback = self.end_poll
        self.add_item(end_button)
        
    async def add_option(self, interaction: discord.Interaction):
        if interaction.user.id != self.author.id:
            return await interaction.response.send_message("⚠️ Only the poll creator can add options.", ephemeral=True)
        
        modal = AddOptionModal(self)
        await interaction.response.send_modal(modal)

    async def select_callback(self, interaction: discord.Interaction):
        try:
            val = interaction.data["values"][0]   
            idx = int(val)
        except Exception:
            return await interaction.response.send_message("⚠️ Invalid selection.", ephemeral=True)

        if idx < 0 or idx >= len(self.options):
            return await interaction.response.send_message("⚠️ Invalid choice.", ephemeral=True)

        choice_label = self.options[idx]

        # remove previous votes by user
        for opt in self.votes:
            self.votes[opt].discard(interaction.user.id)
        self.votes[choice_label].add(interaction.user.id)
        await self.update_poll(interaction, f"<:VERIFIED:1418921885692989532> You voted for **{choice_label}**")

    
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
            return await interaction.response.send_message("⚠️ Only the poll creator can end this poll.", ephemeral=True)

        if self.updater_task and not self.updater_task.done():
            self.updater_task.cancel()

        await interaction.response.defer(ephemeral=True)
        await self.on_timeout()

    async def update_poll(self, interaction: discord.Interaction, ephemeral_msg: str):
        embed = self.make_poll_embed()
        if self.message:
            await self.message.edit(embed=embed, view=self)
        try:
            await interaction.response.send_message(ephemeral_msg, ephemeral=True)
        except discord.errors.InteractionResponded:
            await interaction.followup.send(ephemeral_msg, ephemeral=True)

    def make_poll_embed(self, closed: bool = False):
        total_votes = sum(len(v) for v in self.votes.values())
        lines = []
        colors = ["🟦", "🟥", "🟩", "🟨", "🟪", "🟧", "🟫", "🟦", "🟥", "🟩", "🟨", "🟪", "🟧", "🟫", "🟦"]

        for i, (opt, users) in enumerate(self.votes.items()):
            count = len(users)
            percent = (count / total_votes * 100) if total_votes > 0 else 0
            filled = int(percent // 10)
            empty = 10 - filled
            color = colors[i % len(colors)]
            bar = color * filled + "<:Gray_Large_Square:1418999479557685380>" * empty
            lines.append(f"{opt}\n{bar} `{percent:.0f}% ({count})`")

        description = f"{total_votes} votes\n\n" + "\n\n".join(lines)

        if closed:
            description += "\n\n<:Locked:1419005340812316893> Poll closed\n <:SecretBox:1418986878949916722> Votes are anonymous"
        else:
            if self.end_time:
                unix_ts = int(self.end_time.timestamp())
                description += f"\n\n<:TIME:1415961777912545341> Poll closes <t:{unix_ts}:R>\n <:SecretBox:1418986878949916722> Votes are anonymous"

        title = f"<:CHART:1418908749749420085>  {self.question}"
        embed = discord.Embed(title=title, description=description, color=discord.Color.blurple())
        return embed

    async def on_timeout(self):
        if self.ended:
            return
        self.ended = True
        self.clear_items()
        if self.message:
            results = {opt: len(users) for opt, users in self.votes.items()}
            winner_text = ""
            if results:
                max_votes = max(results.values())
                winners = [opt for opt, count in results.items() if count == max_votes]
                if max_votes > 0:
                    if len(winners) == 1:
                        winner_text = f"\n\n<:MinoriPray:1418919979272896634> Poll ended. The highest vote goes to **{winners[0]}** with {max_votes} vote{'s' if max_votes!=1 else ''}."
                    else:
                        winner_text = f"\n\n<:MinoriPray:1418919979272896634> Poll ended. It's a tie between {', '.join(winners)} — each with {max_votes} votes."
                else:
                    winner_text = "\n\n<:MinoriWink:1414899695209418762> Poll ended. No votes were cast."
            final_embed = self.make_poll_embed(closed=True)
            await self.message.edit(embed=final_embed, view=self)
            if winner_text:
                await self.message.channel.send(winner_text)

class AddOptionModal(ui.Modal, title="Add Poll Options"):
    opt1 = ui.TextInput(label="Option 1 (optional)", required=False, max_length=100,
                        placeholder="Leave empty if not needed")
    opt2 = ui.TextInput(label="Option 2 (optional)", required=False, max_length=100,
                        placeholder="Leave empty if not needed")
    opt3 = ui.TextInput(label="Option 3 (optional)", required=False, max_length=100,
                        placeholder="Leave empty if not needed")
    opt4 = ui.TextInput(label="Option 4 (optional)", required=False, max_length=100,
                        placeholder="Leave empty if not needed")
    opt5 = ui.TextInput(label="Option 5 (optional)", required=False, max_length=100,
                        placeholder="Leave empty if not needed")

    def __init__(self, poll_view: "PollView"):
        super().__init__()
        self.poll_view = poll_view
        self.description = "Note: Discord only allows a maximum of 25 options per select menu."

    async def on_submit(self, interaction: discord.Interaction):
        new_opts_raw = [
            self.opt1.value.strip(),
            self.opt2.value.strip(),
            self.opt3.value.strip(),
            self.opt4.value.strip(),
            self.opt5.value.strip()
        ]
        new_opts = [o for o in new_opts_raw if o]

        if not new_opts:
            return await interaction.response.send_message(
                "⚠️ No new options were added.", ephemeral=True
            )

        normalized_existing = [o.lower() for o in self.poll_view.options]
        for opt in new_opts:
            if opt.lower() in normalized_existing:
                return await interaction.response.send_message(
                    "<:MinoriConfused:1415707082988060874> You can't add duplicate options.",
                    ephemeral=True
                )

        if len(self.poll_view.options) + len(new_opts) > 15:
            return await interaction.response.send_message(
                "⚠️ You can only add up to 15 options.", ephemeral=True
            )

        for opt in new_opts:
            self.poll_view.options.append(opt)
            self.poll_view.votes[opt] = set()
            select: discord.ui.Select = next(
                (i for i in self.poll_view.children if isinstance(i, discord.ui.Select)), None
            )
            if select:
                select.options = [discord.SelectOption(label=opt, value=str(idx)) 
                                for idx, opt in enumerate(self.poll_view.options)]

        embed = self.poll_view.make_poll_embed()
        await self.poll_view.message.edit(embed=embed, view=self.poll_view)
        await interaction.response.send_message(f"<:VERIFIED:1418921885692989532> Added {len(new_opts)} option(s).", ephemeral=True)

class PollInputModal(ui.Modal, title="Create Poll"):
    question = ui.TextInput(label="Question", placeholder="What's the poll about?", required=True, max_length=200)
    opt1 = ui.TextInput(label="Option 1 (required)", placeholder="First option (required)", required=True, max_length=100)
    opt2 = ui.TextInput(label="Option 2 (required)", placeholder="Second option (required)", required=True, max_length=100)
    opt3 = ui.TextInput(label="Option 3 (optional)", placeholder="Third option (optional)", required=False, max_length=100)
    opt4 = ui.TextInput(label="Option 4 (optional)", placeholder="Fourth option (optional)", required=False, max_length=100)

    def __init__(self, ctx: commands.Context, timeout_seconds: Optional[int] = None):
        super().__init__()
        self.ctx = ctx
        self.timeout_seconds = timeout_seconds

    async def select_callback(self, interaction: discord.Interaction):
        try:
            val = interaction.data["values"][0]   # index as string
            idx = int(val)
        except Exception:
            return await interaction.response.send_message("⚠️ Invalid selection.", ephemeral=True)

        if idx < 0 or idx >= len(self.options):
            return await interaction.response.send_message("⚠️ Invalid choice.", ephemeral=True)

        choice_label = self.options[idx]

        # remove previous votes by user
        for opt in self.votes:
            self.votes[opt].discard(interaction.user.id)
        self.votes[choice_label].add(interaction.user.id)
        await self.update_poll(interaction, f"<:VERIFIED:1418921885692989532> You voted for **{choice_label}**")
        
    async def on_submit(self, interaction: discord.Interaction):
        raw_opts = [
            self.opt1.value.strip(),
            self.opt2.value.strip(),
            self.opt3.value.strip(),
            self.opt4.value.strip()
        ]
        opts = [o for o in raw_opts if o]

        # require at least 2 options
        if len(opts) < 2:
            return await interaction.response.send_message(
                "⚠️ Please provide at least two options (Option 1 and Option 2 are required).",
                ephemeral=True
            )

        # Duplicate check (normalize: trim + lower)
        normalized = [o.strip().lower() for o in opts]
        if len(set(normalized)) != len(normalized):
            return await interaction.response.send_message(
                "<:MinoriConfused:1415707082988060874> You cant make same options",
                ephemeral=True
            )
        try:
            view = PollView(self.question.value, opts, self.ctx.author, timeout=self.timeout_seconds)
            embed = view.make_poll_embed()
            msg = await self.ctx.send(embed=embed, view=view)
            view.message = msg
            try:
                await interaction.response.send_message("<:VERIFIED:1418921885692989532> Poll successfully created!", ephemeral=True)
            except discord.errors.InteractionResponded:
                await interaction.followup.send("<:VERIFIED:1418921885692989532> Poll successfully created!", ephemeral=True)
        except Exception as e:
            print(f"[Poll Create Error] {e}")
            try:
                await interaction.response.send_message(f"⚠️ Failed to create poll: {e}", ephemeral=True)
            except discord.errors.InteractionResponded:
                await interaction.followup.send(f"⚠️ Failed to create poll: {e}", ephemeral=True)

                
class Fun(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.gamble_cooldowns = {}
        self.active_views = {}
        self.lock = asyncio.Lock()
        
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

    def get_balanced_quotes(self, num_quotes: int):
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
    @app_commands.describe(duration="How long should the poll last in minutes?")
    async def poll(self, ctx: commands.Context, duration: int):
        if not getattr(ctx, "interaction", None):
            return await ctx.send("<:MinoriConfused:1415707082988060874> Please use the slash (/) version of this command so the bot can open modals.")

        if duration < 1:
            return await ctx.interaction.response.send_message(
                "<:MinoriDisapointed:1416016691430821958> Duration must be at least 1 minute.",
                ephemeral=True
            )
        if duration > 7*24*60:
            return await ctx.interaction.response.send_message(
                "<:MinoriDisapointed:1416016691430821958> Duration cannot exceed 7 days.",
                ephemeral=True
            )

        timeout_seconds = duration * 60

        # open modal for poll options
        poll_modal = PollInputModal(ctx, timeout_seconds=timeout_seconds)
        await ctx.interaction.response.send_modal(poll_modal)

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

                self.reset_timeout()

                user_coins = await progression_cog.get_coins(self.user_id, self.guild_id)
                value = int(self.select.values[0])

                if value == -2:  
                    value = user_coins

                if value == -1:  
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

                try:
                    self.active_views.get(self.user_id, {}).pop("gamble", None)
                except Exception:
                    pass

                try:
                    if self.timeout_task:
                        self.timeout_task.cancel()
                except Exception:
                    pass

                try:
                    await interaction.response.edit_message(content="❌ Gamble exited.", embed=None, view=None)
                except Exception:
                    try:
                        await interaction.message.edit(content="❌ Gamble exited.", embed=None, view=None)
                    except Exception:
                        pass

                self.stop()

            def reset_timeout(self):
                try:
                    if self.timeout_task:
                        self.timeout_task.cancel()
                except Exception:
                    pass
                self.timeout_task = self.bot.loop.create_task(self.timeout_handler())

            async def timeout_handler(self):
                try:
                    await asyncio.sleep(self.timeout_seconds)
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
            win_chance = max(0.201, base_chance - bet_ratio * 0.5)
            
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
        
    @commands.hybrid_command(name="animequotes", description="Give a random anime quote")
    async def animequotes(self, ctx: commands.Context):
        async with self.lock:
            result = self.get_balanced_quotes(1)
            if not result:
                return await ctx.send("❌ No quotes available.")
            q = result[0]

        quote_text = q.get("quote", "")[:1900]  
        character = q.get("character", "Unknown")
        anime = q.get("anime", "Unknown")

        embed = discord.Embed(
            title=f"{anime}",
            description=f"*“{quote_text}”*",
            color=discord.Color.blue() 
        )
        embed.set_footer(text=f"~ {character}")
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Fun(bot))
    print("📦 Loaded fun cog.")
