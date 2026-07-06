import asyncio
from dataclasses import dataclass
from ..utils.deduplicator import URLDeduplicator
from .cache_service import CacheService
from ..workers.pinterest import PinterestWorker
from ..workers.google import GoogleWorker
from ..utils.http_validator import HTTPValidator

@dataclass
class SearchResponse:
    """
    Encapsulates the result of a search operation.

    Attributes:
        images (list): List of found ImageResult objects.
        from_cache (bool): True if results came from the database.
        exhausted (bool): True if no new content exists for this user/query.
    """
    images: list
    from_cache: bool
    exhausted: bool 

class SearchOrchestrator:
    """
    Coordinating service that manages the search workflow.
    
    It orchestrates:
    1. Checking cache for unseen images.
    2. Scraping external sources (Pinterest, Google) if needed.
    3. Validating and deduplicating results.
    4. Updating the cache and user history.
    """
    def __init__(
        self, 
        cache: CacheService, 
        pinterest: PinterestWorker, 
        google: GoogleWorker,
        validator: HTTPValidator
    ):
        self.cache = cache
        self.pinterest = pinterest
        self.google = google
        self.validator = validator

    async def search(self, query: str, user_id: int, count: int = 1) -> SearchResponse:
        """
        Perform a search for a user, prioritizing unseen cached content.

        Args:
            query (str): The search term.
            user_id (int): The Discord User ID (for history tracking).
            count (int): Number of images requested.

        Returns:
            SearchResponse: Object containing images and status flags.
        """
        unseen_cached = await self.cache.get_unseen_images(query, user_id, limit=count + 5)
        
        if len(unseen_cached) >= count:
            selected = unseen_cached[:count]
            await self.cache.mark_viewed(user_id, query, selected)
            return SearchResponse(selected, True, False)
        
        live_results = []
        try:
            live_results = await asyncio.wait_for(
                self.pinterest.search(query, limit=20), 
                timeout=30.0
            )
        except Exception:
            live_results = []
        if len(live_results) < count:
            try:
                google_res = await self.google.search(query, limit=10)
                live_results.extend(google_res)
            except Exception:
                pass

        deduped = URLDeduplicator.deduplicate(live_results)
        
        urls = [i.image_url for i in deduped]
        valid_urls, _ = await self.validator.validate_urls(urls)
        valid_images = [i for i in deduped if i.image_url in valid_urls]
        
        if valid_images:
            await self.cache.store_images(query, valid_images)
            
        final_fresh = await self.cache.get_unseen_images(query, user_id, limit=count)
        
        if not final_fresh:
            return SearchResponse([], False, True)

        await self.cache.mark_viewed(user_id, query, final_fresh)
        
        return SearchResponse(final_fresh, False, False)