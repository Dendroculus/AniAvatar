"""Backward-compatible progression rendering facade.

New code should import from
``bot.features.progression.rendering``.
"""

from bot.features.progression.domain.levels import (
    get_title as _get_title,
    get_title_emoji as _get_title_emoji,
)
from bot.features.progression.rendering.card_drawer import (
    CardDrawer,
    ImageRenderer,
)
from bot.features.progression.rendering.exceptions import (
    AvatarBytesMissing,
    AvatarError,
    AvatarLoadError,
)


def get_title(level: int) -> str:
    """Return the progression title for backward compatibility."""

    return _get_title(level)


def get_title_emoji(level: int):
    """Return the title emoji for backward compatibility."""

    return _get_title_emoji(level)


__all__ = [
    "AvatarBytesMissing",
    "AvatarError",
    "AvatarLoadError",
    "CardDrawer",
    "ImageRenderer",
    "get_title",
    "get_title_emoji",
]
