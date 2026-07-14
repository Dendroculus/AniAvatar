"""Transactional item donation workflow."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from bot.config.configs import TradingConstants as TC


@dataclass(slots=True, frozen=True)
class DonationTransferResult:
    """Result returned after attempting an item transfer."""

    success: bool


class DonationService:
    """Transfer inventory items and enforce donation cooldowns."""

    def __init__(
        self,
        *,
        pool: Any,
        cooldown: timedelta = timedelta(hours=2),
        statement_timeout_ms: int = TC.STMT_TIMEOUT_MS,
    ) -> None:
        self.pool = pool
        self.cooldown = cooldown
        self.statement_timeout_ms = statement_timeout_ms
        self._cooldowns: dict[int, datetime] = {}

    def remaining_cooldown(
        self,
        donor_id: int,
    ) -> timedelta | None:
        """Return the active cooldown or remove it when expired."""
        expires_at = self._cooldowns.get(donor_id)

        if expires_at is None:
            return None

        now = datetime.now(timezone.utc)

        if now >= expires_at:
            self._cooldowns.pop(
                donor_id,
                None,
            )
            return None

        return expires_at - now

    async def transfer_item(
        self,
        *,
        donor_id: int,
        receiver_id: int,
        guild_id: int,
        item_name: str,
        amount: int,
    ) -> DonationTransferResult:
        """Atomically transfer an inventory item."""
        if amount <= 0:
            return DonationTransferResult(success=False)

        async with self.pool.acquire() as connection:
            async with connection.transaction():
                try:
                    await connection.execute(
                        "SET LOCAL statement_timeout = "
                        f"{int(self.statement_timeout_ms)}"
                    )
                except Exception:
                    pass

                row = await connection.fetchrow(
                    """
                    SELECT quantity
                    FROM user_inventory
                    WHERE user_id = $1
                      AND guild_id = $2
                      AND item_name = $3
                    FOR UPDATE
                    """,
                    donor_id,
                    guild_id,
                    item_name,
                )

                if not row or row["quantity"] < amount:
                    return DonationTransferResult(success=False)

                await connection.execute(
                    """
                    UPDATE user_inventory
                    SET quantity = quantity - $1
                    WHERE user_id = $2
                      AND guild_id = $3
                      AND item_name = $4
                    """,
                    amount,
                    donor_id,
                    guild_id,
                    item_name,
                )

                await connection.execute(
                    """
                    DELETE FROM user_inventory
                    WHERE user_id = $1
                      AND guild_id = $2
                      AND item_name = $3
                      AND quantity <= 0
                    """,
                    donor_id,
                    guild_id,
                    item_name,
                )

                await connection.execute(
                    """
                    INSERT INTO user_inventory (
                        user_id,
                        guild_id,
                        item_name,
                        quantity
                    )
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT (
                        user_id,
                        guild_id,
                        item_name
                    )
                    DO UPDATE SET
                        quantity = (
                            user_inventory.quantity
                            + EXCLUDED.quantity
                        )
                    """,
                    receiver_id,
                    guild_id,
                    item_name,
                    amount,
                )

        self._cooldowns[donor_id] = datetime.now(timezone.utc) + self.cooldown

        return DonationTransferResult(success=True)
