from functools import lru_cache
from typing import Literal
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
    google_api_key: str = ""
    knowledge_base_dir: str = "knowledge_base"
    embedding_model: Literal["gemini-embedding-2"] = "gemini-embedding-2"
    embedding_dimension: int = Field(default=768, ge=768, le=768)
    rag_embedding_timeout_seconds: float = Field(default=1.5, ge=0.1, le=3)
    rag_top_k: int = Field(default=5, ge=1, le=10)
    rag_candidate_limit: int = Field(default=24, ge=5, le=100)
    rag_min_similarity: float = Field(default=0.60, ge=-1, le=1)
    rag_max_context_chars: int = Field(default=7000, ge=1000, le=14000)


@lru_cache
def settings():
    return Settings()
