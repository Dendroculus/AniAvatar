import aiohttp
import logging
from urllib.parse import quote
from ..database.models import ImageResult

logger = logging.getLogger(__name__)

class GoogleWorker:
    def __init__(self, session: aiohttp.ClientSession, api_key: str, cx: str):
        self.session = session
        self.api_key = api_key
        self.cx = cx

    async def search(self, query: str, limit: int = 5) -> list[ImageResult]:
        if not self.api_key or not self.cx:
            return []

        # UPDATED: Added &imgSize=large to force high quality
        url = (
            f"https://www.googleapis.com/customsearch/v1?"
            f"key={self.api_key}&cx={self.cx}&searchType=image"
            f"&imgSize=large&safe=active&q={quote(query + ' anime pfp')}"
        )
        
        results = []
        try:
            async with self.session.get(url) as resp:
                if resp.status != 200:
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