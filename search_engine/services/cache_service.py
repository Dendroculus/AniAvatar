from ..database.connection import DatabasePool
from ..database.models import ImageResult
from ..database.queries import GET_UNSEEN_IMAGES, INSERT_CACHED_IMAGE, MARK_AS_SEEN, GET_STALE_IMAGES, MARK_IMAGES_DEAD, UPDATE_VALIDATION_TIME

class CacheService:
    def __init__(self, db: DatabasePool):
        self.db = db
    
    @staticmethod
    def normalize_query(query: str) -> str:
        # Lowercase and remove extra spaces: "Mahiru   Shiina " -> "mahiru shiina"
        return " ".join(query.lower().strip().split())
    
    async def get_unseen_images(self, query: str, user_id: int, limit: int = 5) -> list[ImageResult]:
        """Fetch cached images excluding ones the user has already seen."""
        norm = self.normalize_query(query)
        rows = await self.db.fetch(GET_UNSEEN_IMAGES, norm, user_id, limit)
        return [
            ImageResult(
                image_url=r['image_url'], 
                source=r['source'], 
                thumbnail_url=r['thumbnail_url'], 
                title=r['title']
            ) for r in rows
        ]
    
    async def store_images(self, query: str, images: list[ImageResult]):
        """Save new images to the global cache."""
        norm = self.normalize_query(query)
        for img in images:
            await self.db.execute(
                INSERT_CACHED_IMAGE, 
                norm, img.image_url, img.source, img.thumbnail_url, img.title
            )
            
    async def mark_viewed(self, user_id: int, query: str, images: list[ImageResult]):
        """Mark images as seen by a specific user."""
        norm = self.normalize_query(query)
        for img in images:
            await self.db.execute(MARK_AS_SEEN, user_id, norm, img.image_url)

    async def get_stale_urls(self, limit: int = 100):
        rows = await self.db.fetch(GET_STALE_IMAGES, limit)
        return [r['image_url'] for r in rows]

    async def mark_dead(self, urls: list[str]):
        if urls: 
            await self.db.execute(MARK_IMAGES_DEAD, urls)

    async def update_validation(self, urls: list[str]):
        if urls: 
            await self.db.execute(UPDATE_VALIDATION_TIME, urls)