"""Anime character provider helpers for AniList and Jikan."""

import asyncio
import random
from typing import Dict, Optional

import aiohttp

from bot.config.configs import AnimeAPIConstants as AC
from bot.config.configs import ExternalAPIs as EA


async def fetch_random_character(
    session: aiohttp.ClientSession, prefer: str = "AniList"
) -> Dict:
    """
    Fetch a random popular character from either AniList or Jikan.

    Args:
        session: Shared aiohttp.ClientSession for requests.
        prefer: provider preference string, either "AniList" or "Jikan".

    Behavior:
    - Tries the preferred provider first, falls back to the other provider on error.
    - On success returns a dict including keys: "name", "image", "anime", and sets
      a 'source' key on the returned dict before returning to the caller.
    """
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
    """
    Query AniList for a page of popular characters then pick a random entry.
    """
    query = """
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
    """
    variables = {"page": random.randint(1, 20), "perPage": 50}

    async with session.post(
        EA.ANILIST_API, json={"query": query, "variables": variables}
    ) as resp:
        resp.raise_for_status()
        payload = await resp.json()

    chars = payload.get("data", {}).get("Page", {}).get("characters", [])
    if not chars:
        raise RuntimeError("AniList: no characters")
    ch = random.choice(chars)
    nodes = ch.get("media", {}).get("nodes", [])
    anime_title = nodes[0]["title"]["romaji"] if nodes else "Unknown Anime"
    return {
        "name": ch["name"]["full"],
        "image": ch["image"]["large"],
        "anime": anime_title,
    }


async def _fetch_jikan_character_random(session: aiohttp.ClientSession) -> Dict:
    """
    Query Jikan (MAL) top characters endpoint, page-randomized, and return a random result.
    """
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
    anime_title = anime_nodes[0]["title"] if anime_nodes else "Unknown Anime"
    return {
        "name": ch["name"],
        "image": ch["images"]["jpg"]["image_url"],
        "anime": anime_title,
    }


async def fetch_character_by_name(
    name: str, session: aiohttp.ClientSession, prefer: str = "AniList"
) -> Optional[Dict]:
    """
    Fetch a character by name using AniList first (by default) then Jikan as fallback.
    """
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


async def _fetch_anilist_character_by_name(
    name: str, session: aiohttp.ClientSession
) -> Optional[Dict]:
    """
    Query AniList Character(search: ...) and return the raw character payload.

    UPDATED: We explicitly request 'media(type: ANIME, sort: POPULARITY_DESC)' to ensure
    characters with mixed media (like vocaloids) return their anime entries first.
    """
    query = """
    query ($search: String) {
        Character(search: $search) {
            id
            name { full }
            image { large medium }
            media(sort: POPULARITY_DESC, perPage: 5) { 
                nodes { id type format } 
            }
        }
    }"""
    variables = {"search": name}

    try:
        async with session.post(
            EA.ANILIST_API, json={"query": query, "variables": variables}
        ) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
        ch = (data.get("data") or {}).get("Character")
        return ch or None
    except Exception:
        return None


async def _fetch_jikan_character_by_name(
    name: str, session: aiohttp.ClientSession
) -> Optional[Dict]:
    """
    Query Jikan character search endpoint and convert result to a shape compatible with
    the AniList-oriented consumer code.
    """
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


def char_has_anime_media(char_obj: Optional[Dict]) -> bool:
    """
    Determine if the provided character object has at least one associated ANIME media node.
    """
    if not char_obj:
        return False

    # If the object exists and has a name, it's a valid character result.
    # We trust AniList's search relevance.
    if char_obj.get("name"):
        return True

    return False
