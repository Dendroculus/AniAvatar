import asyncpg
from typing import List, Optional, Tuple
from constants.configs import  ProgressionConstants as PC
class UserRepository:
    """
    Repository layer for handling all database interactions regarding users,
    progression, economy, and themes.
    """
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def initialize_schema(self):
        """Initialize database tables and indexes."""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT,
                    guild_id BIGINT,
                    exp BIGINT NOT NULL DEFAULT 0,
                    level INTEGER NOT NULL DEFAULT 1,
                    PRIMARY KEY (user_id, guild_id)
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS profile_theme (
                    user_id BIGINT PRIMARY KEY,
                    theme_name TEXT DEFAULT 'default',
                    bg_file TEXT DEFAULT 'NULL',
                    font_color TEXT DEFAULT 'white'
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS user_coins (
                    user_id BIGINT,
                    guild_id BIGINT,
                    coins BIGINT DEFAULT 0,
                    PRIMARY KEY(user_id, guild_id)
                )
            """)
            try:
                await conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_users_guild_level_exp ON users (guild_id, level DESC, exp DESC)"
                )
            except Exception as e:
                print(f"[UserRepository] Index creation warning: {e}")

    async def delete_guild_data(self, guild_id: int):
        """Remove all user data for a specific guild."""
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM users WHERE guild_id = $1", guild_id)

    async def get_coins(self, user_id: int, guild_id: int) -> int:
        """Get the coin balance for a user."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT coins FROM user_coins WHERE user_id = $1 AND guild_id = $2",
                user_id, guild_id
            )
            if not row:
                await conn.execute(
                    "INSERT INTO user_coins (user_id, guild_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                    user_id, guild_id
                )
                return 0
            return int(row["coins"])

    async def add_coins(self, user_id: int, guild_id: int, amount: int):
        """Add coins to a user's balance."""
        if amount == 0:
            return
        async with self.pool.acquire() as conn:
            await conn.execute(PC.SQL_INSERT_OR_IGNORE_USER_COINS_ZERO, user_id, guild_id)
            await conn.execute(
                """
                INSERT INTO user_coins (user_id, guild_id, coins) VALUES ($1, $2, $3)
                ON CONFLICT(user_id, guild_id) DO UPDATE SET coins = user_coins.coins + EXCLUDED.coins
                """,
                user_id, guild_id, amount
            )

    async def ensure_user_row(self, user_id: int, guild_id: int):
        """Ensure a user exists in the coin database."""
        async with self.pool.acquire() as conn:
            await conn.execute(PC.SQL_INSERT_OR_IGNORE_USER_COINS_ZERO, user_id, guild_id)

    async def remove_coins(self, user_id: int, guild_id: int, amount: int) -> bool:
        """Remove coins from a user's balance safely."""
        if amount <= 0:
            return False
        async with self.pool.acquire() as conn:
            await conn.execute(PC.SQL_INSERT_OR_IGNORE_USER_COINS_ZERO, user_id, guild_id)
            result = await conn.execute(
                "UPDATE user_coins SET coins = coins - $1 WHERE user_id = $2 AND guild_id = $3 AND coins >= $1",
                amount, user_id, guild_id
            )
            try:
                updated = int(result.split()[-1])
            except Exception:
                updated = 0
            return updated > 0

    async def get_user_theme(self, user_id: int) -> Tuple[str, Optional[str], str]:
        """Get the user's profile theme configuration."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT theme_name, bg_file, font_color FROM profile_theme WHERE user_id = $1",
                user_id
            )
            if not row:
                await conn.execute(
                    "INSERT INTO profile_theme (user_id) VALUES ($1) ON CONFLICT DO NOTHING",
                    user_id
                )
                return "galaxy", "GALAXY.PNG", "white"
            return (row["theme_name"], row["bg_file"], row["font_color"])

    async def set_user_theme(self, user_id: int, theme_name: str, bg_file: Optional[str], font_color: str = "white"):
        """Update the user's profile theme configuration."""
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO profile_theme (user_id, theme_name, bg_file, font_color)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (user_id) DO UPDATE
                SET theme_name = EXCLUDED.theme_name,
                    bg_file = EXCLUDED.bg_file,
                    font_color = EXCLUDED.font_color
                """,
                user_id, theme_name, bg_file, font_color
            )

    async def get_user(self, user_id: int, guild_id: int) -> Tuple[int, int]:
        """Get user experience and level."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT exp, level FROM users WHERE user_id = $1 AND guild_id = $2",
                user_id, guild_id
            )
            if row is None:
                await conn.execute(
                    "INSERT INTO users (user_id, guild_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                    user_id, guild_id
                )
                return 0, 1
            return (row["exp"], row["level"])

    async def add_exp(self, user_id: int, guild_id: int, amount: int) -> Tuple[int, int, bool]:
        """Add experience points to a user and handle leveling up."""
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """
                    SELECT exp, level
                    FROM users
                    WHERE user_id = $1 AND guild_id = $2
                    FOR UPDATE
                    """,
                    user_id, guild_id,
                )

                if row is None:
                    await conn.execute(
                        """
                        INSERT INTO users (user_id, guild_id, exp, level)
                        VALUES ($1, $2, 0, 1)
                        ON CONFLICT DO NOTHING
                        """,
                        user_id, guild_id,
                    )
                    row = await conn.fetchrow(
                        """
                        SELECT exp, level
                        FROM users
                        WHERE user_id = $1 AND guild_id = $2
                        FOR UPDATE
                        """,
                        user_id, guild_id,
                    )

                exp, level = row["exp"], row["level"]
                new_exp = exp + amount
                leveled_up = False

                while level < PC.MAX_LEVEL:
                    next_exp = 50 * level + 20 * level**2
                    if new_exp >= next_exp:
                        new_exp -= next_exp
                        level += 1
                        leveled_up = True
                    else:
                        break

                if level >= PC.MAX_LEVEL:
                    level = PC.MAX_LEVEL
                    new_exp = 0

                await conn.execute(
                    """
                    UPDATE users
                    SET exp = $1, level = $2
                    WHERE user_id = $3 AND guild_id = $4
                    """,
                    new_exp, level, user_id, guild_id,
                )

                return level, new_exp, leveled_up

    async def get_rank(self, user_id: int, guild_id: int) -> int:
        """Get the user's rank position in the guild."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT COUNT(*) + 1 AS rnk
                FROM users
                WHERE guild_id = $1
                    AND (
                    level > (SELECT level FROM users WHERE user_id = $2 AND guild_id = $1)
                    OR (
                        level = (SELECT level FROM users WHERE user_id = $2 AND guild_id = $1)
                        AND exp > (SELECT exp FROM users WHERE user_id = $2 AND guild_id = $1)
                    )
                    )
                """,
                guild_id, user_id
            )
            return int(row["rnk"]) if row and row["rnk"] is not None else 1

    async def get_rank_for(self, guild_id: int, level: int, exp: int) -> int:
        """Calculate the rank for a hypothetical level and experience value."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT COUNT(*) + 1 AS rnk FROM users WHERE guild_id = $1 AND (level > $2 OR (level = $2 AND exp > $3))",
                guild_id, level, exp
            )
            return int(row["rnk"]) if row and row["rnk"] is not None else 1

    async def get_leaderboard_rows(self, guild_id: int, limit: int = 10) -> List[Tuple[int, int, int]]:
        """Fetch the top users for the leaderboard."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT user_id, level, exp
                FROM users
                WHERE guild_id = $1
                    AND ((exp > 0 AND level >= 1) OR level = $2)
                ORDER BY level DESC, exp DESC
                LIMIT $3
                """,
                guild_id, PC.MAX_LEVEL, limit
            )
            return [(r["user_id"], r["level"], r["exp"]) for r in rows]