from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class EngineSettings(BaseSettings):
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