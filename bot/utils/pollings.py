"""Backward-compatible polling UI facade.

New code should import from ``bot.features.polling``.
"""

from bot.features.polling.domain import (
    _compute_results_from_votes,
    _is_expired,
    _parse_options,
    _parse_votes,
    _remaining_seconds,
    _sanitize_votes,
)
from bot.features.polling.recovery import reconstruct_poll
from bot.features.polling.views import (
    AddOptionModal,
    PollInputModal,
    PollView,
)

__all__ = [
    "AddOptionModal",
    "PollInputModal",
    "PollView",
    "_compute_results_from_votes",
    "_is_expired",
    "_parse_options",
    "_parse_votes",
    "_remaining_seconds",
    "_sanitize_votes",
    "reconstruct_poll",
]
