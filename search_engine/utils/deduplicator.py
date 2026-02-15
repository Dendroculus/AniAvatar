import hashlib
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode
from ..database.models import ImageResult 

class URLDeduplicator:
    """
    Utility for normalizing URLs and removing duplicate images from a list.
    """
    TRACKING_PARAMS = {
        "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", 
        "ref", "source", "fbclid", "gclid", "epik"
    }
    
    @staticmethod
    def normalize_url(url: str) -> str:
        """
        Normalize a URL to ensure stable deduplication.
        
        Actions:
        - Force HTTPS scheme.
        - Lowercase netloc (domain).
        - Strip tracking parameters.
        - Remove trailing slash.
        """
        try:
            parsed = urlparse(url)
            query_params = parse_qsl(parsed.query)
            filtered = sorted([(k, v) for k, v in query_params if k.lower() not in URLDeduplicator.TRACKING_PARAMS])
            
            # Force HTTPS for consistency
            scheme = "https" if parsed.scheme in ("http", "https") else parsed.scheme.lower()
            
            return urlunparse((
                scheme, 
                parsed.netloc.lower(), 
                parsed.path.rstrip("/"), 
                parsed.params, 
                urlencode(filtered), 
                parsed.fragment
            ))
        except Exception:
            return url

    @staticmethod
    def deduplicate(images: list[ImageResult]) -> list[ImageResult]:
        """
        Remove duplicate images based on their normalized URL hash.
        
        Args:
            images (list[ImageResult]): The list of images to process.

        Returns:
            list[ImageResult]: A list of unique images.
        """
        seen = set()
        unique = []
        for img in images:
            h = hashlib.md5(URLDeduplicator.normalize_url(img.image_url).encode()).hexdigest()
            if h not in seen:
                seen.add(h)
                unique.append(img)
        return unique