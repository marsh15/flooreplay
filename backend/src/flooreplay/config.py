"""Application settings. Environment over defaults, never secrets in code."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FLOORREPLAY_", env_file=".env")

    database_url: str = "postgresql+psycopg://localhost:5433/flooreplay"
    mode: str = "local"  # "local" (owner) or "public" (curated demo)
    build_id: str = "dev"
    replay_budget_seconds: float = 10.0
    suite_budget_seconds: float = 30.0
    max_concurrent_executions: int = 2
    openai_api_key: str = ""
    allow_paid_parser: bool = False
    local_model: str = "qwen3:1.7b"
    # Public-demo execution limits. The comparison suite executes 64 replays,
    # so it stays a local-owner action; single replays are rate limited per
    # client (in-memory, per process — resets on restart, which is honest for
    # a single-instance demo host).
    public_replays_per_hour: int = 20
    cors_origins: list[str] = []


settings = Settings()
