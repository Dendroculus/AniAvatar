import aiohttp
import asyncio

class HTTPValidator:
    def __init__(self, timeout: float = 3.0, max_concurrent: int = 10):
        self.timeout = timeout
        self.semaphore = asyncio.Semaphore(max_concurrent)
    
    async def validate_urls(self, urls: list[str]) -> tuple[list[str], list[str]]:
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