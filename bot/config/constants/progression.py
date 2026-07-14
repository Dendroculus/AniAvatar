"""Progression runtime limits and attachment conventions."""

from bot.config.emojis import ShopEmojis
from bot.config.settings import settings


class ProgressionConstants:
    @classmethod
    def coins_emoji(cls) -> str:
        return f"{ShopEmojis['Coins']}"

    PROFILE_PNG = "profile.png"
    ATTACHMENT_PROFILE = f"attachment://{PROFILE_PNG}"
    SQL_INSERT_OR_IGNORE_USER_COINS_ZERO = (
        "INSERT INTO user_coins (user_id, guild_id, coins) "
        "VALUES ($1, $2, 0) ON CONFLICT DO NOTHING"
    )
    DEFAULT_STATEMENT_TIMEOUT_MS = settings.pg_statement_timeout_ms
    MAX_LEVEL = 999
    MAX_NAME_WIDTH = 13
    RENDER_CACHE_SIZE = 200
    RENDER_CACHE_TTL = 300
    LEADERBOARD_CACHE_TTL = 120
