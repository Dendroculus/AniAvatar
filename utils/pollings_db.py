import asyncpg
import json
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Dict, Any
from constants.configs import PollingConstants as POLCONST

"""
poll_db.py

Purpose
-------
Isolated database layer for the polling subsystem.

Responsibilities:
- Manage SQL schema (init_db)
- CRUD operations for Polls and Votes
- Data Transfer Objects (PollData)
- Database connection safety (timeouts)

This module is dependency-free regarding Discord.py (except for type hinting context if needed),
ensuring clear separation of concerns.
"""

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

async def _set_stmt_timeout(conn: asyncpg.Connection, ms: int = POLCONST.SAFETY_TIMEOUT_MS):
    """
    Apply a per-connection statement timeout to avoid runaway queries.
    """
    try:
        await conn.execute(f"SET LOCAL statement_timeout = {ms}")
    except Exception:
        pass

def _json_dumps(value: Any) -> str:
    """
    Serialize Python objects to JSON text for deterministic storage/inspection.
    """
    return json.dumps(value, ensure_ascii=False)

#  Schema Initialization  #

async def init_db(pool: asyncpg.Pool):
    """
    Initialize the polls and poll_votes tables if they don't exist.
    """
    async with pool.acquire() as conn:
        await _set_stmt_timeout(conn)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS polls (
                message_id BIGINT PRIMARY KEY,
                guild_id   BIGINT,
                channel_id BIGINT,
                author_id  BIGINT,
                question   TEXT,
                options    JSONB DEFAULT '[]'::jsonb,
                end_time   DOUBLE PRECISION,
                ended      BOOLEAN DEFAULT FALSE,
                winners    JSONB,
                counts     JSONB,
                total_votes INTEGER,
                created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS poll_votes (
                message_id BIGINT REFERENCES polls(message_id) ON DELETE CASCADE,
                user_id    BIGINT NOT NULL,
                option_idx INTEGER NOT NULL,
                PRIMARY KEY (message_id, user_id)
            )
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS poll_votes_option_idx
            ON poll_votes (message_id, option_idx)
        """)

#  Persistence helpers  #

async def save_active_poll(pool: asyncpg.Pool, poll_data: PollData):
    """
    Insert or update poll metadata (no vote blob).
    """
    async with pool.acquire() as conn:
        await _set_stmt_timeout(conn)
        await conn.execute(
            """
            INSERT INTO polls (
                message_id, guild_id, channel_id, author_id,
                question, options, end_time, ended
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, FALSE)
            ON CONFLICT (message_id) DO UPDATE SET
                guild_id   = EXCLUDED.guild_id,
                channel_id = EXCLUDED.channel_id,
                author_id  = EXCLUDED.author_id,
                question   = EXCLUDED.question,
                options    = EXCLUDED.options,
                end_time   = EXCLUDED.end_time,
                ended      = FALSE
            """,
            poll_data.message_id,
            poll_data.guild_id,
            poll_data.channel_id,
            poll_data.author_id,
            poll_data.question,
            _json_dumps(poll_data.options),
            poll_data.end_time.timestamp() if poll_data.end_time else None,
        )

async def upsert_vote(pool: asyncpg.Pool, message_id: int, user_id: int, option_idx: int):
    """
    Insert or update a single user's vote (constant-time write).
    """
    async with pool.acquire() as conn:
        await _set_stmt_timeout(conn)
        await conn.execute(
            """
            INSERT INTO poll_votes (message_id, user_id, option_idx)
            VALUES ($1, $2, $3)
            ON CONFLICT (message_id, user_id)
            DO UPDATE SET option_idx = EXCLUDED.option_idx
            """,
            message_id, user_id, option_idx
        )

async def delete_vote(pool: asyncpg.Pool, message_id: int, user_id: int):
    """
    Remove a user's vote for a poll.
    """
    async with pool.acquire() as conn:
        await _set_stmt_timeout(conn)
        await conn.execute(
            "DELETE FROM poll_votes WHERE message_id = $1 AND user_id = $2",
            message_id, user_id
        )

async def load_active_polls(pool: asyncpg.Pool):
    """
    Return active polls plus their votes aggregated from poll_votes.
    """
    query = """
        SELECT
            message_id,
            guild_id,
            channel_id,
            author_id,
            question,
            options,
            end_time,
            ended
        FROM polls
        WHERE ended = FALSE
    """
    async with pool.acquire() as conn:
        await _set_stmt_timeout(conn)
        poll_rows = await conn.fetch(query)
        if not poll_rows:
            return []

        message_ids = [r["message_id"] for r in poll_rows]
        vote_rows = await conn.fetch(
            "SELECT message_id, user_id, option_idx FROM poll_votes WHERE message_id = ANY($1)",
            message_ids
        )

    votes_by_message: Dict[int, Dict[str, set[int]]] = {mid: {} for mid in message_ids}
    options_map: Dict[int, List[str]] = {r["message_id"]: json.loads(r["options"]) for r in poll_rows}
    
    for row in vote_rows:
        mid = row["message_id"]
        option_idx = row["option_idx"]
        user_id = row["user_id"]
        opts = options_map.get(mid, [])
        if 0 <= option_idx < len(opts):
            label = opts[option_idx]
            votes_by_message[mid].setdefault(label, set()).add(user_id)

    result = []
    for r in poll_rows:
        mid = r["message_id"]
        votes = votes_by_message.get(mid, {})
        for opt in options_map.get(mid, []):
            votes.setdefault(opt, set())
            
        item = dict(r)
        item["options"] = options_map[mid]
        item["votes"] = votes
        result.append(item)

    return result

async def purge_finished_polls(pool: asyncpg.Pool):
    """
    Delete polls that have ended.
    """
    async with pool.acquire() as conn:
        await _set_stmt_timeout(conn)
        await conn.execute("DELETE FROM polls WHERE ended = TRUE")

async def record_poll_result(pool: asyncpg.Pool, message_id, winners, counts, total_votes):
    """
    Mark a poll as ended and persist winners/counts/total_votes.
    """
    async with pool.acquire() as conn:
        await _set_stmt_timeout(conn)
        await conn.execute(
            """
            UPDATE polls
               SET winners = $1,
                   counts = $2,
                   total_votes = $3,
                   ended = TRUE
             WHERE message_id = $4
            """,
            _json_dumps(winners),
            _json_dumps(counts),
            total_votes,
            message_id,
        )