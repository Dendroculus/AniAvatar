"""Backward-compatible exports for anime utility helpers."""

from .anime_characters import (
    char_has_anime_media,
    fetch_character_by_name,
    fetch_random_character,
)
from .anime_quiz import (
    build_character_select_options,
    get_fallback_wrong_options,
    get_wrong_names,
)
from .anime_search import search_anime

__all__ = [
    "build_character_select_options",
    "char_has_anime_media",
    "fetch_character_by_name",
    "fetch_random_character",
    "get_fallback_wrong_options",
    "get_wrong_names",
    "search_anime",
]
