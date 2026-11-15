"""Application settings, loaded from environment variables and `.env`."""

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Repo-root .env when running from backend/, or a local one.
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "HireFlow"
    log_level: str = "INFO"

    database_url: str = "postgresql+asyncpg://hireflow:hireflow@localhost:5432/hireflow"

    anthropic_api_key: SecretStr | None = None
    anthropic_model: str = "claude-opus-5-5"
    anthropic_effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    anthropic_max_tokens: int = 16000
    # Server-side refusal fallback (beta). Routes declined requests to a fallback model.
    anthropic_refusal_fallback: bool = True

    max_upload_bytes: int = 5 * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
