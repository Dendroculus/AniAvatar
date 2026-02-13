import random
import asyncio
from typing import Dict, List, Optional
import aiohttp
import discord
from constants.configs import ExternalAPIs as EA
from constants.configs import AnimeAPIConstants as AC

"""
anime_api.py (Optimized)

Purpose:
- Helpers for fetching anime/character metadata (AniList/Jikan).
- Used by: cogs/games.py (trivia), cogs/search.py (metadata).
- Cleaned of old image-search logic.
"""

async def fetch_random_character(session: aiohttp.ClientSession, prefer: str = "AniList") -> Dict:
    """Used by games.py for guesscharacter command."""
    providers = [prefer, "Jikan" if prefer == "AniList" else "AniList"]
    last_err = None
    for provider in providers:
        try:
            async with asyncio.timeout(AC.TIMEOUT_SECONDS):
                if provider == "AniList":
                    data = await _fetch_anilist_character_random(session)
                    data["source"] = "AniList"
                    return data
                else:
                    data = await _fetch_jikan_character_random(session)
                    data["source"] = "Jikan (MAL)"
                    return data
        except Exception as e:
            last_err = e
            continue
    raise last_err or RuntimeError("Failed to fetch character from providers")

async def _fetch_anilist_character_random(session: aiohttp.ClientSession) -> Dict:
    query = '''
    query ($page: Int, $perPage: Int) {
        Page(page: $page, perPage: $perPage) {
            characters(sort: FAVOURITES_DESC) {
                id
                name { full }
                image { large }
                media { nodes { title { romaji } } }
            }
        }
    }
    '''
    variables = {"page": random.randint(1, 20), "perPage": 50}
    
    async with session.post(EA.ANILIST_API, json={"query": query, "variables": variables}) as resp:
        resp.raise_for_status()
        payload = await resp.json()

    chars = payload.get("data", {}).get("Page", {}).get("characters", [])
    if not chars:
        raise RuntimeError("AniList: no characters")
    ch = random.choice(chars)
    nodes = ch.get("media", {}).get("nodes", [])
    anime_title = nodes[0]["title"]["romaji"] if nodes else "Unknown Anime"
    return {"name": ch["name"]["full"], "image": ch["image"]["large"], "anime": anime_title}

async def _fetch_jikan_character_random(session: aiohttp.ClientSession) -> Dict:
    page = random.randint(1, 10)
    url = f"{EA.JIKAN_TOP_CHAR_URL}?page={page}"
    
    async with session.get(url) as resp:
        resp.raise_for_status()
        payload = await resp.json()
    
    chars = payload.get("data", [])
    if not chars:
        raise RuntimeError("Jikan: no characters")
    ch = random.choice(chars)
    anime_nodes = ch.get("anime", [])
    anime_title = (anime_nodes[0]["title"] if anime_nodes else "Unknown Anime")
    return {"name": ch["name"], "image": ch["images"]["jpg"]["image_url"], "anime": anime_title}

async def fetch_character_by_name(name: str, session: aiohttp.ClientSession, prefer: str = "AniList") -> Optional[Dict]:
    """Used by search.py validation."""
    providers = [prefer, "Jikan" if prefer == "AniList" else "AniList"]
    for prov in providers:
        try:
            async with asyncio.timeout(AC.TIMEOUT_SECONDS):
                if prov == "AniList":
                    char = await _fetch_anilist_character_by_name(name, session)
                    if char:
                        char["source"] = "AniList"
                        return char
                else:
                    char = await _fetch_jikan_character_by_name(name, session)
                    if char:
                        char["source"] = "Jikan (MAL)"
                        return char
        except Exception:
            continue
    return None

async def _fetch_anilist_character_by_name(name: str, session: aiohttp.ClientSession) -> Optional[Dict]:
    query = """
    query ($search: String) {
        Character(search: $search) {
            id
            name { full }
            image { large medium }
            media { nodes { id type format } }
        }
    }"""
    variables = {"search": name}

    try:
        async with session.post(EA.ANILIST_API, json={"query": query, "variables": variables}) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
        ch = (data.get("data") or {}).get("Character")
        return ch or None
    except Exception:
        return None

async def _fetch_jikan_character_by_name(name: str, session: aiohttp.ClientSession) -> Optional[Dict]:
    from urllib.parse import quote
    url = f"{EA.JIKAN_SEARCH_CHAR_URL}?q={quote(name)}&limit=1"

    try:
        async with session.get(url) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
        results = data.get("data") or []
        if not results:
            return None
        c = results[0]
        img = (c.get("images") or {}).get("jpg", {}).get("image_url")
        return {
            "id": c.get("mal_id"),
            "name": {"full": c.get("name")},
            "image": {"large": img, "medium": img},
        }
    except Exception:
        return None

