"""Backward-compatible gambling UI facade.

New code should import from
``bot.features.fun.gambling``.
"""

from bot.features.fun.gambling import GambleView

__all__ = ["GambleView"]
