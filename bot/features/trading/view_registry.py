"""Registry for active trading Discord views."""

from __future__ import annotations


class TradingViewRegistry:
    """Track open shop and inventory views by guild and user."""

    def __init__(self) -> None:
        self._shops: dict[int, dict[int, object]] = {}
        self._inventories: dict[int, dict[int, object]] = {}

    def get_shop(self, guild_id: int, user_id: int) -> object | None:
        """Return a user's currently open shop view, if any."""
        return self._shops.get(guild_id, {}).get(user_id)

    def register_shop(self, guild_id: int, user_id: int, view: object) -> None:
        """Register or replace a user's open shop view."""
        self._shops.setdefault(guild_id, {})[user_id] = view

    def remove_shop(self, guild_id: int, user_id: int) -> None:
        """Remove a user's open shop view and empty guild bucket."""
        self._remove(self._shops, guild_id, user_id)

    def get_inventory(self, guild_id: int, user_id: int) -> object | None:
        """Return a user's currently open inventory view, if any."""
        return self._inventories.get(guild_id, {}).get(user_id)

    def register_inventory(self, guild_id: int, user_id: int, view: object) -> None:
        """Register or replace a user's open inventory view."""
        self._inventories.setdefault(guild_id, {})[user_id] = view

    def remove_inventory(self, guild_id: int, user_id: int) -> None:
        """Remove a user's open inventory view and empty guild bucket."""
        self._remove(self._inventories, guild_id, user_id)

    @staticmethod
    def _remove(
        views: dict[int, dict[int, object]],
        guild_id: int,
        user_id: int,
    ) -> None:
        guild_views = views.get(guild_id)
        if guild_views is None:
            return

        guild_views.pop(user_id, None)
        if not guild_views:
            views.pop(guild_id, None)
