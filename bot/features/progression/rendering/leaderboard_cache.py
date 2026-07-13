"""Short-lived in-memory cache for rendered leaderboards."""

from __future__ import annotations

import time
from typing import Optional


class LeaderboardCacheMixin:
    def _get_cached_leaderboard(
        self, cache_key: Optional[str], ttl_seconds: int
    ) -> Optional[bytes]:
        if not cache_key or ttl_seconds <= 0:
            return None
        entry = self._leaderboard_cache.get(cache_key)
        if not entry:
            return None
        ts, payload = entry
        if (time.monotonic() - ts) <= ttl_seconds:
            return payload
        self._leaderboard_cache.pop(cache_key, None)
        return None

    def _set_cached_leaderboard(self, cache_key: Optional[str], payload: bytes) -> None:
        if not cache_key:
            return
        self._leaderboard_cache[cache_key] = (time.monotonic(), payload)
        if len(self._leaderboard_cache) > self._cache_size:
            oldest_key = min(self._leaderboard_cache.items(), key=lambda kv: kv[1][0])[
                0
            ]
            self._leaderboard_cache.pop(oldest_key, None)
