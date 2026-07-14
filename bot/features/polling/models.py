"""Polling data-transfer models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional


@dataclass
class PollData:
    """
    Data transfer object for creating or updating a poll.
    """

    message_id: int
    guild_id: int
    channel_id: int
    author_id: int
    question: str
    options: List[str]
    end_time: Optional[datetime]
