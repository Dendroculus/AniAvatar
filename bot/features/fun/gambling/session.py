"""Gambling session counters, cooldowns, and active views."""

from __future__ import annotations

import time
from typing import Optional

from bot.config.configs import FunConstants as FC
from bot.features.fun.gambling.view import GambleView


class GamblingSessionMixin:
    def _cooldown_remaining(self, guild_id: int, user_id: int) -> int:
        """
        Calculate remaining cooldown seconds for a user's gamble session.

        This tracks the specific 'session cooldown' triggered after max attempts,
        separate from the standard command rate limit.
        """
        key = (guild_id, user_id)
        now = time.time()
        expires = self._gamble_cooldowns.get(key)
        if expires and expires > now:
            return int(expires - now)
        return 0

    def _start_session_cooldown(self, guild_id: int, user_id: int) -> None:
        """Start the gamble session cooldown and reset the attempt counter."""
        key = (guild_id, user_id)
        self._gamble_cooldowns[key] = time.time() + FC.GAMBLE_COOLDOWN_SECONDS
        self._gamble_counts.pop(key, None)

    def _count_attempt(self, guild_id: int, user_id: int) -> int:
        """Increment and return the gamble attempt count for the current session."""
        key = (guild_id, user_id)
        new_val = self._gamble_counts.get(key, 0) + 1
        self._gamble_counts[key] = new_val
        return new_val

    def _clear_attempts(self, guild_id: int, user_id: int) -> None:
        """Clear the gamble attempt counter for a user."""
        self._gamble_counts.pop((guild_id, user_id), None)

    def _set_active_view(
        self, guild_id: int, user_id: int, view: Optional[GambleView]
    ) -> None:
        """
        Register or remove the active GambleView for a user.

        Ensures we can locate the specific view instance later to update
        buttons or balances.
        """
        self.active_views.setdefault(guild_id, {})
        if view is None:
            self.active_views[guild_id].pop(user_id, None)
        else:
            self.active_views[guild_id][user_id] = view

    def _get_active_view(self, guild_id: int, user_id: int) -> Optional[GambleView]:
        """Retrieve the active GambleView for a user, if one exists."""
        return self.active_views.get(guild_id, {}).get(user_id)
