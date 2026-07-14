"""Waifu-image API client."""

from __future__ import annotations

import asyncio

import aiohttp


class WaifuAPIError(RuntimeError):
    """Raised when the waifu API request fails."""


class WaifuImageMissing(RuntimeError):
    """Raised when the API response contains no image URL."""


class WaifuClient:
    """Fetch random SFW waifu image URLs using the shared bot session."""

    def __init__(
        self,
        bot,
        endpoint: str,
        *,
        timeout_seconds: float = 10.0,
    ) -> None:
        self.bot = bot
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds

    async def fetch_image_url(self) -> str:
        """Fetch and validate one random SFW image URL."""
        session = getattr(self.bot, "session", None)

        if session is None or session.closed:
            raise WaifuAPIError("The shared HTTP session is unavailable.")

        params = {
            "IsNsfw": "False",
            "PageSize": "1",
        }

        try:
            async with asyncio.timeout(self.timeout_seconds):
                async with session.get(
                    self.endpoint,
                    params=params,
                ) as response:
                    if response.status != 200:
                        raise WaifuAPIError(
                            f"Waifu API returned status {response.status}."
                        )

                    try:
                        data = await response.json(content_type=None)
                    except (
                        aiohttp.ContentTypeError,
                        ValueError,
                    ) as error:
                        raise WaifuAPIError(
                            "Waifu API returned invalid JSON."
                        ) from error

        except TimeoutError as error:
            raise WaifuAPIError("Waifu API request timed out.") from error
        except aiohttp.ClientError as error:
            raise WaifuAPIError("Waifu API connection failed.") from error

        items = data.get("items") if isinstance(data, dict) else None
        image_url = (
            items[0].get("url")
            if isinstance(items, list) and items and isinstance(items[0], dict)
            else None
        )

        if not image_url:
            raise WaifuImageMissing("Waifu API response had no image URL.")

        return str(image_url)
