import random
from typing import Dict, List, Optional
import aiohttp
import discord
from constants.configs import ExternalAPIs as EA

"""
anime_api.py

Purpose:
- Lightweight helpers for fetching anime character information and images from AniList
  (GraphQL) and Jikan (MAL) as fallback.
- Utility functions also provide Google image search integration and basic image URL
  reachability checks.

Design notes (important):
- Network resource management: many functions accept an optional aiohttp.ClientSession.
  When a session is not provided the function "owns" the session (creates and closes it).
  This behavior is explicit in functions using the local `owns` variable — callers can
  pass a shared session to avoid repeated connection setup and teardown.
- Timeouts: DEFAULT_TIMEOUT provides a conservative default (10s) for all external calls.
- Resilience: calls are defensive — on non-200 responses or malformed payloads functions
  typically return None or raise a controlled RuntimeError so callers can implement
  fallback logic without encountering unhandled exceptions.
- Return shapes:
  - AniList fetchers return dict shapes matching the fields requested from AniList.
  - Jikan fetchers return dicts shaped to be compatible with the AniList-oriented code
    that consumes them (e.g., 'image' subkeys 'large'/'medium').
- Google Custom Search: the google_image_search function filters results by common image
  extensions. This conservative filtering reduces false positives but may exclude valid
  images with unusual URLs.
"""

DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=10)

FALLBACK_NAMES = [
    "Naruto Uzumaki", "Monkey D. Luffy", "Goku", "Light Yagami", "Eren Yeager", "Levi Ackerman",
    "Saitama", "Edward Elric", "Spike Spiegel", "Lelouch Lamperouge", "Killua Zoldyck", "Gon Freecss"
]


async def fetch_random_character(prefer: str = "AniList", session: Optional[aiohttp.ClientSession] = None) -> Dict:
    """
    Fetch a random popular character from either AniList or Jikan.

    Args:
        prefer: provider preference string, either "AniList" or "Jikan".
        session: optional aiohttp.ClientSession to reuse resources; if None, the function
                 creates and closes its own session.

    Behavior:
    - Tries the preferred provider first, falls back to the other provider on error.
    - On success returns a dict including keys: "name", "image", "anime", and sets
      a 'source' key on the returned dict before returning to the caller.
    - On failure raises the last observed exception (or a RuntimeError if none captured).
    """
    providers = [prefer, "Jikan" if prefer == "AniList" else "AniList"]
    last_err = None
    for provider in providers:
        try:
            if provider == "AniList":
                data = await _fetch_anilist_character_random(session=session)
                data["source"] = "AniList"
                return data
            else:
                data = await _fetch_jikan_character_random(session=session)
                data["source"] = "Jikan (MAL)"
                return data
        except Exception as e:
            last_err = e
            continue
    raise last_err or RuntimeError("Failed to fetch character from providers")


