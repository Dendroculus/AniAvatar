from dataclasses import dataclass
from datetime import datetime

@dataclass(frozen=True)
class ImageResult:
    """
    Represents a single image found by a search worker.
    
    Attributes:
        image_url (str): Direct link to the image.
        source (str): Origin of the image (e.g., "pinterest", "google").
        thumbnail_url (str | None): Optional link to a thumbnail/preview.
        title (str | None): Optional title or description of the image.
    """
    image_url: str
    source: str
    thumbnail_url: str | None = None
    title: str | None = None

@dataclass(frozen=True)
class CachedImage:
    """
    Represents an image retrieved from the database cache.
    
    Attributes:
        id (int): Database primary key.
        query (str): The search query associated with this image.
        image_url (str): Direct link to the image.
        source (str): Origin source.
        thumbnail_url (str | None): Thumbnail link.
        title (str | None): Image title.
        created_at (datetime): Timestamp when cached.
        is_dead (bool): True if the link was found to be broken.
    """
    id: int
    query: str
    image_url: str
    source: str
    thumbnail_url: str | None
    title: str | None
    created_at: datetime
    is_dead: bool