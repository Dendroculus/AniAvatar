"""Backward-compatible trading UI imports.

Trading views now live under ``bot.features.trading.views``.
"""

from bot.features.trading.views import (
    CloseButton as CloseButton,
)
from bot.features.trading.views import (
    InventorySelect as InventorySelect,
)
from bot.features.trading.views import (
    InventoryView as InventoryView,
)
from bot.features.trading.views import (
    ShopSelect as ShopSelect,
)
from bot.features.trading.views import (
    ShopView as ShopView,
)
from bot.features.trading.views import (
    format_coins as format_coins,
)

__all__ = [
    "CloseButton",
    "InventorySelect",
    "InventoryView",
    "ShopSelect",
    "ShopView",
    "format_coins",
]
