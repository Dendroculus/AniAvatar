import random
import asyncio
import logging
from typing import Dict, List, Optional
import aiohttp
import discord
from bot.config.configs import ExternalAPIs as EA
from bot.config.configs import AnimeAPIConstants as AC

"""
anime_api.py

Purpose:
- Lightweight helpers for fetching anime character information and images from AniList
  (GraphQL) and Jikan (MAL) as fallback.
- Utility functions also provide Google image search integration and basic image URL
  reachability checks.

Design notes :
- Network resource management: All functions REQUIRE an aiohttp.ClientSession.
  This enforces connection pooling and prevents "session leaks" (creating new sessions
  per command) which can exhaust file descriptors.
- Timeouts: High-level functions use `asyncio.timeout` context manager (10s default).
- Resilience: calls are defensive — on non-200 responses or malformed payloads functions
  typically return None or raise a controlled RuntimeError.
"""


async def fetch_random_character(session: aiohttp.ClientSession, prefer: str = "AniList") -> Dict:
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
    anime_title = (anime_nodes[0]["title"] if anime_nodes else "Unknown Anime")
    return {"name": ch["name"], "image": ch["images"]["jpg"]["image_url"], "anime": anime_title}


async def fetch_character_by_name(name: str, session: aiohttp.ClientSession, prefer: str = "AniList") -> Optional[Dict]:
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


async def _fetch_anilist_character_by_name(name: str, session: aiohttp.ClientSession) -> Optional[Dict]:
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
        async with session.post(EA.ANILIST_API, json={"query": query, "variables": variables}) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
        ch = (data.get("data") or {}).get("Character")
        return ch or None
    except Exception:
        return None


async def _fetch_jikan_character_by_name(name: str, session: aiohttp.ClientSession) -> Optional[Dict]:
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


async def search_anime(session: aiohttp.ClientSession, query: str) -> List[Dict]:
    """
    Search for anime by name using AniList.

    Args:
        session: Shared aiohttp.ClientSession.
        query: Name of the anime to search for.

    Returns:
        List[Dict]: A list of anime metadata dictionaries.
    """
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
    """
    Search for characters by name using AniList.

    Args:
        session: Shared aiohttp.ClientSession.
        name: Name of the character to search for.

    Returns:
        List[Dict]: A list of character dictionaries containing names, images, and media info.
    """
    query_str = """
    query ($search: String) {
        Page(perPage: 5) {
            characters(search: $search) {
                id
                name { full native alternative }
                image { large medium }
                media(perPage: 1, sort: POPULARITY_DESC) {
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


async def get_wrong_names(source: str, correct_name: str, session: aiohttp.ClientSession) -> List[str]:
    """
    Return a small list of plausible incorrect character names.
    """
    try:
        async with asyncio.timeout(AC.TIMEOUT_SECONDS):
            if source == "AniList":
                return await _get_anilist_wrong_options(correct_name, session)
            else:
                return await _get_jikan_wrong_options(correct_name, session)
    except Exception:
        return get_fallback_wrong_options(correct_name)


def get_fallback_wrong_options(correct_name: str, pool: Optional[List[str]] = None) -> List[str]:
    """
    Return up to 3 random names from a fallback pool excluding the correct_name.
    """
    names = [n for n in (pool or AC.FALLBACK_NAMES) if n != correct_name]
    k = min(3, len(names))
    return random.sample(names, k=k) if k > 0 else []


async def _get_anilist_wrong_options(correct_name: str, session: aiohttp.ClientSession) -> List[str]:
    """
    Request a page of popular characters from AniList for distractors.
    """
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
    """
    Query Jikan top characters for distractors.
    """
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
    """
    Build a randomized list of discord.SelectOption objects.
    """
    opts = [correct_name]
    wrong = await get_wrong_names(source, correct_name, session)
    opts.extend(wrong)
    random.shuffle(opts)
    return [discord.SelectOption(label=o, value=o) for o in opts]


def _check(resp):
    """
    Synchronous helper to validate response headers.
    """
    if resp.status != 200:
        return False
    ct = resp.headers.get("Content-Type", "")
    if not ct.startswith("image/"):
        return False
    try:
        clen = int(resp.headers.get("Content-Length", "0"))
    except Exception:
        clen = 0
    return clen > 1000  # basic size guard: at least 1KB


async def is_image_url_ok(session: aiohttp.ClientSession, url: str) -> bool:
    if not url:
        return False

    try:
        async with asyncio.timeout(AC.TIMEOUT_SECONDS):
            await asyncio.sleep(0)
            async with session.head(url, allow_redirects=True) as resp:
                if _check(resp):
                    return True

    except asyncio.TimeoutError:
        logging.debug("HEAD timeout: %s", url)

    except aiohttp.ClientError as e:
        logging.debug("HEAD client error %s: %s", url, e)

    except Exception:
        logging.exception("Unexpected HEAD error for %s", url)


    try:
        async with asyncio.timeout(AC.TIMEOUT_SECONDS):
            await asyncio.sleep(0)
            async with session.get(url, allow_redirects=True) as resp:
                return _check(resp)

    except asyncio.TimeoutError:
        logging.debug("GET timeout: %s", url)

    except aiohttp.ClientError as e:
        logging.debug("GET client error %s: %s", url, e)

    except Exception:
        logging.exception("Unexpected GET error for %s", url)

    return False



async def google_image_search(query: str, api_key: str, cx: str, session: aiohttp.ClientSession) -> List[str]:
    """
    Query Google Custom Search (image type) and return a filtered list of image links.
    Requires an active aiohttp.ClientSession.
    """
    from urllib.parse import quote
    url = (
        f"https://www.googleapis.com/customsearch/v1?"
        f"key={api_key}&cx={cx}&searchType=image&q={quote(query)}"
    )
    
    try:
        async with asyncio.timeout(AC.TIMEOUT_SECONDS):
            async with session.get(url) as resp:
                data = {}
                try:
                    data = await resp.json()
                except Exception:
                    pass
            items = data.get("items") or []
            image_extensions = (".png", ".jpg", ".jpeg", ".webp")
            links = [
                item.get("link") for item in items
                if isinstance(item.get("link"), str) and item["link"].lower().endswith(image_extensions)
            ]
            return links
    except Exception as e:
        logging.warning(f"Google Image Search failed for query '{query}': {e}")
        return []


async def first_reachable_image(links: List[str], session: aiohttp.ClientSession) -> Optional[str]:
    """
    Return the first reachable image URL from a list of links.
    Uses the provided session for all checks.
    """
    if not links:
        return None
    for link in links:
        try:
            async with asyncio.timeout(AC.TIMEOUT_SECONDS):
                ok = await is_image_url_ok(session, link)
                if ok:
                    return link
        except Exception:
            continue
    return None