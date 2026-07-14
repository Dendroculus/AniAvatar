import logging

import discord
from discord import app_commands
from discord.ext import commands

from bot.config.paths import DATA_PATH
from bot.features.games import (
    CharacterGuessView,
    GameRewardService,
    JsonTriviaLoader,
    TriviaQuizRunner,
    TriviaService,
)
from bot.features.anime import (
    build_character_select_options,
    fetch_random_character,
)
from bot.core.discord.helpers import create_same_choices

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
  - Dedicated interaction components own per-game state so concurrent games remain
    isolated from one another.
- Rewarding:
  - GameRewardService centralizes reward calculation and progression updates.
  - The code checks for the Progression cog before attempting to award to avoid
    hard failures when the progression subsystem is not loaded.
- Data resilience (Refactored):
  - Trivia loading is abstracted behind a TriviaLoader interface.
  - JsonTriviaLoader handles file I/O and structure normalization asynchronously.
"""

# --- Games Cog ---


class Games(commands.Cog):
    """
    Games cog: trivia and character-guessing interactions.

    Responsibilities:
    - Load trivia data asynchronously via TriviaLoader.
    - Delegate trivia interactions to TriviaQuizRunner.
    - Build character games using CharacterGuessView.
    """

    def __init__(self, bot):
        self.bot = bot
        self.reward_service = GameRewardService(bot)
        self.trivia_runner = TriviaQuizRunner(self.reward_service)

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

    @commands.hybrid_command(
        name="animequiz",
        description="Start an anime trivia quiz.",
    )
    @commands.guild_only()
    @app_commands.describe(questions="Number of questions")
    @app_commands.choices(questions=create_same_choices([5, 10, 15, 20]))
    async def animequiz(
        self,
        ctx: commands.Context,
        questions: app_commands.Choice[int],
    ) -> None:
        """Run a sequential anime trivia quiz."""
        total_questions = questions.value
        quiz_questions = self.trivia_service.get_balanced_questions(total_questions)

        if not quiz_questions:
            await ctx.send("❌ No trivia questions available.")
            return

        await self.trivia_runner.run(
            ctx,
            quiz_questions,
            total_questions,
        )

    @commands.hybrid_command(
        name="guesscharacter",
        description=("Guess a random popular anime character"),
    )
    @commands.guild_only()
    async def guesscharacter(
        self,
        ctx: commands.Context,
    ) -> None:
        """Start an image-based character guessing game."""
        try:
            if not self.bot.session:
                await ctx.send("❌ Bot network session not initialized.")
                return

            character = await fetch_random_character(
                session=self.bot.session,
                prefer="AniList",
            )
        except Exception as error:
            print(f"[Games] guesscharacter error: {error}")
            await ctx.send(
                "❌ Couldn't fetch characters from any API. Please try again later."
            )
            return

        correct_name = character["name"]
        image = character["image"]
        anime_title = character["anime"]
        source = character["source"]

        try:
            options = await build_character_select_options(
                correct_name,
                source,
                session=self.bot.session,
            )
        except Exception:
            await ctx.send("❌ Failed to fetch options for the quiz. Please try again.")
            return

        embed = discord.Embed(
            title="Guess the character!",
            description=f"From **{anime_title}**",
        )
        embed.set_image(url=image)
        embed.set_footer(text=f"Source: {source}")

        view = CharacterGuessView(
            author_id=ctx.author.id,
            correct_answer=correct_name,
            anime_title=anime_title,
            options=options,
            reward_service=self.reward_service,
        )
        view.message = await ctx.send(
            embed=embed,
            view=view,
        )


async def setup(bot):
    await bot.add_cog(Games(bot))
