import aiohttp
import asyncio

class HTTPValidator:
    """
    Validates URLs by checking if they are reachable (HTTP 200).
    Uses a semaphore to limit concurrent connections.
    """
    def __init__(self, timeout: float = 3.0, max_concurrent: int = 10):
        self.timeout = timeout
        self.semaphore = asyncio.Semaphore(max_concurrent)
    
    async def validate_urls(self, urls: list[str]) -> tuple[list[str], list[str]]:
        """
        Concurrently validate a list of URLs.

        Args:
            urls (list[str]): List of URLs to check.

        Returns:
            tuple[list[str], list[str]]: A tuple containing (valid_urls, dead_urls).
        """
        async def check(url):
            async with self.semaphore:
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.head(url, timeout=self.timeout) as resp:
                            return url, resp.status == 200
                except Exception:
                    return url, False

        results = await asyncio.gather(*[check(u) for u in urls])
        valid = [r[0] for r in results if r[1]]
        dead = [r[0] for r in results if not r[1]]
        return valid, dead