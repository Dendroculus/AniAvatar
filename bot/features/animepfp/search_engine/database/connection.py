import asyncpg
import logging

logger = logging.getLogger(__name__)

SCHEMA_DDL = """
-- Search history for user behavior analysis
CREATE TABLE IF NOT EXISTS search_history (
    id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    query TEXT NOT NULL,
    searched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_search_history_user ON search_history(user_id);
CREATE INDEX IF NOT EXISTS idx_search_history_query ON search_history(query);

-- Image cache for fast retrieval (Global Pool)
CREATE TABLE IF NOT EXISTS image_cache (
    id SERIAL PRIMARY KEY,
    query TEXT NOT NULL,
    image_url TEXT NOT NULL,
    source TEXT NOT NULL,
    thumbnail_url TEXT,
    title TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_validated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_dead BOOLEAN DEFAULT FALSE,
    UNIQUE(query, image_url)
);

CREATE INDEX IF NOT EXISTS idx_query_alive ON image_cache(query) WHERE is_dead = FALSE;
CREATE INDEX IF NOT EXISTS idx_cache_validation ON image_cache(last_validated) WHERE is_dead = FALSE;

-- Track which images a user has already seen for a specific query
CREATE TABLE IF NOT EXISTS user_seen_images (
    id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    query TEXT NOT NULL,
    image_url TEXT NOT NULL,
    seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, query, image_url)
);

CREATE INDEX IF NOT EXISTS idx_user_seen_lookup ON user_seen_images(user_id, query);
"""

class DatabasePool:
    """
    Singleton manager for the PostgreSQL connection pool.
    
    Handles initialization, schema creation, and connection acquisition.
    """
    _instance = None
    _pool = None
    
    @classmethod
    async def get_instance(cls, database_url: str, min_size: int = 5, max_size: int = 20):
        """
        Get or create the singleton DatabasePool instance.

        Args:
            database_url (str): The PostgreSQL connection string.
            min_size (int): Minimum connections in the pool.
            max_size (int): Maximum connections in the pool.

        Returns:
            DatabasePool: The active pool instance.
        """
        if cls._instance is None:
            cls._instance = cls()
            await cls._instance.initialize(database_url, min_size, max_size)
        return cls._instance
    
    async def initialize(self, database_url: str, min_size: int, max_size: int):
        """
        Initialize the asyncpg pool and ensure database schema exists.

        Args:
            database_url (str): Connection string.
            min_size (int): Minimum pool size.
            max_size (int): Maximum pool size.
        """
        if self._pool is None:
            logger.info("Creating PostgreSQL connection pool...")
            self._pool = await asyncpg.create_pool(
                database_url, 
                min_size=min_size, 
                max_size=max_size
            )
            logger.info("Verifying database schema...")
            async with self.acquire() as conn:
                await conn.execute(SCHEMA_DDL)
    
    async def close(self):
        """Close the database connection pool gracefully."""
        if self._pool:
            logger.info("Closing database pool...")
            await self._pool.close()
            self._pool = None
            
    def acquire(self):
        """
        Acquire a connection context manager from the pool.
        
        Usage:
            async with db.acquire() as conn:
                await conn.execute(...)
        """
        return self._pool.acquire()
    
    async def execute(self, query: str, *args):
        """
        Execute a SQL statement.

        Args:
            query (str): SQL query string.
            *args: Arguments for query parameters ($1, $2, etc.).

        Returns:
            str: Command status tag (e.g., "INSERT 0 1").
        """
        async with self.acquire() as conn:
            return await conn.execute(query, *args)
    
    async def fetch(self, query: str, *args):
        """
        Fetch multiple rows.

        Args:
            query (str): SQL query string.
            *args: Arguments for query parameters.

        Returns:
            list[asyncpg.Record]: List of database records.
        """
        async with self.acquire() as conn:
            return await conn.fetch(query, *args)