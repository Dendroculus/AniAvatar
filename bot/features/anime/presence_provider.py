"""AniList-backed anime titles for Discord presence rotation."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import aiohttp

from bot.config.configs import AnimeAPIConstants as AC
from bot.config.configs import ExternalAPIs as EA
from bot.config.paths import DATA_PATH


logger = logging.getLogger(__name__)

DEFAULT_PRESENCE_TITLES = (
    "Frieren: Beyond Journey's End",
    "Fullmetal Alchemist: Brotherhood",
    "Steins;Gate",
    "Hunter x Hunter",
    "Attack on Titan",
    "Violet Evergarden",
    "Kaguya-sama: Love is War",
    "Oshi no Ko",
    "Re:Zero",
    "The Apothecary Diaries",
)

ANILIST_PRESENCE_QUERY = """
query ($page: Int, $perPage: Int) {
  Page(page: $page, perPage: $perPage) {
    media(
      type: ANIME
      isAdult: false
      sort: POPULARITY_DESC
    ) {
      title {
        english
        romaji
      }
    }
  }
}
"""


class AnimePresenceProvider:
    """Load popular anime titles from AniList with a durable local cache."""

    def __init__(
        self,
        bot,
        *,
        cache_path: Path | None = None,
        cache_ttl: timedelta = timedelta(hours=24),
        per_page: int = 50,
    ) -> None:
        self.bot = bot
        self.cache_path = (
            cache_path
            if cache_path is not None
            else DATA_PATH / "cache" / "anilist_presence.json"
        )
        self.cache_ttl = cache_ttl
        self.per_page = max(1, min(per_page, 50))

    async def load_titles(self) -> list[str]:
        """Return a fresh cache, AniList data, stale cache, or defaults."""
        cached = await asyncio.to_thread(self._read_cache)

        if cached is not None:
            fetched_at, titles = cached
            if datetime.now(timezone.utc) - fetched_at <= self.cache_ttl:
                return titles

        fresh_titles = await self._fetch_titles()

        if fresh_titles:
            await asyncio.to_thread(self._write_cache, fresh_titles)
            return fresh_titles

        if cached is not None:
            logger.warning("AniList presence refresh failed; using stale cache.")
            return cached[1]

        logger.warning("AniList presence data unavailable; using built-in defaults.")
        return list(DEFAULT_PRESENCE_TITLES)

    async def refresh_titles(self) -> list[str]:
        """Fetch and cache new titles, returning an empty list on failure."""
        titles = await self._fetch_titles()

        if not titles:
            return []

        await asyncio.to_thread(self._write_cache, titles)
        return titles

    async def _fetch_titles(self) -> list[str]:
        session = getattr(self.bot, "session", None)

        if session is None or session.closed:
            logger.warning(
                "Cannot refresh AniList presence titles: HTTP session unavailable."
            )
            return []

        variables = {
            "page": 1,
            "perPage": self.per_page,
        }

        try:
            async with asyncio.timeout(AC.TIMEOUT_SECONDS):
                async with session.post(
                    EA.ANILIST_API,
                    json={
                        "query": ANILIST_PRESENCE_QUERY,
                        "variables": variables,
                    },
                ) as response:
                    if response.status != 200:
                        logger.warning(
                            "AniList presence request returned HTTP %s.",
                            response.status,
                        )
                        return []

                    payload = await response.json(content_type=None)

        except TimeoutError:
            logger.warning("AniList presence request timed out.")
            return []
        except (aiohttp.ClientError, ValueError, TypeError):
            logger.exception("AniList presence request failed.")
            return []

        if not isinstance(payload, dict) or payload.get("errors"):
            logger.warning("AniList presence response contained GraphQL errors.")
            return []

        media = payload.get("data", {}).get("Page", {}).get("media", [])

        if not isinstance(media, list):
            return []

        return self._extract_titles(media)

    @staticmethod
    def _extract_titles(media: list[Any]) -> list[str]:
        titles: list[str] = []
        seen: set[str] = set()

        for item in media:
            if not isinstance(item, dict):
                continue

            title_data = item.get("title")

            if not isinstance(title_data, dict):
                continue

            title = title_data.get("english") or title_data.get("romaji")

            if not isinstance(title, str):
                continue

            title = " ".join(title.split()).strip()

            if not title:
                continue

            lookup = title.casefold()

            if lookup in seen:
                continue

            seen.add(lookup)
            titles.append(title)

        return titles

    def _read_cache(self) -> tuple[datetime, list[str]] | None:
        try:
            payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
            fetched_at_raw = payload.get("fetched_at")
            titles_raw = payload.get("titles")

            if not isinstance(fetched_at_raw, str) or not isinstance(titles_raw, list):
                return None

            fetched_at = datetime.fromisoformat(fetched_at_raw)

            if fetched_at.tzinfo is None:
                fetched_at = fetched_at.replace(tzinfo=timezone.utc)

            titles = [
                title.strip()
                for title in titles_raw
                if isinstance(title, str) and title.strip()
            ]

            if not titles:
                return None

            return fetched_at.astimezone(timezone.utc), titles

        except (OSError, ValueError, TypeError, AttributeError):
            return None

    def _write_cache(self, titles: list[str]) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)

        payload = {
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "titles": titles,
        }
        temporary_path = self.cache_path.with_suffix(self.cache_path.suffix + ".tmp")
        temporary_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        temporary_path.replace(self.cache_path)
