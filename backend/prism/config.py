"""Application configuration via Pydantic Settings."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration loaded from environment / .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Database ──
    database_url: str = "sqlite:///./prism.db"

    # ── Git mirror storage ──
    git_mirror_dir: str = "./data/git-mirrors"

    # ── LLM ──
    llm_provider: str = "ollama"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5-coder:7b"

    # ── Server ──
    backend_host: str = "127.0.0.1"
    backend_port: int = 8000
    frontend_url: str = "http://localhost:3000"

    # ── Security ──
    webhook_secret: str = "change-me-to-a-random-secret"

    # ── Integrations ──
    github_app_id: str = ""
    github_private_key_path: str = ""
    github_webhook_secret: str = ""
    # Personal Access Token for outbound GitHub API calls (approve, merge, fetch PR data)
    github_token: str = ""

    coverity_api_url: str = ""
    coverity_api_token: str = ""

    blackduck_url: str = ""
    blackduck_api_token: str = ""

    # ── Worker ──
    worker_concurrency: int = 2
    job_timeout_seconds: int = 600

    # ── Auto-sync / polling ──
    # How often (seconds) PRISM polls each connected repository for new commits.
    # Set to 0 to disable polling entirely and rely only on webhooks.
    # Default: 300 seconds (5 minutes) — lightweight, just a git fetch + SHA compare.
    sync_interval_seconds: int = 300
    # Maximum repositories to check per sync pass (avoids thundering-herd on many repos)
    sync_batch_size: int = 10

    # ── Rate limiting ──
    rate_limit_per_minute: int = 60

    # ── Logging ──
    log_level: str = "INFO"

    @field_validator("database_url")
    @classmethod
    def _ensure_async_driver(cls, v: str) -> str:
        """Allow plain sqlite:/// — we'll convert to aiosqlite where needed."""
        return v

    @property
    def git_mirror_path(self) -> Path:
        p = Path(self.git_mirror_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def is_sqlite(self) -> bool:
        return "sqlite" in self.database_url

    @property
    def async_database_url(self) -> str:
        """Return an async-compatible database URL."""
        if self.database_url.startswith("sqlite:///"):
            path = self.database_url[len("sqlite:///"):]
            return f"sqlite+aiosqlite:///{path}"
        if self.database_url.startswith("postgresql://"):
            return self.database_url.replace(
                "postgresql://", "postgresql+asyncpg://", 1
            )
        return self.database_url


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reload_settings() -> Settings:
    """Clear cache and reload settings (useful for tests)."""
    get_settings.cache_clear()
    return get_settings()