async def search_anime(session: aiohttp.ClientSession, query: str) -> List[Dict]:
    """Used by search.py for /anime command."""
    query_str = """
    query ($search: String) {
    Page(perPage: 5) {
        media(search: $search, type: ANIME) {
        id
        title { romaji english native }
        description(asHtml: false)
        episodes
        status
        duration
        startDate { year month day }
        endDate { year month day }
        season
        averageScore
        popularity
        favourites
        format
        source
        studios(isMain: true) { nodes { name } }
        genres
        coverImage { large medium }
        bannerImage
        siteUrl
        }
    }
    }
    """
    variables = {"search": query}

    try:
        async with asyncio.timeout(AC.TIMEOUT_SECONDS):
            async with session.post(EA.ANILIST_API, json={"query": query_str, "variables": variables}) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
            return data.get("data", {}).get("Page", {}).get("media", [])
    except Exception:
        return []

async def search_characters(session: aiohttp.ClientSession, name: str) -> List[Dict]:
    query_str = """
    query ($search: String) {
        Page(perPage: 5) {
            characters(search: $search) {
                id
                name { full native alternative }
                image { large medium }
                media(type: ANIME, perPage: 1) {
                    nodes { id type }
                }
            }
        }
    }
    """
    variables = {"search": name}

    try:
        async with asyncio.timeout(AC.TIMEOUT_SECONDS):
            async with session.post(EA.ANILIST_API, json={"query": query_str, "variables": variables}) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
            return data.get("data", {}).get("Page", {}).get("characters", [])
    except Exception:
        return []

def char_has_anime_media(char_obj: Optional[Dict]) -> bool:
    if not char_obj:
        return False
    media = char_obj.get("media") or {}
    nodes = media.get("nodes") or []
    for n in nodes:
        if (n.get("type") or "").upper() == "ANIME":
            return True
    return False

async def get_wrong_names(source: str, correct_name: str, session: aiohttp.ClientSession) -> List[str]:
    """Used by games.py to generate wrong answers."""
    try:
        async with asyncio.timeout(AC.TIMEOUT_SECONDS):
            if source == "AniList":
                return await _get_anilist_wrong_options(correct_name, session)
            else:
                return await _get_jikan_wrong_options(correct_name, session)
    except Exception:
        return get_fallback_wrong_options(correct_name)

def get_fallback_wrong_options(correct_name: str, pool: Optional[List[str]] = None) -> List[str]:
    names = [n for n in (pool or AC.FALLBACK_NAMES) if n != correct_name]
    k = min(3, len(names))
    return random.sample(names, k=k) if k > 0 else []

async def _get_anilist_wrong_options(correct_name: str, session: aiohttp.ClientSession) -> List[str]:
    query = '''
    query ($page: Int, $perPage: Int) {
        Page(page: $page, perPage: $perPage) {
            characters(sort: FAVOURITES_DESC) { name { full } }
        }
    }
    '''
    variables = {"page": random.randint(1, 20), "perPage": 50}

    async with session.post(EA.ANILIST_API, json={"query": query, "variables": variables}) as resp:
        if resp.status != 200:
            return get_fallback_wrong_options(correct_name)
        payload = await resp.json()

    chars = payload.get("data", {}).get("Page", {}).get("characters", [])
    wrong = [c["name"]["full"] for c in chars if c["name"]["full"] != correct_name]
    k = min(3, len(wrong))
    return random.sample(wrong, k=k) if k > 0 else get_fallback_wrong_options(correct_name)

async def _get_jikan_wrong_options(correct_name: str, session: aiohttp.ClientSession) -> List[str]:
    page = random.randint(1, 10)
    url = f"{EA.JIKAN_TOP_CHAR_URL}?page={page}"

    async with session.get(url) as resp:
        if resp.status != 200:
            return get_fallback_wrong_options(correct_name)
        payload = await resp.json()

    chars = payload.get("data", [])
    wrong = [c["name"] for c in chars if c["name"] != correct_name]
    k = min(3, len(wrong))
    return random.sample(wrong, k=k) if k > 0 else get_fallback_wrong_options(correct_name)

async def build_character_select_options(correct_name: str, source: str, session: aiohttp.ClientSession) -> List[discord.SelectOption]:
    """Used by games.py to build UI."""
    opts = [correct_name]
    wrong = await get_wrong_names(source, correct_name, session)
    opts.extend(wrong)
    random.shuffle(opts)
    return [discord.SelectOption(label=o, value=o) for o in opts]