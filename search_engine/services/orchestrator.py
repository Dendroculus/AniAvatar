import asyncio
from dataclasses import dataclass
from ..utils.deduplicator import URLDeduplicator
from .cache_service import CacheService
from ..workers.pinterest import PinterestWorker
from ..workers.google import GoogleWorker
from ..utils.http_validator import HTTPValidator

@dataclass
class SearchResponse:
    images: list
    from_cache: bool
    exhausted: bool 

class SearchOrchestrator:
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
        # 1. Try to get Unseen Images from Global Cache
        # Ask for slightly more than count to have a buffer
        unseen_cached = await self.cache.get_unseen_images(query, user_id, limit=count + 5)
        
        # If we found enough new content in the cache, return it immediately
        if len(unseen_cached) >= count:
            selected = unseen_cached[:count]
            # Mark them as seen so they aren't shown again next time
            await self.cache.mark_viewed(user_id, query, selected)
            return SearchResponse(selected, True, False)
        
        # 2. Not enough in cache? We need to Scrape for FRESH content.
        # We fetch existing URLs user has seen to deduplicate in memory (optional optimization, 
        # but for now we rely on the DB insert check which is safer).
        
        live_results = []
        try:
            # Scrape a batch (15-20)
            live_results = await asyncio.wait_for(
                self.pinterest.search(query, limit=20), 
                timeout=30.0
            )
        except Exception:
            live_results = []

        # 3. Google Fallback if Pinterest is dry
        if len(live_results) < count:
            try:
                google_res = await self.google.search(query, limit=10)
                live_results.extend(google_res)
            except Exception:
                pass

        # 4. Deduplicate & Validate
        deduped = URLDeduplicator.deduplicate(live_results)
        
        # Validate URLs
        urls = [i.image_url for i in deduped]
        valid_urls, _ = await self.validator.validate_urls(urls)
        valid_images = [i for i in deduped if i.image_url in valid_urls]
        
        # 5. Store in Global Cache (so other users can see them)
        if valid_images:
            await self.cache.store_images(query, valid_images)
            
        # 6. FILTER: Which of these valid images has the user NOT seen?
        # We re-query the database for 'unseen' images. 
        # Why? Because we just inserted the fresh scrape into the DB. 
        # Now we ask the DB: "Give me images for this query that User X hasn't seen."
        # This handles the logic of filtering out duplicates perfectly.
        
        final_fresh = await self.cache.get_unseen_images(query, user_id, limit=count)
        
        if not final_fresh:
            # If after scraping and checking DB we STILL have nothing, 
            # the user has truly seen everything we can find right now.
            return SearchResponse([], False, True)

        # 7. Mark as seen and return
        await self.cache.mark_viewed(user_id, query, final_fresh)
        
        return SearchResponse(final_fresh, False, False)