async def _fetch_anilist_character_random(session: Optional[aiohttp.ClientSession] = None) -> Dict:
    """
    Query AniList for a page of popular characters then pick a random entry.

    - The GraphQL query requests characters sorted by favourites.
    - Pagination is randomized to broaden result variety.
    - Returns a dict with keys: "name" (str), "image" (str), "anime" (str).
    - If session is None this function creates and closes a ClientSession (see 'owns' var).
    - Raises RuntimeError when no characters are returned.
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
    owns = session is None
    if owns:
        session = aiohttp.ClientSession(timeout=DEFAULT_TIMEOUT)
    try:
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
    finally:
        if owns:
            await session.close()


async def _fetch_jikan_character_random(session: Optional[aiohttp.ClientSession] = None) -> Dict:
    """
    Query Jikan (MAL) top characters endpoint, page-randomized, and return a random result.

    - Returns a dict with keys: "name" (str), "image" (str), "anime" (str).
    - Uses 'owns' pattern to optionally create/close its own session.
    - Raises RuntimeError when no characters are available.
    """
    page = random.randint(1, 10)
    url = f"{EA.JIKAN_TOP_CHAR_URL}?page={page}"
    owns = session is None
    if owns:
        session = aiohttp.ClientSession(timeout=DEFAULT_TIMEOUT)
    try:
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
    finally:
        if owns:
            await session.close()


async def fetch_character_by_name(name: str, prefer: str = "AniList", session: Optional[aiohttp.ClientSession] = None) -> Optional[Dict]:
    """
    Fetch a character by name using AniList first (by default) then Jikan as fallback.

    - prefer controls which provider is attempted first.
    - Returns the first successful character dict or None if no provider matches.
    - Returned dicts are provider-specific but calling code expects keys such as:
      'id', 'name' (mapping with 'full'), 'image' (mapping with 'large'/'medium'), and optionally 'media'.
    """
    providers = [prefer, "Jikan" if prefer == "AniList" else "AniList"]
    for prov in providers:
        if prov == "AniList":
            char = await _fetch_anilist_character_by_name(name, session=session)
            if char:
                char["source"] = "AniList"
                return char
        else:
            char = await _fetch_jikan_character_by_name(name, session=session)
            if char:
                char["source"] = "Jikan (MAL)"
                return char
    return None


async def _fetch_anilist_character_by_name(name: str, session: Optional[aiohttp.ClientSession] = None) -> Optional[Dict]:
    """
    Query AniList Character(search: ...) and return the raw character payload.

    Notes:
    - The GraphQL selection requests 'image.large' and 'image.medium' to be compatible
      with downstream code that prefers 'large' then 'medium'.
    - Returns None on non-200 responses or if no character was found.
    """
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
    owns = session is None
    if owns:
        session = aiohttp.ClientSession(timeout=DEFAULT_TIMEOUT)
    try:
        async with session.post(EA.ANILIST_API, json={"query": query, "variables": variables}) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
        ch = (data.get("data") or {}).get("Character")
        return ch or None
    finally:
        if owns:
            await session.close()


async def _fetch_jikan_character_by_name(name: str, session: Optional[aiohttp.ClientSession] = None) -> Optional[Dict]:
    """
    Query Jikan character search endpoint and convert result to a shape compatible with
    the AniList-oriented consumer code.

    - Uses urllib.parse.quote to safely encode the query string.
    - Returns None if the HTTP status is non-200 or no results exist.
    - The returned dict contains 'id' (mal_id), 'name' mapping, and 'image' mapping with
      'large' and 'medium' pointing to the same Jikan image URL.
    """
    from urllib.parse import quote
    url = f"{EA.JIKAN_SEARCH_CHAR_URL}?q={quote(name)}&limit=1"
    owns = session is None
    if owns:
        session = aiohttp.ClientSession(timeout=DEFAULT_TIMEOUT)
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
    finally:
        if owns:
            await session.close()


def char_has_anime_media(char_obj: Optional[Dict]) -> bool:
    """
    Determine if the provided character object has at least one associated ANIME media node.

    - The function is defensive and tolerates different shapes (None, missing keys, etc.).
    - It upper-cases the 'type' field to handle provider inconsistencies.
    """
    if not char_obj:
        return False
    media = char_obj.get("media") or {}
    nodes = media.get("nodes") or []
    for n in nodes:
        if (n.get("type") or "").upper() == "ANIME":
            return True
    return False


async def get_wrong_names(source: str, correct_name: str, session: Optional[aiohttp.ClientSession] = None) -> List[str]:
    """
    Return a small list of plausible incorrect character names for use in multiple-choice UIs.

    - Attempts to fetch provider-generated alternatives; falls back to a small static pool.
    - Exceptions from provider calls are caught and a deterministic fallback is returned.
    """
    try:
        if source == "AniList":
            return await _get_anilist_wrong_options(correct_name, session=session)
        else:
            return await _get_jikan_wrong_options(correct_name, session=session)
    except Exception:
        return get_fallback_wrong_options(correct_name)


def get_fallback_wrong_options(correct_name: str, pool: Optional[List[str]] = None) -> List[str]:
    """
    Return up to 3 random names from a fallback pool excluding the correct_name.

    - The fallback pool is intentionally small and curated for predictable UX when
      API calls fail or are rate-limited.
    """
    names = [n for n in (pool or FALLBACK_NAMES) if n != correct_name]
    k = min(3, len(names))
    return random.sample(names, k=k) if k > 0 else []


async def _get_anilist_wrong_options(correct_name: str, session: Optional[aiohttp.ClientSession] = None) -> List[str]:
    """
    Request a page of popular characters from AniList and return up to 3 names
    that are different from the correct_name.

    - Uses the same 'owns' session pattern as other functions.
    - Falls back to get_fallback_wrong_options when the request fails or returns no data.
    """
    query = '''
    query ($page: Int, $perPage: Int) {
        Page(page: $page, perPage: $perPage) {
            characters(sort: FAVOURITES_DESC) { name { full } }
        }
    }
    '''
    variables = {"page": random.randint(1, 20), "perPage": 50}
    owns = session is None
    if owns:
        session = aiohttp.ClientSession(timeout=DEFAULT_TIMEOUT)
    try:
        async with session.post(EA.ANILIST_API, json={"query": query, "variables": variables}) as resp:
            if resp.status != 200:
                return get_fallback_wrong_options(correct_name)
            payload = await resp.json()
        chars = payload.get("data", {}).get("Page", {}).get("characters", [])
        wrong = [c["name"]["full"] for c in chars if c["name"]["full"] != correct_name]
        k = min(3, len(wrong))
        return random.sample(wrong, k=k) if k > 0 else get_fallback_wrong_options(correct_name)
    finally:
        if owns:
            await session.close()


async def _get_jikan_wrong_options(correct_name: str, session: Optional[aiohttp.ClientSession] = None) -> List[str]:
    """
    Query Jikan top characters and return up to 3 names excluding the correct_name.

    - Uses a randomized page index to diversify results.
    - Falls back to the static pool when the HTTP call fails.
    """
    page = random.randint(1, 10)
    url = f"{EA.JIKAN_TOP_CHAR_URL}?page={page}"
    owns = session is None
    if owns:
        session = aiohttp.ClientSession(timeout=DEFAULT_TIMEOUT)
    try:
        async with session.get(url) as resp:
            if resp.status != 200:
                return get_fallback_wrong_options(correct_name)
            payload = await resp.json()
        chars = payload.get("data", [])
        wrong = [c["name"] for c in chars if c["name"] != correct_name]
        k = min(3, len(wrong))
        return random.sample(wrong, k=k) if k > 0 else get_fallback_wrong_options(correct_name)
    finally:
        if owns:
            await session.close()


async def build_character_select_options(correct_name: str, source: str, session: Optional[aiohttp.ClientSession] = None) -> List[discord.SelectOption]:
    """
    Build a randomized list of discord.SelectOption objects containing the correct_name
    and up to three distractor names.

    - Returns options shuffled so the correct answer position is not predictable.
    - Useful for human verification flows (e.g., "pick the correct character name").
    """
    opts = [correct_name]
    wrong = await get_wrong_names(source, correct_name, session=session)
    opts.extend(wrong)
    random.shuffle(opts)
    return [discord.SelectOption(label=o, value=o) for o in opts]


async def _check(resp):
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


async def is_image_url_ok(session: aiohttp.ClientSession, url: str, timeout_obj: aiohttp.ClientTimeout) -> bool:
    """
    Check whether the given URL refers to an image and is reachable.

    Strategy:
    1. Try an HTTP HEAD request to validate content-type/status/length quickly.
    2. If HEAD fails or doesn't provide usable headers, fall back to GET and inspect headers.
    3. Return True only when status is 200, Content-Type starts with "image/", and size > 1KB.

    Exceptions are swallowed and treated as unreachable (False).
    """
    if not url:
        return False

    try:
        async with session.head(url, timeout=timeout_obj, allow_redirects=True) as resp:
            if await _check(resp):
                return True
    except Exception:
        pass

    try:
        async with session.get(url, timeout=timeout_obj, allow_redirects=True) as resp:
            return await _check(resp)
    except Exception:
        return False


async def google_image_search(query: str, api_key: str, cx: str, session: Optional[aiohttp.ClientSession] = None) -> List[str]:
    """
    Query Google Custom Search (image type) and return a filtered list of image links.

    - Uses `searchType=image` and filters results by common image file extensions.
    - Returns only links ending with one of ('.png', '.jpg', '.jpeg', '.webp') to reduce
      false positives (this may exclude valid images with unusual URLs).
    - The function tolerates JSON parse errors and returns an empty list on unexpected payloads.

    Important:
    - The caller is responsible for handling API key/execution quotas and errors.
    """
    from urllib.parse import quote
    url = (
        f"https://www.googleapis.com/customsearch/v1?"
        f"key={api_key}&cx={cx}&searchType=image&q={quote(query)}"
    )
    owns = session is None
    if owns:
        session = aiohttp.ClientSession(timeout=DEFAULT_TIMEOUT)
    try:
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
    finally:
        if owns:
            await session.close()


async def first_reachable_image(links: List[str]) -> Optional[str]:
    """
    Return the first reachable image URL from a list of links.

    - Creates a temporary ClientSession with DEFAULT_TIMEOUT and iterates links in order.
    - Uses is_image_url_ok to validate reachability and content-type.
    - Returns the first URL that passes validation, or None if none are reachable.
    """
    if not links:
        return None
    async with aiohttp.ClientSession(timeout=DEFAULT_TIMEOUT) as session:
        for link in links:
            try:
                ok = await is_image_url_ok(session, link, DEFAULT_TIMEOUT)
                if ok:
                    return link
            except Exception:
                continue
    return None