"""Inventory item-use orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import discord

from bot.config.configs import (
    ProgressionConstants as PC,
    TradingConstants as TC,
)
from bot.features.trading.item_effects import ItemEffectService
from bot.services.trading_repository import TradingRepository
from bot.services.user_repository import UserRepository


InventoryUseStatus = Literal["success", "max_level", "missing"]


@dataclass(frozen=True)
class InventoryUseResult:
    """Outcome of one inventory item-use attempt."""

    status: InventoryUseStatus
    item_name: str
    emoji: str = ""
    exp_gain: int = 0
    extra_message: str = ""
    rewards: tuple[tuple[str, int, str], ...] = ()
    inventory: tuple[tuple[str, int, str], ...] = ()


class InventoryWorkflow:
    """Coordinate inventory validation, consumption, effects, and reload."""

    def __init__(
        self,
        *,
        user_repository: UserRepository,
        trading_repository: TradingRepository,
        item_effect_service: ItemEffectService,
    ) -> None:
        self.user_repository = user_repository
        self.trading_repository = trading_repository
        self.item_effect_service = item_effect_service

    async def use_item(
        self,
        *,
        user_id: int,
        guild_id: int,
        item_name: str,
        channel: discord.abc.Messageable | None,
    ) -> InventoryUseResult:
        """Use one item while preserving the existing operation order."""

        if item_name in TC.POTION_ITEMS:
            _, level = await self.user_repository.get_user(
                user_id,
                guild_id,
            )

            if level >= PC.MAX_LEVEL:
                return InventoryUseResult(
                    status="max_level",
                    item_name=item_name,
                )

        new_quantity = await self.trading_repository.use_item(
            user_id,
            guild_id,
            item_name,
        )

        if new_quantity is None:
            return InventoryUseResult(
                status="missing",
                item_name=item_name,
            )

        details = await self.trading_repository.get_item_details(
            item_name,
        )
        emoji = details["emoji"] if details else "📦"

        exp_gain = 0
        extra_message = ""
        rewards: list[tuple[str, int, str]] = []

        if item_name in TC.POTION_ITEMS:
            (
                exp_gain,
                extra_message,
            ) = await self.item_effect_service.apply_potion_effect(
                user_id,
                guild_id,
                item_name,
                channel,
            )

        elif item_name == TC.MYSTERY_BOX_NAME:
            raw_rewards = await self.item_effect_service.apply_mystery_box(
                user_id,
                guild_id,
            )

            for reward_name, reward_quantity in raw_rewards:
                reward_details = await self.trading_repository.get_item_details(
                    reward_name,
                )
                reward_emoji = reward_details["emoji"] if reward_details else "📦"
                rewards.append(
                    (
                        reward_name,
                        reward_quantity,
                        reward_emoji,
                    )
                )

        inventory = await self.trading_repository.get_user_inventory(
            user_id,
            guild_id,
        )

        return InventoryUseResult(
            status="success",
            item_name=item_name,
            emoji=emoji,
            exp_gain=exp_gain,
            extra_message=extra_message,
            rewards=tuple(rewards),
            inventory=tuple(inventory),
        )
