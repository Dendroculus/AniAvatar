"""Waifu-image API client."""

from __future__ import annotations


class WaifuAPIError(RuntimeError):
    """Raised when the waifu API returns a failed status."""


class WaifuImageMissing(RuntimeError):
    """Raised when the API response contains no image URL."""


class WaifuClient:
    """Fetch random waifu image URLs using the shared bot session."""

    def __init__(
        self,
        bot,
        endpoint: str,
    ) -> None:
        self.bot = bot
        self.endpoint = endpoint

    async def fetch_image_url(self) -> str:
        """Fetch and validate one random image URL."""

        async with self.bot.session.get(self.endpoint) as response:
            if response.status != 200:
                raise WaifuAPIError(f"Waifu API returned status {response.status}.")

            data = await response.json()

        image_url = data.get("url")

        if not image_url:
            raise WaifuImageMissing("Waifu API response had no image URL.")

        return str(image_url)
