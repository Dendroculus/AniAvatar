"""Canonical project and asset filesystem paths."""

from __future__ import annotations

import os
from pathlib import Path


ROOT_PATH = Path(__file__).resolve().parents[2]
BOT_DIR = ROOT_PATH / "bot"
COG_DIR = BOT_DIR / "cogs"


def _resolve_asset_root() -> Path:
    """Resolve bundled or externally mounted application assets."""
    configured = os.getenv("ASSET_ROOT", "").strip()

    if not configured:
        return ROOT_PATH / "assets"

    candidate = Path(configured).expanduser()

    if not candidate.is_absolute():
        candidate = ROOT_PATH / candidate

    return candidate.resolve()


ASSET_DIR = _resolve_asset_root()
FONT_PATH = ASSET_DIR / "fonts"
RANK_ICON_PATH = ASSET_DIR / "rank_icons"
BACKGROUND_PATH = ASSET_DIR / "backgrounds"
ESSENTIAL_ICON_PATH = ASSET_DIR / "essential_icons"
SHOP_ASSET_PATH = ASSET_DIR / "shop"
DATA_PATH = ROOT_PATH / "data"
LOG_PATH = ROOT_PATH / "logs"

COG_PATH = str(COG_DIR)
FONT_DIR = str(FONT_PATH)
EMOJI_PATH = str(RANK_ICON_PATH)
BG_PATH = str(BACKGROUND_PATH)
