"""Durable provider operations, allowance, and immutable retrieval releases."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .models import Base


def now() -> datetime:
    return datetime.now(UTC)


class SpendEntry(Base):
    __tablename__ = "spend_entries"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String(64))
    purpose: Mapped[str] = mapped_column(String(32))
    operation: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), default="RESERVED")
    reserved_inr: Mapped[float] = mapped_column(Float)
    charged_inr: Mapped[float] = mapped_column(Float, default=0)
    charged_usd: Mapped[float] = mapped_column(Float, default=0)
    price_table: Mapped[dict[str, Any]] = mapped_column(JSONB)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AIRun(Base):
    __tablename__ = "ai_runs"
    workspace_id: Mapped[str] = mapped_column(String(64), default="public-demo", server_default="public-demo", index=True)
    __table_args__ = (UniqueConstraint("user_id", "request_key"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String(64))
    request_key: Mapped[str] = mapped_column(String(120))
    analysis_id: Mapped[str] = mapped_column(String(64))
    identity: Mapped[str] = mapped_column(String(80))
    task: Mapped[str] = mapped_column(String(32))
    question: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32))
    packet: Mapped[dict[str, Any]] = mapped_column(JSONB)
    configuration: Mapped[dict[str, Any]] = mapped_column(JSONB)
    attempts: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    reservation_id: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CorpusRelease(Base):
    __tablename__ = "corpus_releases"
    workspace_id: Mapped[str] = mapped_column(String(64), default="public-demo", server_default="public-demo", index=True)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    digest: Mapped[str] = mapped_column(String(80))
    cutoff: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    cards: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class EmbeddingArtifact(Base):
    __tablename__ = "embedding_artifacts"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    model: Mapped[str] = mapped_column(String(120))
    dimensions: Mapped[int] = mapped_column(Integer)
    preprocessing_version: Mapped[str] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(Text)
    vector: Mapped[Any] = mapped_column(Vector(512))
    provider_usage: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class SpendingAllocation(Base):
    __tablename__ = "spending_allocations"
    purpose: Mapped[str] = mapped_column(String(32), primary_key=True)
    ceiling_inr: Mapped[float] = mapped_column(Float)


class RetrievalRun(Base):
    __tablename__ = "retrieval_runs"
    workspace_id: Mapped[str] = mapped_column(String(64), default="public-demo", server_default="public-demo", index=True)
    __table_args__ = (UniqueConstraint("user_id", "request_key"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String(64))
    request_key: Mapped[str] = mapped_column(String(120))
    identity: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(32))
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
