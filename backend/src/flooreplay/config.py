"""Application settings. Environment over defaults, never secrets in code."""

from __future__ import annotations

from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FLOORREPLAY_", env_file=".env", allow_inf_nan=False)

    database_url: str = "postgresql+psycopg://localhost:5433/flooreplay"
    mode: Literal["local", "public"] = "local"
    build_id: str = "dev"
    replay_budget_seconds: float = Field(default=10.0, gt=0)
    suite_budget_seconds: float = Field(default=30.0, gt=0)
    max_concurrent_executions: int = Field(default=2, ge=1)
    openai_api_key: str = ""
    openai_generation_model: str = "gpt-4.1-mini-2025-04-14"
    openai_embedding_model: str = "text-embedding-3-small"
    openai_embedding_dimensions: int = 512
    anthropic_api_key: str = ""
    openai_inr_per_usd: float = Field(default=90.0, gt=0)
    # Public-demo execution limits. The comparison suite executes 64 replays,
    # so it stays a local-owner action; single replays are rate limited per
    # client (in-memory, per process — resets on restart, which is honest for
    # a single-instance demo host).
    public_replays_per_hour: int = Field(default=20, ge=1)
    cors_origins: list[str] = []

    @field_validator("cors_origins")
    @classmethod
    def exact_origins(cls, origins: list[str]) -> list[str]:
        for origin in origins:
            url = urlsplit(origin)
            local_http = url.scheme == "http" and url.hostname in {"localhost", "127.0.0.1"}
            if (url.scheme != "https" and not local_http) or not url.netloc or "*" in origin or url.username or url.password or url.path or url.query or url.fragment:
                raise ValueError("CORS origins must be exact HTTPS origins (localhost HTTP is allowed), without paths or wildcards")
        return origins


settings = Settings()
