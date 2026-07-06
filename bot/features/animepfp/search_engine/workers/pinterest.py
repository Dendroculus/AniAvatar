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
    """
    Worker for scraping high-quality anime images from Pinterest.
    
    Uses Playwright to render the page, handles scrolling for lazy-loaded content,
    and applies heuristics to find the highest resolution image version.
    """
    def __init__(self, rate_limiter: TokenBucketRateLimiter):
        """
        Initialize the Pinterest Worker.

        Args:
            rate_limiter (TokenBucketRateLimiter): Limiter to prevent IP bans.
        """
        self.limiter = rate_limiter
        self.playwright = None
        self.browser = None

    async def initialize(self):
        """
        Start the Playwright engine and launch the headless browser.
        Must be called before search().
        """
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=True, 
            args=["--no-sandbox", "--disable-gpu"]
        )

    async def close(self):
        """
        Gracefully close the browser and Playwright engine.
        """
        if self.browser: 
            await self.browser.close()
        if self.playwright: 
            await self.playwright.stop()

    async def search(self, query: str, limit: int = 20) -> list[ImageResult]:
        """
        Scrape Pinterest for images matching the query.

        Args:
            query (str): The search term.
            limit (int): Target number of images to scrape.

        Returns:
            list[ImageResult]: List of high-resolution image results.
        
        Raises:
            RuntimeError: If the worker has not been initialized.
        """
        await self.limiter.acquire()
        if not self.browser: 
            raise RuntimeError("Worker not initialized")
        
        # Use a new context per search to ensure a clean state
        context = await self.browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        results = []
        
        try:
            # Construct search URL
            search_url = f"https://www.pinterest.com/search/pins/?q={quote_plus(query + ' anime pfp')}"
            await page.goto(search_url)
            
            # Smart Scroll: Scroll a few times to trigger lazy loading
            scroll_count = random.randint(2, 4)
            for _ in range(scroll_count):
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await asyncio.sleep(1.0)
            
            # Extract images based on the unique Pinterest CDN domain
            imgs = await page.query_selector_all('img[src*="pinimg.com"]')
            
            for img in imgs:
                if len(results) >= limit: 
                    break
                
                src = await img.get_attribute("src")
                if not src: 
                    continue

                # Filter out tiny UI icons/avatars (usually 30x30 or 75x75)
                if "30x30" in src or "75x75" in src:
                    continue

                # --- FORCE UPSCALE LOGIC ---
                # Pinterest serves low-res thumbnails in the grid (e.g., 236x).
                # We rewrite the URL to point to the 'originals' bucket for HD quality.
                # Regex replaces '/236x/', '/474x/', '/564x/' with '/originals/'.
                hd_url = re.sub(r'/\d+x/', '/originals/', src)
                
                # Check for video thumbnails or non-image formats (often obscure)
                if not hd_url.endswith(('.jpg', '.jpeg', '.png', '.webp')):
                    hd_url = src

                results.append(ImageResult(
                    image_url=hd_url,      # The HD version
                    source="pinterest", 
                    thumbnail_url=src,     # Keep low-res for thumbnail (optional)
                    title=query
                ))
                
        except Exception as e:
            logger.error(f"Scrape error for query '{query}': {e}")
        finally:
            await context.close()
            
        return results