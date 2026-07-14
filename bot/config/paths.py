"""Canonical project and asset filesystem paths."""

from pathlib import Path


ROOT_PATH = Path(__file__).resolve().parents[2]
BOT_DIR = ROOT_PATH / "bot"
COG_DIR = BOT_DIR / "cogs"
ASSET_DIR = ROOT_PATH / "assets"
FONT_PATH = ASSET_DIR / "fonts"
RANK_ICON_PATH = ASSET_DIR / "RANK ICONS"
BACKGROUND_PATH = ASSET_DIR / "background"
ESSENTIAL_ICON_PATH = ASSET_DIR / "other essentials emojis"
SHOP_ASSET_PATH = ASSET_DIR / "shops"
DATA_PATH = ROOT_PATH / "data"
LOG_PATH = ROOT_PATH / "logs"

COG_PATH = str(COG_DIR)
FONT_DIR = str(FONT_PATH)
EMOJI_PATH = str(RANK_ICON_PATH)
BG_PATH = str(BACKGROUND_PATH)
