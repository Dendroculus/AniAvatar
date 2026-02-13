import asyncio
import random
import logging
import re
from urllib.parse import quote_plus
from playwright.async_api import async_playwright
from ..database.models import ImageResult
from ..utils.rate_limiter import TokenBucketRateLimiter

logger = logging.getLogger(__name__)

class PinterestWorker:
    def __init__(self, rate_limiter: TokenBucketRateLimiter):
        self.limiter = rate_limiter
        self.playwright = None
        self.browser = None

    async def initialize(self):
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=True, 
            args=["--no-sandbox", "--disable-gpu"]
        )

    async def close(self):
        if self.browser: 
            await self.browser.close()
        if self.playwright: 
            await self.playwright.stop()

    async def search(self, query: str, limit: int = 20) -> list[ImageResult]:
        await self.limiter.acquire()
        if not self.browser: 
            raise RuntimeError("Worker not initialized")
        
        context = await self.browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        results = []
        
        try:
            # Search URL
            await page.goto(f"https://www.pinterest.com/search/pins/?q={quote_plus(query + ' anime pfp')}")
            
            # Scroll to load more items
            for _ in range(random.randint(2, 4)):
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await asyncio.sleep(1.0)
            
            # Extract images
            imgs = await page.query_selector_all('img[src*="pinimg.com"]')
            
            for img in imgs:
                if len(results) >= limit: 
                    break
                
                src = await img.get_attribute("src")
                if not src: 
                    continue

                # SKIP tiny UI icons/avatars (usually 30x30 or 75x75)
                if "30x30" in src or "75x75" in src:
                    continue

                # --- FORCE UPSCALE LOGIC ---
                # Pinterest URLs look like: https://i.pinimg.com/236x/path/to/image.jpg
                # We want: https://i.pinimg.com/originals/path/to/image.jpg
                # Regex replaces '/236x/', '/474x/', '/564x/' with '/originals/'
                hd_url = re.sub(r'/\d+x/', '/originals/', src)
                
                # Check for video thumbnails (often obscure format, skip if unsure)
                if not hd_url.endswith(('.jpg', '.jpeg', '.png', '.webp')):
                    hd_url = src

                results.append(ImageResult(
                    image_url=hd_url,      # The HD version
                    source="pinterest", 
                    thumbnail_url=src,     # Keep low-res for thumbnail (optional)
                    title=query
                ))
                
        except Exception as e:
            logger.error(f"Scrape error: {e}")
        finally:
            await context.close()
            
        return results