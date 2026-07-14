"""Character quiz option and distractor helpers."""

import asyncio
import random
from typing import List, Optional

import aiohttp
import discord

from bot.config.configs import AnimeAPIConstants as AC
from bot.config.configs import ExternalAPIs as EA


async def get_wrong_names(
    source: str, correct_name: str, session: aiohttp.ClientSession
) -> List[str]:
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


def get_fallback_wrong_options(
    correct_name: str, pool: Optional[List[str]] = None
) -> List[str]:
    """
    Return up to 3 random names from a fallback pool excluding the correct_name.
    """
    names = [n for n in (pool or AC.FALLBACK_NAMES) if n != correct_name]
    k = min(3, len(names))
    return random.sample(names, k=k) if k > 0 else []


async def _get_anilist_wrong_options(
    correct_name: str, session: aiohttp.ClientSession
) -> List[str]:
    """
    Request a page of popular characters from AniList for distractors.
    """
    query = """
    query ($page: Int, $perPage: Int) {
        Page(page: $page, perPage: $perPage) {
            characters(sort: FAVOURITES_DESC) { name { full } }
        }
    }
    """
    variables = {"page": random.randint(1, 20), "perPage": 50}

    async with session.post(
        EA.ANILIST_API, json={"query": query, "variables": variables}
    ) as resp:
        if resp.status != 200:
            return get_fallback_wrong_options(correct_name)
        payload = await resp.json()

    chars = payload.get("data", {}).get("Page", {}).get("characters", [])
    wrong = [c["name"]["full"] for c in chars if c["name"]["full"] != correct_name]
    k = min(3, len(wrong))
    return (
        random.sample(wrong, k=k) if k > 0 else get_fallback_wrong_options(correct_name)
    )


async def _get_jikan_wrong_options(
    correct_name: str, session: aiohttp.ClientSession
) -> List[str]:
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
    return (
        random.sample(wrong, k=k) if k > 0 else get_fallback_wrong_options(correct_name)
    )


async def build_character_select_options(
    correct_name: str, source: str, session: aiohttp.ClientSession
) -> List[discord.SelectOption]:
    """
    Build a randomized list of discord.SelectOption objects.
    """
    opts = [correct_name]
    wrong = await get_wrong_names(source, correct_name, session)
    opts.extend(wrong)
    random.shuffle(opts)
    return [discord.SelectOption(label=o, value=o) for o in opts]
