"""Reward handling shared by game interactions."""

from collections.abc import Awaitable, Callable

from discord.ext import commands

from bot.utils.game_texts import (
    award_rewards,
    compute_rewards,
    random_win_message,
)

SendFunction = Callable[[str], Awaitable[object]]


class GameRewardService:
    """Calculate and award progression rewards for correct game answers."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def handle_correct_answer(
        self,
        user_id: int,
        guild_id: int,
        send_fn: SendFunction,
        *,
        exp_mul: tuple[int, int] = (2, 3),
        exp_base: tuple[int, int] = (5, 10),
        coin_range: tuple[int, int] = (15, 30),
    ) -> None:
        """Award rewards and send the resulting success message."""
        progression = self.bot.get_cog("Progression")

        if progression is None:
            await send_fn("✅ Correct!")
            return

        user_state = await progression.get_user(
            user_id,
            guild_id,
        )
        current_level = int(user_state[1]) if user_state else 1

        exp_reward, coin_reward = compute_rewards(
            level=current_level,
            exp_mul=exp_mul,
            exp_base=exp_base,
            coin_range=coin_range,
        )

        await award_rewards(
            progression,
            user_id,
            guild_id,
            exp_reward,
            coin_reward,
        )
        await send_fn(
            random_win_message(
                exp_reward,
                coin_reward,
            )
        )
