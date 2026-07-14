"""AniList anime metadata search helpers."""

import asyncio
from typing import Dict, List

import aiohttp

from bot.config.configs import AnimeAPIConstants as AC
from bot.config.configs import ExternalAPIs as EA


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
            async with session.post(
                EA.ANILIST_API, json={"query": query_str, "variables": variables}
            ) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
            return data.get("data", {}).get("Page", {}).get("media", [])
    except Exception:
        return []
