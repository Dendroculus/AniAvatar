import os
from dotenv import load_dotenv
from .emojis import ShopEmojis

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

class ExternalAPIs:
    """
    Constants for external API endpoints used in the bot.
    """
    ANILIST_API = "https://graphql.anilist.co"
    WAIFU_API = "https://api.waifu.pics/sfw/waifu"
    JIKAN_TOP_CHAR_URL = "https://api.jikan.moe/v4/top/characters"
    JIKAN_SEARCH_CHAR_URL = "https://api.jikan.moe/v4/characters"
    
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
    POTION_ITEMS = (SMALL_EXP_POTION, MEDIUM_EXP_POTION, LARGE_EXP_POTION, LEVEL_SKIP_TOKEN)
    STMT_TIMEOUT_MS = 2000
    MAINTENANCE_INTERVAL = 6 * 60 * 60  # 6 hours
    SQL_USER_INV_SELECT = "SELECT item_name, quantity FROM user_inventory WHERE user_id = $1 AND guild_id = $2"
    SQL_UPSERT_USER_INV = """
    INSERT INTO user_inventory (user_id, guild_id, item_name, quantity)
    VALUES ($1, $2, $3, $4)
    ON CONFLICT(user_id, guild_id, item_name) DO UPDATE SET quantity = user_inventory.quantity + EXCLUDED.quantity
    """
    SQL_SELECT_PRICE_EMOJI = "SELECT price, emoji FROM shop_items WHERE name = $1"

class ProgressionConstants:
    """
    Constants used in the Progression Cog for managing user progression,
     including SQL statements and rank definitions.
    """

    @classmethod # use as a method to avoid issues with ShopEmojis not being defined yet
    def COINS_EMOJI(cls):
        return f"{ShopEmojis['Coins']}"
    
    PROFILE_PNG = "profile.png"
    ATTACHMENT_PROFILE = f"attachment://{PROFILE_PNG}"
    SQL_INSERT_OR_IGNORE_USER_COINS_ZERO = (
        "INSERT INTO user_coins (user_id, guild_id, coins) VALUES ($1, $2, 0) ON CONFLICT DO NOTHING"
    )
    
    DEFAULT_STATEMENT_TIMEOUT_MS = int(os.getenv("PG_STATEMENT_TIMEOUT_MS", "2000"))
    MAX_LEVEL = 999
    MAX_NAME_WIDTH = 13
    RENDER_CACHE_SIZE = 200
    RENDER_CACHE_TTL = 300
    LEADERBOARD_CACHE_TTL = 120 # 2 minutes
    
class FunConstants:
    """
    Constants used in the Fun Cog for managing fun interactions.
    """
    FALSE_GAMBLE_SESSION = "⚠️ This is not your gamble session."
    GAMBLE_MAX_ATTEMPTS = 20
    GAMBLE_COOLDOWN_SECONDS = 5 * 60  # 5 minutes
    DEFAULT_WIN_PROBABILITY = 0.5 # 50% base chance to win
    
class RolesConstants:
    """
    Constants used in the Roles Cog for managing user roles.
    """
    TITLE_ORDER = [
        "Novice", "Warrior", "Elite", "Champion", "Hero", "Legend", "Mythic",
        "Ascendant", "Immortal", "Celestial", "Transcendent", "Aetherborn",
        "Cosmic", "Divine", "Eternal", "Enlightened"
    ]
    SYNC_INTERVAL_MINUTES = 720  # 12 hours

class PollingConstants:
    """
    Constants used in the Polling Cog for managing polling operations,
    including timeouts and placeholders.
    """
    MODAL_PLACEHOLDER = "Leave empty if not needed"
    SAFETY_TIMEOUT_MS = 2000 