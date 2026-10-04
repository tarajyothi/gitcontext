"""Application settings, loaded from environment variables / .env."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "GitContext"
    app_version: str = "0.1.0"
    database_url: str = "sqlite:///./gitcontext.db"
    workspace_dir: str = "./workspace"
    cors_origins: str = "http://localhost:3000"
    log_level: str = "INFO"
    # "hashing" = local deterministic baseline (no key needed); "openai" = any OpenAI-compatible /embeddings API
    session_days: int = 7
    cookie_secure: bool = False  # set COOKIE_SECURE=true behind HTTPS in production
    max_repos_per_workspace: int = 5  # "free" plan boundary
    max_indexed_bytes: int = 50_000_000
    embedding_provider: str = "hashing"
    embedding_model: str = "text-embedding-3-small"
    embedding_base_url: str = "https://api.openai.com/v1"
    embedding_api_key: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
