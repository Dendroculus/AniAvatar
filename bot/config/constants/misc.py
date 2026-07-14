"""Constants for external APIs and smaller bot features."""

import aiohttp


class ExternalAPIs:
    ANILIST_API = "https://graphql.anilist.co"
    WAIFU_API = "https://api.waifu.im/images"
    JIKAN_TOP_CHAR_URL = "https://api.jikan.moe/v4/top/characters"
    JIKAN_SEARCH_CHAR_URL = "https://api.jikan.moe/v4/characters"


class FunConstants:
    FALSE_GAMBLE_SESSION = "⚠️ This is not your gamble session."
    GAMBLE_MAX_ATTEMPTS = 20
    GAMBLE_COOLDOWN_SECONDS = 5 * 60
    DEFAULT_WIN_PROBABILITY = 0.5


class RolesConstants:
    TITLE_ORDER = [
        "Novice",
        "Warrior",
        "Elite",
        "Champion",
        "Hero",
        "Legend",
        "Mythic",
        "Ascendant",
        "Immortal",
        "Celestial",
        "Transcendent",
        "Aetherborn",
        "Cosmic",
        "Divine",
        "Eternal",
        "Enlightened",
    ]
    SYNC_INTERVAL_MINUTES = 720


class PollingConstants:
    MODAL_PLACEHOLDER = "Leave empty if not needed"
    SAFETY_TIMEOUT_MS = 2000


class AnimeAPIConstants:
    TIMEOUT_SECONDS = 10
    DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=TIMEOUT_SECONDS)
    FALLBACK_NAMES = [
        "Naruto Uzumaki",
        "Monkey D. Luffy",
        "Goku",
        "Light Yagami",
        "Eren Yeager",
        "Levi Ackerman",
        "Saitama",
        "Edward Elric",
        "Spike Spiegel",
        "Lelouch Lamperouge",
        "Killua Zoldyck",
        "Gon Freecss",
    ]
