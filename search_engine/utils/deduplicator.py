import hashlib
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode
from ..database.models import ImageResult 

class URLDeduplicator:
    TRACKING_PARAMS = {
        "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", 
        "ref", "source", "fbclid", "gclid", "epik"
    }
    
    @staticmethod
    def normalize_url(url: str) -> str:
        try:
            parsed = urlparse(url)
            query_params = parse_qsl(parsed.query)
            filtered = sorted([(k, v) for k, v in query_params if k.lower() not in URLDeduplicator.TRACKING_PARAMS])
            return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"), parsed.params, urlencode(filtered), parsed.fragment))
        except Exception:
            return url

    @staticmethod
    def deduplicate(images: list[ImageResult]) -> list[ImageResult]:
        seen = set()
        unique = []
        for img in images:
            h = hashlib.md5(URLDeduplicator.normalize_url(img.image_url).encode()).hexdigest()
            if h not in seen:
                seen.add(h)
                unique.append(img)
        return unique