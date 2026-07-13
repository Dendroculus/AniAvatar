"""Public progression image-renderer composition."""

from __future__ import annotations

from typing import Dict, Tuple

from bot.features.progression.rendering.leaderboard_renderer import (
    LeaderboardRendererMixin,
)
from bot.features.progression.rendering.profile_renderer import (
    ProfileRendererMixin,
)
from bot.features.progression.rendering.resources import (
    AssetLoader,
    FontManager,
)


class CardDrawer(
    ProfileRendererMixin,
    LeaderboardRendererMixin,
):
    """Coordinate profile and leaderboard image rendering."""

    def __init__(self, cache_size=200):
        self.fonts = FontManager()
        self.assets = AssetLoader()
        self._cache_size = cache_size
        self._leaderboard_cache: Dict[str, Tuple[float, bytes]] = {}


class ImageRenderer(CardDrawer):
    """Backward-compatible renderer name."""

    pass
