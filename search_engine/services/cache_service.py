from ..database.connection import DatabasePool
from ..database.models import ImageResult
from ..database.queries import (
    GET_UNSEEN_IMAGES, 
    INSERT_CACHED_IMAGE, 
    MARK_AS_SEEN, 
    GET_STALE_IMAGES, 
    MARK_IMAGES_DEAD, 
    UPDATE_VALIDATION_TIME
)

class CacheService:
    """
    Service layer abstracting database interactions for image caching and history.
    """
    def __init__(self, db: DatabasePool):
        self.db = db
    
    @staticmethod
    def normalize_query(query: str) -> str:
        """
        Normalize a search query string.
        
        Example: "  Mahiru   Shiina " -> "mahiru shiina"

        Args:
            query (str): Raw input query.

        Returns:
            str: Normalized query string.
        """
        return " ".join(query.lower().strip().split())
    
    async def get_unseen_images(self, query: str, user_id: int, limit: int = 5) -> list[ImageResult]:
        """
        Retrieve cached images that the specified user has not yet seen.

        Args:
            query (str): The search query.
            user_id (int): Discord User ID.
            limit (int): Number of images to fetch.

        Returns:
            list[ImageResult]: List of unseen image objects.
        """
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
        """
        Store newly scraped images into the global cache.

        Args:
            query (str): The search query.
            images (list[ImageResult]): List of new images.
        """
        norm = self.normalize_query(query)
        for img in images:
            await self.db.execute(
                INSERT_CACHED_IMAGE, 
                norm, img.image_url, img.source, img.thumbnail_url, img.title
            )
            
    async def mark_viewed(self, user_id: int, query: str, images: list[ImageResult]):
        """
        Mark images as 'seen' for a specific user to prevent repetition.

        Args:
            user_id (int): Discord User ID.
            query (str): The search query.
            images (list[ImageResult]): List of images displayed to the user.
        """
        norm = self.normalize_query(query)
        for img in images:
            await self.db.execute(MARK_AS_SEEN, user_id, norm, img.image_url)

    async def get_stale_urls(self, limit: int = 100) -> list[str]:
        """
        Get cached URLs that have not been validated in 24 hours.

        Args:
            limit (int): Max number of URLs to retrieve.

        Returns:
            list[str]: List of stale image URLs.
        """
        rows = await self.db.fetch(GET_STALE_IMAGES, limit)
        return [r['image_url'] for r in rows]

    async def mark_dead(self, urls: list[str]):
        """
        Mark URLs as dead (404/Invalid) in the cache.

        Args:
            urls (list[str]): List of dead URLs.
        """
        if urls: 
            await self.db.execute(MARK_IMAGES_DEAD, urls)

    async def update_validation(self, urls: list[str]):
        """
        Update the 'last_validated' timestamp for healthy URLs.

        Args:
            urls (list[str]): List of valid URLs.
        """
        if urls: 
            await self.db.execute(UPDATE_VALIDATION_TIME, urls)