import os
from dotenv import load_dotenv
from .emojis import CustomEmojis

ROOT_PATH = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) 
COG_PATH = os.path.join(ROOT_PATH, "cogs")  

FONT_DIR = os.path.join(ROOT_PATH, "assets", "fonts")
EMOJI_PATH = os.path.join(ROOT_PATH, "assets", "RANK ICONS")
BG_PATH = os.path.join(ROOT_PATH, "assets", "background")  # singular

"""
Load necessary environment variables
"""
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GOOGLE_API = os.getenv("GOOGLE_API_KEY")
GOOGLE_SEARCH_ENGINE = os.getenv("SEARCH_ENGINE_ID")
DATABASE = os.getenv("DATABASE_URL")
REDIS_CACHING = os.getenv("REDIS_URL")

""" External API Endpoints """
ANILIST_API = "https://graphql.anilist.co"

FONTS = {
    "bold": os.path.join(FONT_DIR, "gg sans Bold.ttf"),
    "medium": os.path.join(FONT_DIR, "gg sans Medium.ttf"),
    "regular": os.path.join(FONT_DIR, "gg sans Regular.ttf"),
    "semibold": os.path.join(FONT_DIR, "gg sans Semibold.ttf"),
    "cjk": os.path.join(FONT_DIR, "NotoSerifCJK.ttf"),
}

TITLE_EMOJI_FILES = {
    "Novice": os.path.join(EMOJI_PATH, "NOVICE.png"),
    "Warrior": os.path.join(EMOJI_PATH, "WARRIOR.png"),
    "Elite": os.path.join(EMOJI_PATH, "ELITE.png"),
    "Champion": os.path.join(EMOJI_PATH, "CHAMPION.png"),
    "Hero": os.path.join(EMOJI_PATH, "HERO.png"),
    "Legend": os.path.join(EMOJI_PATH, "LEGEND.png"),
    "Mythic": os.path.join(EMOJI_PATH, "MYTHIC.png"),
    "Ascendant": os.path.join(EMOJI_PATH, "ASCENDANT.png"),
    "Immortal": os.path.join(EMOJI_PATH, "IMMORTAL.png"),
    "Celestial": os.path.join(EMOJI_PATH, "CELESTIAL.png"),
    "Transcendent": os.path.join(EMOJI_PATH, "TRANSCENDENT.png"),
    "Aetherborn": os.path.join(EMOJI_PATH, "AETHERBORN.png"),
    "Cosmic": os.path.join(EMOJI_PATH, "COSMIC.png"),
    "Divine": os.path.join(EMOJI_PATH, "DIVINE.png"),
    "Eternal": os.path.join(EMOJI_PATH, "ETERNAL.png"),
    "Enlightened": os.path.join(EMOJI_PATH, "ENLIGHTENED.png"),
}
class TradingConstants:
    """
    Constants used in the Trading Cog for managing in-game item trading,
     including SQL statements and item definitions.
    """
    SHOP_ICON_URL = "https://cdn.discordapp.com/emojis/1415555390489366680.png"
    MYSTERY_BOX_NAME = "Mystery Box"
    SMALL_EXP_POTION = "Small EXP Potion"
    MEDIUM_EXP_POTION = "Medium EXP Potion"
    LARGE_EXP_POTION = "Large EXP Potion"
    LEVEL_SKIP_TOKEN = "Level Skip Token"
    EXP_EMOJI = f"{CustomEmojis['EXP']}"
    POTION_ITEMS = (SMALL_EXP_POTION, MEDIUM_EXP_POTION, LARGE_EXP_POTION, LEVEL_SKIP_TOKEN)
    SQL_USER_INV_SELECT = "SELECT item_name, quantity FROM user_inventory WHERE user_id = $1 AND guild_id = $2"
    SQL_UPSERT_USER_INV = """
    INSERT INTO user_inventory (user_id, guild_id, item_name, quantity)
    VALUES ($1, $2, $3, $4)
    ON CONFLICT(user_id, guild_id, item_name) DO UPDATE SET quantity = user_inventory.quantity + EXCLUDED.quantity
    """
    SQL_SELECT_PRICE_EMOJI = "SELECT price, emoji FROM shop_items WHERE name = $1"
