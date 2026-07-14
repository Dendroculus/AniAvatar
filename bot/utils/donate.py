"""Backward-compatible donation UI imports.

Donation views now live under ``bot.features.trading.views``.
"""

from bot.features.trading.views.donate import (
    DonateAmountModal as DonateAmountModal,
)
from bot.features.trading.views.donate import (
    DonateSelect as DonateSelect,
)
from bot.features.trading.views.donate import (
    DonateView as DonateView,
)

__all__ = [
    "DonateAmountModal",
    "DonateSelect",
    "DonateView",
]
