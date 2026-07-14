"""Pure polling state parsing and result calculations."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple


def _parse_options(raw) -> list:
    """Robustly parse stored poll options."""
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        return list(raw)
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, (list, tuple)):
                return list(parsed)
        except Exception:
            return []
    return []


def _parse_votes(raw) -> Dict[str, list]:
    """Parse persisted votes into a dictionary mapping option -> list of user ids."""
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return {str(k): list(v) for k, v in raw.items()}
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return {str(k): list(v) for k, v in parsed.items()}
        except Exception:
            return {}
    return {}


def _sanitize_votes(options: list, votes_raw: Dict[str, list]) -> Dict[str, list[int]]:
    """Ensure votes are keyed by option strings and values are lists of integer user IDs."""
    for opt in options:
        votes_raw.setdefault(opt, [])
    sanitized: Dict[str, list[int]] = {}
    for opt, uids in votes_raw.items():
        out = []
        if isinstance(uids, (list, tuple)):
            for uid in uids:
                try:
                    out.append(int(uid))
                except Exception:
                    continue
        else:
            try:
                out.append(int(uids))
            except Exception:
                pass
        sanitized[str(opt)] = out
    return sanitized


def _remaining_seconds(end_time: Optional[float]) -> Optional[int]:
    """Compute remaining seconds until end_time (UNIX timestamp) relative to UTC now."""
    if end_time is None:
        return None
    try:
        return int(float(end_time) - datetime.now(timezone.utc).timestamp())
    except Exception:
        return None


def _compute_results_from_votes(
    votes_raw: Dict[str, list[int]],
) -> Tuple[dict[str, int], list[str]]:
    """Compute counts per option and determine winner(s)."""
    counts: dict[str, int] = {}
    if not votes_raw:
        return counts, []
    for opt, uids in votes_raw.items():
        try:
            size = len(uids) if uids is not None else 0
        except TypeError:
            size = 0
        counts[str(opt)] = int(size)
    winners = []
    if counts:
        max_votes = max(counts.values())
        winners = [opt for opt, c in counts.items() if c == max_votes]
    return counts, winners


def _is_expired(remaining_seconds: Optional[int]) -> bool:
    """Return True if remaining_seconds indicates the poll should be considered expired."""
    return remaining_seconds is not None and remaining_seconds <= 0
