from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class EngineSettings(BaseSettings):
    """
    Configuration settings for the Search Engine.
    
    Loads values from environment variables or .env file.
    
    Attributes:
        discord_token (str): The Discord Bot Token.
        database_url (str): PostgreSQL connection string.
        google_api_key (str): API Key for Google Custom Search.
        google_search_engine_id (str): Search Engine ID (CX) for Google.
        engine_log_level (str): Logging level (default: INFO).
        cache_ttl_hours (int): Hours before cached images are considered stale.
        max_pool_size (int): Max database connection pool size.
        min_pool_size (int): Min database connection pool size.
    """
    discord_token: str
    database_url: str
    google_api_key: str = Field(alias="GOOGLE_API_KEY")
    google_search_engine_id: str = Field(alias="SEARCH_ENGINE_ID")
    
    engine_log_level: str = "INFO"
    cache_ttl_hours: int = 24
    max_pool_size: int = 20
    min_pool_size: int = 5
    
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = EngineSettings()