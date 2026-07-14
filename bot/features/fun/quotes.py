"""Local quote loading and balanced quote selection."""

from __future__ import annotations

import asyncio
import json
import random
from itertools import cycle
from typing import Any, Dict, List

from bot.config.paths import DATA_PATH


class QuoteManager:
    """
    Manages loading and retrieving anime quotes with balancing logic.
    """

    def __init__(self, bot):
        self.bot = bot
        self.data_path = DATA_PATH / "quotes.json"
        self.quotes_dict: Dict[str, List[Dict[str, str]]] = {"Mixed": []}
        self.used_quotes = set()
        self.lock = asyncio.Lock()

    async def load_quotes(self):
        """
        Load quotes from JSON file asynchronously to avoid blocking the event loop.
        """

        def _read_json():
            try:
                with open(self.data_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except FileNotFoundError:
                return {}

        data = await asyncio.to_thread(_read_json)

        if isinstance(data, dict):
            self.quotes_dict = data
        elif isinstance(data, list):
            self.quotes_dict = {"Mixed": data}
        else:
            self.quotes_dict = {"Mixed": []}

    async def get_balanced_quotes(self, num_quotes: int) -> List[Dict[str, Any]]:
        """
        Select a balanced set of random quotes, avoiding immediate repetition.
        Thread-safe.

        Args:
            num_quotes (int): Number of quotes to retrieve.

        Returns:
            list: A list of quote dictionaries containing 'anime', 'character', and 'quote'.
        """
        async with self.lock:
            titles = list(self.quotes_dict.keys())
            if not titles:
                return []

            random.shuffle(titles)
            quotes = []
            title_cycle = cycle(titles)

            while len(quotes) < num_quotes:
                title = next(title_cycle)
                cat_list = self.quotes_dict.get(title, [])
                available = [
                    q
                    for q in cat_list
                    if q.get("quote") and q["quote"] not in self.used_quotes
                ]
                if available:
                    q = random.choice(available)
                    self.used_quotes.add(q["quote"])
                    quotes.append({"anime": title, **q})

                total_quotes = sum(len(qs) for qs in self.quotes_dict.values())
                if total_quotes and len(self.used_quotes) >= total_quotes:
                    self.used_quotes.clear()

            return quotes
