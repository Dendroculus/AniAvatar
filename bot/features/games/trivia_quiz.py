"""Sequential Discord trivia interaction workflow."""

import asyncio
import random
from collections.abc import Sequence
from typing import Any

import discord
from discord.ext import commands

from bot.config.emojis import CustomEmojis
from bot.features.games.texts import random_lose_message

from .reward_service import GameRewardService


class TriviaQuizRunner:
    """Present trivia questions, collect answers, and award rewards."""

    def __init__(self, reward_service: GameRewardService):
        self.reward_service = reward_service

    async def run(
        self,
        ctx: commands.Context,
        questions: Sequence[dict[str, Any]],
        total_questions: int,
    ) -> None:
        """Run the complete sequential trivia interaction."""
        score = 0

        for index, question in enumerate(questions, 1):
            options_list = list(question["options"])
            random.shuffle(options_list)
            options = [
                discord.SelectOption(
                    label=option,
                    value=option,
                )
                for option in options_list
            ]

            embed = discord.Embed(
                title=f"Question {index}/{total_questions}",
                description=question["question"],
            )
            view = discord.ui.View()
            answer_future = asyncio.get_running_loop().create_future()

            select = discord.ui.Select(
                placeholder="Choose an answer...",
                options=options,
            )
            view.add_item(select)

            async def callback(
                interaction: discord.Interaction,
                _future=answer_future,
                _select=select,
                _view=view,
            ) -> None:
                if interaction.user != ctx.author:
                    await interaction.response.send_message(
                        "This is not your game!",
                        ephemeral=True,
                    )
                    return

                if not _future.done():
                    _future.set_result(interaction.data["values"][0])

                _select.disabled = True
                await interaction.response.edit_message(view=_view)

            select.callback = callback
            message = await ctx.send(
                embed=embed,
                view=view,
            )

            try:
                selected = await asyncio.wait_for(
                    answer_future,
                    timeout=15,
                )

                if selected == question["answer"]:
                    score += 1

                    async def send_result(
                        content: str,
                    ) -> object:
                        return await ctx.send(content)

                    await self.reward_service.handle_correct_answer(
                        ctx.author.id,
                        ctx.guild.id,
                        send_result,
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
                    f"{CustomEmojis['TIME']} Time's up! "
                    "The correct answer was "
                    f"`{question['answer']}`."
                )

        await ctx.send(f"🏁 Quiz finished! You scored **{score}/{total_questions}**.")
