import discord
from discord import app_commands
from discord.ext import commands
import aiohttp
import asyncio
import random
import json
import os
from itertools import cycle

from cogs.utils.pollUtils import *
                
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
        if duration > 7 *24*60:
            return await ctx.interaction.response.send_message(
                "<:MinoriDisapointed:1416016691430821958> Duration cannot exceed 7 days.",
                ephemeral=True
            )

        timeout_seconds = duration * 60

        poll_modal = PollInputModal(ctx, timeout_seconds=timeout_seconds)
        await ctx.interaction.response.send_modal(poll_modal)


    @commands.hybrid_command(name="gamble", description="Gamble your coins!")
    @commands.guild_only()
    async def gamble(self, ctx: commands.Context):
        user_id = ctx.author.id
        guild_id = ctx.guild.id
        
        if self.active_views.get(guild_id, {}).get(user_id):
            return await ctx.send("⚠️ You already have the gamble view open!", ephemeral=True)
        
        progression_cog = self.bot.get_cog("Progression")
        if not progression_cog:
            return await ctx.send("❌ Progression cog not loaded. Coins unavailable.")

        user_coins = await progression_cog.get_coins(user_id, guild_id)
        if user_coins <= 0:
            return await ctx.send("❌ You don't have any coins to gamble!")

        class GambleSelect(discord.ui.View):
            def __init__(self, bot, user_id, guild_id, active_views, timeout=120):
                super().__init__(timeout=None) 
                self.bot = bot
                self.user_id = user_id
                self.guild_id = guild_id
                self.active_views = active_views
                self.timeout_task = None
                self.timeout_seconds = timeout
                self.message = None

                self.options_list = [
                    ("100", 100, discord.PartialEmoji(name="Coins", id=1415353285270966403)),
                    ("250", 250, discord.PartialEmoji(name="Coins", id=1415353285270966403)),
                    ("500", 500, discord.PartialEmoji(name="Coins", id=1415353285270966403)),
                    ("All In", -2, discord.PartialEmoji(name="Coins", id=1415353285270966403)),
                    ("Custom", -1, None)
                ]
                self.select = self.create_select()
                self.add_item(self.select)

                self.exit_button = discord.ui.Button(
                    label="Exit Gamble",
                    style=discord.ButtonStyle.danger
                )
                self.exit_button.callback = self.exit_callback
                self.add_item(self.exit_button)

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

                try:
                    value_raw = None
                    if isinstance(getattr(interaction, "data", None), dict):
                        value_raw = interaction.data.get("values", [None])[0]
                    if value_raw is None:
                        value_raw = self.select.values[0] if getattr(self.select, "values", None) else None
                    if value_raw is None:
                        raise ValueError("no selection")
                    value = int(value_raw)
                except Exception:
                    return await interaction.response.send_message("❌ Invalid selection.", ephemeral=True)

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
                                latest_coins = await progression_cog.get_coins(user_id, guild_id)
                                if amount <= 0 or amount > latest_coins:
                                    return await modal_interaction.response.send_message(
                                        f"❌ Invalid amount. You have {latest_coins} <:Coins:1415353285270966403>.",
                                        ephemeral=True
                                    )
                                await process_gamble(modal_interaction, amount)
                            except ValueError:
                                await modal_interaction.response.send_message("❌ Invalid number.", ephemeral=True)

                    await interaction.response.send_modal(CustomModal())
                    return  

                if value > user_coins:
                    return await interaction.response.send_message(
                        f"❌ Not enough coins. You have {user_coins} <:Coins:1415353285270966403>.",
                        ephemeral=True
                    )

                await process_gamble(interaction, value)
                return


            async def exit_callback(self, interaction: discord.Interaction):
                if interaction.user.id != self.user_id:
                    return await interaction.response.send_message(
                        "⚠️ This is not your gamble session.", ephemeral=True
                    )

                try:
                    self.active_views.get(self.guild_id, {}).pop(self.user_id, None)
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
                        self.active_views.get(self.guild_id, {}).pop(self.user_id, None)
                    except Exception:
                        pass

                    self.stop()
                except asyncio.CancelledError:
                    return


        async def process_gamble(interaction: discord.Interaction, amount: int):
            user_total_coins = await progression_cog.get_coins(user_id, guild_id)
            base_chance = 0.5
            bet_ratio = (amount / user_total_coins) if user_total_coins else 1
            win_chance = max(0.201, base_chance - bet_ratio * 0.5)
            
            if random.random() < win_chance:
                await progression_cog.add_coins(user_id, guild_id, amount)
                if amount == user_total_coins:
                    result_text = f"<:MinoriAmazed:1416024121837490256> WOOOAA JACKPOT! You just doubled everything you own!"
                else:
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

            try:
                view_obj = self.active_views.get(guild_id, {}).get(user_id)
                if view_obj and getattr(view_obj, "message", None):
                    await view_obj.message.edit(
                        content=f"You have {new_balance} <:Coins:1415353285270966403>. Select amount to gamble:",
                        view=view_obj
                    )
            except Exception:
                pass

        view = GambleSelect(self.bot, user_id, guild_id, self.active_views)
        self.active_views.setdefault(guild_id, {})[user_id] = view
        
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
