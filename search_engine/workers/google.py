import aiohttp
import logging
from urllib.parse import quote
from ..database.models import ImageResult

logger = logging.getLogger(__name__)

class GoogleWorker:
    """
    Worker for fetching images using the Google Custom Search API.
    
    Acts as a fallback when scraping fails or returns insufficient results.
    Uses the shared bot session to prevent connection exhaustion.
    """
    def __init__(self, session: aiohttp.ClientSession, api_key: str, cx: str):
        """
        Initialize the Google Worker.

        Args:
            session (aiohttp.ClientSession): Shared HTTP session.
            api_key (str): Google API Key.
            cx (str): Google Custom Search Engine ID.
        """
        self.session = session
        self.api_key = api_key
        self.cx = cx

    async def search(self, query: str, limit: int = 5) -> list[ImageResult]:
        """
        Perform an image search via Google API.

        Args:
            query (str): The search term.
            limit (int): Maximum number of results to return (API pages).

        Returns:
            list[ImageResult]: A list of found images.
        """
        if not self.api_key or not self.cx:
            logger.warning("Google API credentials missing. Skipping search.")
            return []

        # Construct URL with strict parameters for high-quality images
        url = (
            f"https://www.googleapis.com/customsearch/v1?"
            f"key={self.api_key}&cx={self.cx}&searchType=image"
            f"&imgSize=large&safe=active&q={quote(query + ' anime pfp')}"
        )
        
        results = []
        try:
            async with self.session.get(url) as resp:
                if resp.status != 200:
                    logger.warning(f"Google API returned status {resp.status}")
                    return []
                data = await resp.json()
                
            items = data.get("items", [])
            for item in items:
                if len(results) >= limit:
                    break
                    
                link = item.get("link")
                if link:
                    title = item.get("title", f"Result for {query}")
                    thumbnail = item.get("image", {}).get("thumbnailLink", link)
                    
                    results.append(ImageResult(
                        image_url=link,
                        source="Google Images",
                        thumbnail_url=thumbnail,
                        title=title
                    ))
        except Exception as e:
            logger.error(f"Google Search Error: {e}")
            
        return results