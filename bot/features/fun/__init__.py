"""Entertainment feature services."""

from .gambling import GamblingMixin
from .quotes import QuoteManager
from .responses import ResponseMixin
from .waifu import (
    WaifuAPIError,
    WaifuClient,
    WaifuImageMissing,
)

__all__ = [
    "GamblingMixin",
    "QuoteManager",
    "ResponseMixin",
    "WaifuAPIError",
    "WaifuClient",
    "WaifuImageMissing",
]
