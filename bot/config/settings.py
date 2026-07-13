"""Environment-backed application settings."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


load_dotenv()


def _optional_int(name: str) -> int | None:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return None
    try:
        return int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer.") from exc


@dataclass(frozen=True, slots=True)
class Settings:
    owner_id: int | None
    discord_token: str | None
    google_api_key: str | None
    search_engine_id: str | None
    database_url: str | None
    redis_url: str | None
    pg_statement_timeout_ms: int

    @classmethod
    def from_environment(cls) -> "Settings":
        timeout_raw = os.getenv("PG_STATEMENT_TIMEOUT_MS", "2000")
        try:
            statement_timeout = int(timeout_raw)
        except ValueError as exc:
            raise RuntimeError("PG_STATEMENT_TIMEOUT_MS must be an integer.") from exc

        return cls(
            owner_id=_optional_int("OWNER_ID"),
            discord_token=os.getenv("DISCORD_TOKEN"),
            google_api_key=os.getenv("GOOGLE_API_KEY"),
            search_engine_id=os.getenv("SEARCH_ENGINE_ID"),
            database_url=os.getenv("DATABASE_URL"),
            redis_url=os.getenv("REDIS_URL"),
            pg_statement_timeout_ms=statement_timeout,
        )

    def validate_runtime(self) -> None:
        missing = [
            name
            for name, value in (
                ("DISCORD_TOKEN", self.discord_token),
                ("DATABASE_URL", self.database_url),
            )
            if not value
        ]
        if missing:
            raise RuntimeError(
                "Missing required environment variables: " + ", ".join(missing)
            )


settings = Settings.from_environment()

OWNER_ID = settings.owner_id or 0
DISCORD_TOKEN = settings.discord_token
GOOGLE_API = settings.google_api_key
GOOGLE_SEARCH_ENGINE = settings.search_engine_id
DATABASE = settings.database_url
REDIS_CACHING = settings.redis_url
