import discord
from discord.ext import commands
from discord import app_commands
import random
import asyncio
import json
import os
from itertools import cycle

from cogs.utils.anime_api import fetch_random_character, build_character_select_options
from cogs.utils.game_text import random_win_message, random_lose_message, compute_rewards, award_rewards

class Games(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.data_path = os.path.join(os.path.dirname(__file__), "..", "data", "trivia.json")
        with open(self.data_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, dict):
            self.trivia_dict = data
        elif isinstance(data, list):
            self.trivia_dict = {"Mixed": data}
        else:
            self.trivia_dict = {"Mixed": []}

        self.used_questions = set()

    def get_balanced_questions(self, num_questions: int):
        titles = list(self.trivia_dict.keys())
        random.shuffle(titles)
        questions = []
        title_cycle = cycle(titles)

        while len(questions) < num_questions:
            title = next(title_cycle)
            available = [q for q in self.trivia_dict[title] if q["question"] not in self.used_questions]
            if available:
                q = random.choice(available)
                self.used_questions.add(q["question"])
                questions.append(q)

            if len(self.used_questions) >= sum(len(qs) for qs in self.trivia_dict.values()):
                self.used_questions.clear()

        return questions

    async def _handle_correct_answer(
        self,
        user_id: int,
        guild_id: int,
        send_fn, 
        *,
        exp_mul=(2, 3),
        exp_base=(5, 10),
        coin_range=(15, 30)
    ):
        profile_cog = self.bot.get_cog("Progression")
        if not profile_cog:
            await send_fn("✅ Correct!")
            return

        exp_level_tuple = await profile_cog.get_user(user_id, guild_id)
        current_level = int(exp_level_tuple[1]) if exp_level_tuple else 1

        exp_reward, coin_reward = compute_rewards(
            level=current_level,
            exp_mul=exp_mul,
            exp_base=exp_base,
            coin_range=coin_range,
        )

        await award_rewards(profile_cog, user_id, guild_id, exp_reward, coin_reward)
        await send_fn(random_win_message(exp_reward, coin_reward))

    @commands.hybrid_command(name="animequiz", description="Start an anime trivia quiz.")
    @commands.guild_only()
    @app_commands.describe(questions="Number of questions")
    @app_commands.choices(questions=[
        app_commands.Choice(name="5", value=5),
        app_commands.Choice(name="10", value=10),
        app_commands.Choice(name="15", value=15),
        app_commands.Choice(name="20", value=20),
    ])
    async def animequiz(self, ctx, questions: app_commands.Choice[int]):
        num_questions = questions.value
        quiz_questions = self.get_balanced_questions(num_questions)
        score = 0

        for idx, question in enumerate(quiz_questions, 1):
            options_list = list(question["options"])
            random.shuffle(options_list)
            options = [discord.SelectOption(label=opt, value=opt) for opt in options_list]

            embed = discord.Embed(
                title=f"Question {idx}/{num_questions}",
                description=question["question"]
            )
            view = discord.ui.View()
            future = asyncio.get_event_loop().create_future()

            select = discord.ui.Select(placeholder="Choose an answer...", options=options)
            view.add_item(select)

            async def callback(interaction: discord.Interaction):
                if interaction.user != ctx.author:
                    await interaction.response.send_message("This is not your game!", ephemeral=True)
                    return
                if not future.done():
                    future.set_result(interaction.data["values"][0])
                select.disabled = True
                await interaction.response.edit_message(view=view)

            select.callback = callback

            message = await ctx.send(embed=embed, view=view)

            try:
                selected = await asyncio.wait_for(future, timeout=15)

                if selected == question["answer"]:
                    score += 1
                    async def send_ctx(msg: str):
                        await ctx.send(msg)
                    # Use gentler coin range for quiz mode
                    await self._handle_correct_answer(
                        ctx.author.id,
                        ctx.guild.id,
                        send_ctx,
                        exp_mul=(2, 3),
                        exp_base=(5, 10),
                        coin_range=(5, 20),
                    )
                else:
                    await ctx.send(random_lose_message(question["answer"]))

            except asyncio.TimeoutError:
                select.disabled = True
                await message.edit(view=view)
                await ctx.send(f"<:TIME:1415961777912545341> Time's up! The correct answer was `{question['answer']}`.")

        await ctx.send(f"🏁 Quiz finished! You scored **{score}/{num_questions}**.")

    @commands.hybrid_command(name="guesscharacter", description="Guess a random popular anime character")
    @commands.guild_only()
    async def guesscharacter(self, ctx):
        try:
            character = await fetch_random_character(prefer="AniList")
        except Exception:
            return await ctx.send("❌ Couldn't fetch characters from any API. Please try again later.")

        correct_name = character["name"]
        image = character["image"]
        anime_title = character["anime"]
        source = character["source"]

        try:
            options_list = await build_character_select_options(correct_name, source)
        except Exception:
            return await ctx.send("❌ Failed to fetch options for the quiz. Please try again.")

        embed = discord.Embed(title="Guess the character!", description=f"From **{anime_title}**")
        embed.set_image(url=image)
        embed.set_footer(text=f"Source: {source}")

        view = discord.ui.View(timeout=60)
        view.correct_answer = correct_name
        view.anime_title = anime_title
        view.author_id = ctx.author.id

        select = discord.ui.Select(placeholder="Choose the correct character...", options=options_list)
        view.add_item(select)

        message = await ctx.send(embed=embed, view=view)

        select.callback = self.create_select_callback(view, message)

    def create_select_callback(self, view, message):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != view.author_id:
                await interaction.response.send_message("This is not your game!", ephemeral=True)
                return
            selected = interaction.data["values"][0]
            correct_name = view.correct_answer
            anime_title = view.anime_title

            if selected == correct_name:
                async def send_interaction(msg: str):
                    await interaction.response.send_message(msg)
                await self._handle_correct_answer(
                    interaction.user.id,
                    interaction.guild.id,
                    send_interaction,
                    exp_mul=(2, 3),
                    exp_base=(5, 10),
                    coin_range=(15, 30),
                )
            else:
                await interaction.response.send_message(random_lose_message(correct_name, anime_title))

            for item in view.children:
                if isinstance(item, discord.ui.Select):
                    item.disabled = True
            await message.edit(view=view)
        return callback

async def setup(bot):
    await bot.add_cog(Games(bot))
    print("📦 Loaded games cog.")