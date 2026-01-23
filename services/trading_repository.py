import asyncpg
from typing import List, Tuple, Optional
from constants.configs import TradingConstants as TC

"""
trading_repository.py

Data access layer for the Trading subsystem.
Handles schema initialization and CRUD operations for shop items and user inventory.
"""

class TradingRepository:
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def initialize_schema(self):
        """Initialize the database tables and indexes."""
        async with self.pool.acquire() as conn:
            await self._set_stmt_timeout(conn)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS shop_items (
                    id BIGSERIAL PRIMARY KEY,
                    name TEXT UNIQUE,
                    type TEXT,
                    price BIGINT,
                    emoji TEXT
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS user_inventory (
                    user_id BIGINT,
                    guild_id BIGINT,
                    item_name TEXT,
                    quantity BIGINT,
                    PRIMARY KEY(user_id, guild_id, item_name)
                )
            """)
            
            try:
                await conn.execute("CREATE INDEX IF NOT EXISTS user_inventory_guild_user_idx ON user_inventory (guild_id, user_id)")
                await conn.execute("CREATE INDEX IF NOT EXISTS user_inventory_guild_item_idx ON user_inventory (guild_id, item_name)")
            except Exception as e:
                print(f"[TradingRepository] Index creation warning: {e}")

    async def seed_default_items(self, items: List[Tuple[str, str, int, str]]):
        """Seed default shop items if they don't exist."""
        async with self.pool.acquire() as conn:
            await self._set_stmt_timeout(conn)
            for name, type_, price, emoji in items:
                await conn.execute(
                    "INSERT INTO shop_items (name, type, price, emoji) VALUES ($1, $2, $3, $4) ON CONFLICT (name) DO NOTHING",
                    name, type_, price, emoji
                )

    async def cleanup_zero_quantity_items(self):
        """Remove inventory rows with <= 0 quantity."""
        async with self.pool.acquire() as conn:
            await self._set_stmt_timeout(conn)
            await conn.execute("DELETE FROM user_inventory WHERE quantity <= 0")

    async def cleanup_guild_inventory(self, guild_id: int):
        """Remove all inventory items for a specific guild."""
        async with self.pool.acquire() as conn:
            await self._set_stmt_timeout(conn)
            await conn.execute("DELETE FROM user_inventory WHERE guild_id = $1", guild_id)

    async def get_shop_items(self) -> List[dict]:
        """Fetch all items available in the shop."""
        async with self.pool.acquire() as conn:
            await self._set_stmt_timeout(conn)
            return await conn.fetch("SELECT name, price, emoji FROM shop_items")

    async def get_item_details(self, item_name: str) -> Optional[dict]:
        """Fetch price and emoji for a specific item."""
        async with self.pool.acquire() as conn:
            await self._set_stmt_timeout(conn)
            return await conn.fetchrow("SELECT price, emoji FROM shop_items WHERE name = $1", item_name)

    async def get_user_inventory(self, user_id: int, guild_id: int) -> List[Tuple[str, int, str]]:
        """Fetch a user's inventory with emojis."""
        async with self.pool.acquire() as conn:
            await self._set_stmt_timeout(conn)
            rows = await conn.fetch(TC.SQL_USER_INV_SELECT, user_id, guild_id)
            
            results = []
            for name, qty in rows:
                if qty <= 0:
                    continue
                erow = await conn.fetchrow("SELECT emoji FROM shop_items WHERE name = $1", name)
                emoji = erow["emoji"] if erow else "📦"
                results.append((name, qty, emoji))
            return results

    async def add_item(self, user_id: int, guild_id: int, item_name: str, quantity: int):
        """Add items to a user's inventory."""
        async with self.pool.acquire() as conn:
            await self._set_stmt_timeout(conn)
            await conn.execute(TC.SQL_UPSERT_USER_INV, user_id, guild_id, item_name, quantity)

    async def use_item(self, user_id: int, guild_id: int, item_name: str) -> Optional[int]:
        """
        Decrement item quantity by 1. Returns the new quantity, or None if item not found/empty.
        Automatically cleans up if quantity reaches 0.
        """
        async with self.pool.acquire() as conn:
            await self._set_stmt_timeout(conn)
            async with conn.transaction():
                row = await conn.fetchrow(
                    """
                    UPDATE user_inventory
                    SET quantity = quantity - 1
                    WHERE user_id = $1 AND guild_id = $2 AND item_name = $3 AND quantity > 0
                    RETURNING quantity
                    """,
                    user_id, guild_id, item_name
                )
                
                if not row:
                    return None
                
                new_qty = row["quantity"]
                if new_qty <= 0:
                    await conn.execute(
                        "DELETE FROM user_inventory WHERE user_id = $1 AND guild_id = $2 AND item_name = $3",
                        user_id, guild_id, item_name
                    )
                
                return new_qty

    async def _set_stmt_timeout(self, conn):
        """Apply safety timeout to connection."""
        try:
            await conn.execute(f"SET LOCAL statement_timeout = {TC.STMT_TIMEOUT_MS}")
        except Exception:
            pass