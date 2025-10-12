import random
from typing import Dict, List, Optional
import aiohttp
import discord

ANILIST_URL = "https://graphql.anilist.co"
JIKAN_TOP_CHAR_URL = "https://api.jikan.moe/v4/top/characters"
JIKAN_SEARCH_CHAR_URL = "https://api.jikan.moe/v4/characters"

DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=10)

FALLBACK_NAMES = [
    "Naruto Uzumaki", "Monkey D. Luffy", "Goku", "Light Yagami", "Eren Yeager", "Levi Ackerman",
    "Saitama", "Edward Elric", "Spike Spiegel", "Lelouch Lamperouge", "Killua Zoldyck", "Gon Freecss"
]


async def fetch_random_character(prefer: str = "AniList", session: Optional[aiohttp.ClientSession] = None) -> Dict:
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
        async with session.post(ANILIST_URL, json={"query": query, "variables": variables}) as resp:
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
    page = random.randint(1, 10)
    url = f"{JIKAN_TOP_CHAR_URL}?page={page}"
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
        async with session.post(ANILIST_URL, json={"query": query, "variables": variables}) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
        ch = (data.get("data") or {}).get("Character")
        return ch or None
    finally:
        if owns:
            await session.close()

async def _fetch_jikan_character_by_name(name: str, session: Optional[aiohttp.ClientSession] = None) -> Optional[Dict]:
    from urllib.parse import quote
    url = f"{JIKAN_SEARCH_CHAR_URL}?q={quote(name)}&limit=1"
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
    if not char_obj:
        return False
    media = char_obj.get("media") or {}
    nodes = media.get("nodes") or []
    for n in nodes:
        if (n.get("type") or "").upper() == "ANIME":
            return True
    return False

async def get_wrong_names(source: str, correct_name: str, session: Optional[aiohttp.ClientSession] = None) -> List[str]:
    try:
        if source == "AniList":
            return await _get_anilist_wrong_options(correct_name, session=session)
        else:
            return await _get_jikan_wrong_options(correct_name, session=session)
    except Exception:
        return get_fallback_wrong_options(correct_name)

def get_fallback_wrong_options(correct_name: str, pool: Optional[List[str]] = None) -> List[str]:
    names = [n for n in (pool or FALLBACK_NAMES) if n != correct_name]
    k = min(3, len(names))
    return random.sample(names, k=k) if k > 0 else []

async def _get_anilist_wrong_options(correct_name: str, session: Optional[aiohttp.ClientSession] = None) -> List[str]:
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
        async with session.post(ANILIST_URL, json={"query": query, "variables": variables}) as resp:
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
    page = random.randint(1, 10)
    url = f"{JIKAN_TOP_CHAR_URL}?page={page}"
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
    opts = [correct_name]
    wrong = await get_wrong_names(source, correct_name, session=session)
    opts.extend(wrong)
    random.shuffle(opts)
    return [discord.SelectOption(label=o, value=o) for o in opts]


async def is_image_url_ok(session: aiohttp.ClientSession, url: str, timeout_obj: aiohttp.ClientTimeout) -> bool:
    if not url:
        return False
    try:
        async with session.head(url, timeout=timeout_obj) as resp:
            ct = resp.headers.get("Content-Type", "")
            if resp.status == 200 and ct and ct.startswith("image"):
                return True
    except Exception:
        pass
    try:
        async with session.get(url, timeout=timeout_obj) as resp:
            ct = resp.headers.get("Content-Type", "")
            return resp.status == 200 and ct and ct.startswith("image")
    except Exception:
        return False

async def google_image_search(query: str, api_key: str, cx: str, session: Optional[aiohttp.ClientSession] = None) -> List[str]:
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
        links = [
            item.get("link") for item in items
            if isinstance(item.get("link"), str) and item["link"].lower().endswith((".png", ".jpg", ".jpeg", ".webp"))
        ]
        return links
    finally:
        if owns:
            await session.close()

async def first_reachable_image(links: List[str], timeout: aiohttp.ClientTimeout) -> Optional[str]:
    if not links:
        return None
    async with aiohttp.ClientSession(timeout=timeout) as session:
        for link in links:
            try:
                ok = await is_image_url_ok(session, link, timeout)
                if ok:
                    return link
            except Exception:
                continue
    return None