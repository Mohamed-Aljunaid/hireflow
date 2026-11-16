"""Application settings, loaded from environment variables and `.env`."""

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Effort = Literal["low", "medium", "high", "xhigh", "max"]


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

    # Demo/E2E mode: canned responses, no API key needed (app/core/mock_llm.py).
    llm_mock: bool = False
    llm_mock_delay_seconds: float = 0.8

    anthropic_api_key: SecretStr | None = None
    anthropic_model: str = "claude-opus-5-5"
    anthropic_effort: Effort = "medium"
    # Judgement-heavy agents (fit analysis, tailoring, writing, claim checks) run at this effort.
    anthropic_analysis_effort: Effort = "high"
    # Rewrites allowed after a failed claim check before unsupported items are dropped.
    claim_check_max_rewrites: int = 2
    anthropic_max_tokens: int = 16000
    # Server-side refusal fallback (beta). Routes declined requests to a fallback model.
    anthropic_refusal_fallback: bool = True

    max_upload_bytes: int = 5 * 1024 * 1024
    max_job_posting_chars: int = 50_000

    @field_validator("database_url")
    @classmethod
    def _async_driver(cls, url: str) -> str:
        """Hosts (e.g. Render) hand out postgres:// or postgresql:// URLs; SQLAlchemy's
        async engine needs the asyncpg driver named."""
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                return "postgresql+asyncpg://" + url.removeprefix(prefix)
        return url


@lru_cache
def get_settings() -> Settings:
    return Settings()
