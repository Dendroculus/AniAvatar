import discord
from discord.ext import commands
from discord import app_commands
import random
import asyncio
import logging

from bot.features.games import JsonTriviaLoader, TriviaService
from bot.utils.anime_api import fetch_random_character, build_character_select_options
from bot.utils.game_texts import (
    random_win_message,
    random_lose_message,
    compute_rewards,
    award_rewards,
)
from bot.utils.discord_helpers import create_same_choices
from bot.config.emojis import CustomEmojis
from bot.config.paths import DATA_PATH

logger = logging.getLogger(__name__)


"""
games.py

Purpose:
- Provide lightweight, user-facing game commands such as trivia quizzes and
  character-guessing games. These commands are intentionally ephemeral and
  self-contained; they reward users via the Progression cog when appropriate.

Design notes (important):
- Concurrency and UX:
  - Per-question interaction handlers use a short timeout (15s) and a per-message
    discord.ui.View with a Select component; this keeps individual question state
    isolated to a single message and prevents cross-talk between concurrent games.
  - create_select_callback returns a coroutine function that closes over per-game
    state (view and message) so multiple games can run concurrently without
    interfering with each other.
- Rewarding:
  - Reward amounts are computed using helper utilities (compute_rewards / award_rewards)
    to centralize leveling/economy rules in one place.
  - The code checks for the Progression cog before attempting to award to avoid
    hard failures when the progression subsystem is not loaded.
- Data resilience (Refactored):
  - Trivia loading is abstracted behind a TriviaLoader interface.
  - JsonTriviaLoader handles file I/O and structure normalization asynchronously.
"""

# --- Trivia Data Adapter Interface ---


# --- Games Cog ---


class Games(commands.Cog):
    """
    Games cog: trivia and character-guessing interactions.

    Responsibilities:
    - Load trivia data asynchronously via TriviaLoader.
    - Present per-question UI, handle user answers, and reward correct responses.
    - Integrate with anime_api to provide image-based character guessing.
    """

    def __init__(self, bot):
        self.bot = bot

        trivia_path = DATA_PATH / "trivia.json"
        self.trivia_service = TriviaService(JsonTriviaLoader(trivia_path))

    async def cog_load(self):
        """
        Asynchronously load trivia data using the configured loader.
        """
        total_questions = await self.trivia_service.load()
        logger.info(
            "Loaded %d trivia questions.",
            total_questions,
        )

    def get_balanced_questions(
        self,
        num_questions: int,
    ):
        """Delegate balanced question selection to the trivia service."""
        return self.trivia_service.get_balanced_questions(num_questions)

    async def _handle_correct_answer(
        self,
        user_id: int,
        guild_id: int,
        send_fn,
        *,
        exp_mul=(2, 3),
        exp_base=(5, 10),
        coin_range=(15, 30),
    ):
        """
        Handle awarding rewards for a correct answer.

        Parameters:
        - user_id, guild_id: identity for awarding.
        - send_fn: a callable used to deliver text feedback (ctx.send or interaction.response.send_message).
        - exp_mul, exp_base, coin_range: parameters passed to compute_rewards.
        """
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

    @commands.hybrid_command(
        name="animequiz", description="Start an anime trivia quiz."
    )
    @commands.guild_only()
    @app_commands.describe(questions="Number of questions")
    @app_commands.choices(questions=create_same_choices([5, 10, 15, 20]))
    async def animequiz(self, ctx, questions: app_commands.Choice[int]):
        """
        Run a sequential trivia quiz presented question-by-question.

        Args:
            questions (int): The number of questions to ask (5, 10, 15, 20).
        """
        num_questions = questions.value
        quiz_questions = self.get_balanced_questions(num_questions)

        if not quiz_questions:
            return await ctx.send("❌ No trivia questions available.")

        score = 0

        for idx, question in enumerate(quiz_questions, 1):
            options_list = list(question["options"])
            random.shuffle(options_list)
            options = [
                discord.SelectOption(label=opt, value=opt) for opt in options_list
            ]

            embed = discord.Embed(
                title=f"Question {idx}/{num_questions}",
                description=question["question"],
            )
            view = discord.ui.View()
            future = asyncio.get_event_loop().create_future()

            select = discord.ui.Select(
                placeholder="Choose an answer...", options=options
            )
            view.add_item(select)

            async def callback(
                interaction: discord.Interaction,
                _future=future,
                _select=select,
                _view=view,
            ):
                # Only allow the quiz invoker to answer this question.
                if interaction.user != ctx.author:
                    await interaction.response.send_message(
                        "This is not your game!", ephemeral=True
                    )
                    return
                if not _future.done():
                    _future.set_result(interaction.data["values"][0])
                _select.disabled = True
                await interaction.response.edit_message(view=_view)

            select.callback = callback

            message = await ctx.send(embed=embed, view=view)

            try:
                selected = await asyncio.wait_for(future, timeout=15)

                if selected == question["answer"]:
                    score += 1

                    async def send_ctx(msg: str):
                        await ctx.send(msg)

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
                await ctx.send(
                    f"{CustomEmojis['TIME']} Time's up! The correct answer was `{question['answer']}`."
                )

        await ctx.send(f"🏁 Quiz finished! You scored **{score}/{num_questions}**.")

    @commands.hybrid_command(
        name="guesscharacter", description="Guess a random popular anime character"
    )
    @commands.guild_only()
    async def guesscharacter(self, ctx):
        """
        Image-based character guess game.

        Fetches a random character from AniList/Jikan and presents a
        multiple-choice menu with the correct name and randomized distractors.
        """
        try:
            # Need a session to pass to the API; get from bot
            if not self.bot.session:
                return await ctx.send("❌ Bot network session not initialized.")

            character = await fetch_random_character(
                session=self.bot.session, prefer="AniList"
            )
        except Exception as e:
            print(f"[Games] guesscharacter error: {e}")
            return await ctx.send(
                "❌ Couldn't fetch characters from any API. Please try again later."
            )

        correct_name = character["name"]
        image = character["image"]
        anime_title = character["anime"]
        source = character["source"]

        try:
            options_list = await build_character_select_options(
                correct_name, source, session=self.bot.session
            )
        except Exception:
            return await ctx.send(
                "❌ Failed to fetch options for the quiz. Please try again."
            )

        embed = discord.Embed(
            title="Guess the character!", description=f"From **{anime_title}**"
        )
        embed.set_image(url=image)
        embed.set_footer(text=f"Source: {source}")

        view = discord.ui.View(timeout=60)
        view.correct_answer = correct_name
        view.anime_title = anime_title
        view.author_id = ctx.author.id

        select = discord.ui.Select(
            placeholder="Choose the correct character...", options=options_list
        )
        view.add_item(select)

        message = await ctx.send(embed=embed, view=view)

        select.callback = self.create_select_callback(view, message)

    def create_select_callback(self, view, message):
        """
        Factory that creates a Select callback bound to the provided view and message.

        The returned coroutine:
        - Validates ownership (only the original invoker may answer).
        - Awards rewards on correct answers via _handle_correct_answer (uses an interaction-aware sender).
        - Disables the Select and updates the message view after an answer.
        """

        async def callback(interaction: discord.Interaction):
            if interaction.user.id != view.author_id:
                await interaction.response.send_message(
                    "This is not your game!", ephemeral=True
                )
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
                await interaction.response.send_message(
                    random_lose_message(correct_name, anime_title)
                )

            for item in view.children:
                if isinstance(item, discord.ui.Select):
                    item.disabled = True
            await message.edit(view=view)

        return callback


async def setup(bot):
    await bot.add_cog(Games(bot))
