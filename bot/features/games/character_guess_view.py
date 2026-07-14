"""Discord view for the character-guess game."""

from typing import Optional

import discord

from bot.utils.game_texts import random_lose_message

from .reward_service import GameRewardService


class CharacterGuessSelect(discord.ui.Select):
    """Select menu that forwards answers to its owning view."""

    def __init__(
        self,
        options: list[discord.SelectOption],
    ) -> None:
        super().__init__(
            placeholder="Choose the correct character...",
            options=options,
        )

    async def callback(
        self,
        interaction: discord.Interaction,
    ) -> None:
        view = self.view

        if isinstance(view, CharacterGuessView):
            await view.handle_selection(
                interaction,
                self.values[0],
            )


class CharacterGuessView(discord.ui.View):
    """Own character-game state and interaction handling."""

    def __init__(
        self,
        *,
        author_id: int,
        correct_answer: str,
        anime_title: str,
        options: list[discord.SelectOption],
        reward_service: GameRewardService,
        timeout: float = 60,
    ) -> None:
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.correct_answer = correct_answer
        self.anime_title = anime_title
        self.reward_service = reward_service
        self.message: Optional[discord.Message] = None
        self.add_item(CharacterGuessSelect(options))

    async def handle_selection(
        self,
        interaction: discord.Interaction,
        selected: str,
    ) -> None:
        """Validate the player, resolve the answer, and close the view."""
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "This is not your game!",
                ephemeral=True,
            )
            return

        if selected == self.correct_answer:

            async def send_result(
                content: str,
            ) -> object:
                await interaction.response.send_message(content)
                return interaction

            await self.reward_service.handle_correct_answer(
                interaction.user.id,
                interaction.guild.id,
                send_result,
                exp_mul=(2, 3),
                exp_base=(5, 10),
                coin_range=(15, 30),
            )
        else:
            await interaction.response.send_message(
                random_lose_message(
                    self.correct_answer,
                    self.anime_title,
                )
            )

        for item in self.children:
            if isinstance(item, discord.ui.Select):
                item.disabled = True

        if self.message is not None:
            await self.message.edit(view=self)

        self.stop()

    async def on_timeout(self) -> None:
        """Disable the select menu when the game expires."""
        for item in self.children:
            if isinstance(item, discord.ui.Select):
                item.disabled = True

        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass
