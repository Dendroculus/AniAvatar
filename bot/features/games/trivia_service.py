"""Trivia data loading and balanced question selection."""

import asyncio
import json
import logging
import random
from abc import ABC, abstractmethod
from itertools import cycle
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class TriviaLoader(ABC):
    """
    Abstract interface for loading trivia questions.
    Allows swapping the underlying data source (JSON, DB, API) without changing game logic.
    """

    @abstractmethod
    async def load_data(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        Load trivia questions and return them in a normalized dictionary format:
        {'CategoryName': [{'question': '...', 'answer': '...', 'options': []}, ...]}
        """
        pass


class JsonTriviaLoader(TriviaLoader):
    """
    Concrete implementation of TriviaLoader for local JSON files.
    """

    def __init__(self, file_path: str | Path):
        self.file_path = Path(file_path)

    async def load_data(self) -> Dict[str, List[Dict[str, Any]]]:
        def _read_file():
            try:
                with open(self.file_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except FileNotFoundError:
                logger.warning("Trivia file not found: %s", self.file_path)
                return {}
            except json.JSONDecodeError:
                logger.error("Invalid JSON in trivia file: %s", self.file_path)
                return {}

        # Offload blocking I/O to executor
        data = await asyncio.to_thread(_read_file)

        # Normalize structure to Dict[str, List]
        if isinstance(data, dict):
            return data
        elif isinstance(data, list):
            return {"Mixed": data}
        else:
            return {"Mixed": []}


class TriviaService:
    """Load trivia data and select balanced, non-repeating questions."""

    def __init__(self, loader: TriviaLoader):
        self.loader = loader
        self.trivia_dict: Dict[str, List[Dict[str, Any]]] = {"Mixed": []}
        self.used_questions: set[str] = set()

    async def load(self) -> int:
        """Load trivia data and return the total question count."""
        self.trivia_dict = await self.loader.load_data()
        return sum(len(questions) for questions in self.trivia_dict.values())

    def get_balanced_questions(self, num_questions: int):
        """
        Return up to `num_questions` sampled across available categories.

        Args:
            num_questions (int): The number of unique questions to retrieve.

        Returns:
            list: A list of question dictionaries.
        """
        titles = list(self.trivia_dict.keys())
        if not titles:
            return []

        random.shuffle(titles)
        questions = []
        title_cycle = cycle(titles)

        # Safety: avoid infinite loop if no questions exist
        total_available = sum(len(qs) for qs in self.trivia_dict.values())
        if total_available == 0:
            return []

        while len(questions) < num_questions:
            title = next(title_cycle)
            available = [
                q
                for q in self.trivia_dict[title]
                if q["question"] not in self.used_questions
            ]
            if available:
                q = random.choice(available)
                self.used_questions.add(q["question"])
                questions.append(q)

            # If we've used all questions, clear history to allow repeats
            if len(self.used_questions) >= total_available:
                self.used_questions.clear()

        return questions
