"""Backward-compatible configuration facade.

New code should import from settings, paths, assets, or constants directly.
"""

from .assets import AssetPaths, asset_catalog, resolve_background_path
from .constants import (
    AnimeAPIConstants,
    ExternalAPIs,
    FunConstants,
    PollingConstants,
    ProfileCardConstants,
    ProgressionConstants,
    RolesConstants,
    TradingConstants,
)
from .paths import BG_PATH, COG_PATH, EMOJI_PATH, FONT_DIR, ROOT_PATH
from .settings import (
    DATABASE,
    DISCORD_TOKEN,
    GOOGLE_API,
    GOOGLE_SEARCH_ENGINE,
    OWNER_ID,
    REDIS_CACHING,
    settings,
)

__all__ = [
    "AnimeAPIConstants",
    "AssetPaths",
    "BG_PATH",
    "COG_PATH",
    "DATABASE",
    "DISCORD_TOKEN",
    "EMOJI_PATH",
    "ExternalAPIs",
    "FONT_DIR",
    "FunConstants",
    "GOOGLE_API",
    "GOOGLE_SEARCH_ENGINE",
    "OWNER_ID",
    "PollingConstants",
    "ProfileCardConstants",
    "ProgressionConstants",
    "REDIS_CACHING",
    "ROOT_PATH",
    "RolesConstants",
    "TradingConstants",
    "asset_catalog",
    "resolve_background_path",
    "settings",
]
