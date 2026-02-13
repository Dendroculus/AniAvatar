from dataclasses import dataclass
from datetime import datetime

@dataclass(frozen=True)
class ImageResult:
    image_url: str
    source: str
    thumbnail_url: str | None = None
    title: str | None = None

@dataclass(frozen=True)
class CachedImage:
    id: int
    query: str
    image_url: str
    source: str
    thumbnail_url: str | None
    title: str | None
    created_at: datetime
    is_dead: bool