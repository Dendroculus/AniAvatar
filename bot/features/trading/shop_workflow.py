"""Shop loading and purchase orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from bot.features.trading.repository import TradingRepository
from bot.core.repositories.user_repository import UserRepository


ShopPurchaseStatus = Literal["success", "missing", "insufficient"]


@dataclass(frozen=True)
class ShopItem:
    """One item shown in the trading shop."""

    name: str
    price: int
    emoji: str


@dataclass(frozen=True)
class ShopState:
    """Current shop items and the requesting user's balance."""

    balance: int
    items: tuple[ShopItem, ...]


@dataclass(frozen=True)
class ShopPurchaseResult:
    """Outcome of one shop purchase attempt."""

    status: ShopPurchaseStatus
    item_name: str
    emoji: str = ""
    price: int = 0


class ShopPurchaseWorkflow:
    """Coordinate shop reads and purchases without Discord UI coupling."""

    def __init__(
        self,
        *,
        user_repository: UserRepository,
        trading_repository: TradingRepository,
    ) -> None:
        self.user_repository = user_repository
        self.trading_repository = trading_repository

    async def load_shop(
        self,
        *,
        user_id: int,
        guild_id: int,
    ) -> ShopState:
        """Load available items before resolving the user's balance."""

        rows = await self.trading_repository.get_shop_items()

        if not rows:
            return ShopState(
                balance=0,
                items=(),
            )

        balance = await self.user_repository.get_coins(
            user_id,
            guild_id,
        )

        items = tuple(
            ShopItem(
                name=row["name"],
                price=row["price"],
                emoji=row["emoji"],
            )
            for row in rows
        )

        return ShopState(
            balance=balance,
            items=items,
        )

    async def purchase(
        self,
        *,
        user_id: int,
        guild_id: int,
        item_name: str,
    ) -> ShopPurchaseResult:
        """Purchase one item while preserving the existing operation order."""

        details = await self.trading_repository.get_item_details(
            item_name,
        )

        if not details:
            return ShopPurchaseResult(
                status="missing",
                item_name=item_name,
            )

        price = details["price"]
        emoji = details["emoji"]

        coins = await self.user_repository.get_coins(
            user_id,
            guild_id,
        )

        if coins < price:
            return ShopPurchaseResult(
                status="insufficient",
                item_name=item_name,
                emoji=emoji,
                price=price,
            )

        removed = await self.user_repository.remove_coins(
            user_id,
            guild_id,
            price,
        )

        if not removed:
            return ShopPurchaseResult(
                status="insufficient",
                item_name=item_name,
                emoji=emoji,
                price=price,
            )

        await self.trading_repository.add_item(
            user_id,
            guild_id,
            item_name,
            1,
        )

        return ShopPurchaseResult(
            status="success",
            item_name=item_name,
            emoji=emoji,
            price=price,
        )
