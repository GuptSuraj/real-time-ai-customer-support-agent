from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "sqlite:///./support.db"
    app_origin: str = "http://localhost:3000"
    session_secret: str = Field(default="local-development-only-change-before-sharing-123", min_length=32)
    cookie_secure: bool = False
    demo_mode: bool = True
    livekit_url: str = ""
    livekit_api_key: str = ""
    livekit_api_secret: str = ""
    agent_name: str = "commerce-support"
    enable_fault_injection: bool = False


@lru_cache
def settings():
    return Settings()
