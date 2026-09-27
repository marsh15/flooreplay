"""Persistence model: immutable artifacts plus replay attempts.

Relational columns carry identity, relationships, status, and uniqueness;
JSONB carries the typed immutable payloads and structured reports. Source
payloads are not the whole database model. Published artifacts are never
updated: corrections create new revisions, and nothing in the application
deletes a referenced artifact.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _uuid() -> str:
    return str(uuid.uuid4())


class CatalogRevision(Base):
    __tablename__ = "catalog_revisions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    content_digest: Mapped[str] = mapped_column(String(80), unique=True)


class SourceSnapshot(Base):
    __tablename__ = "source_snapshots"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    source_system: Mapped[str] = mapped_column(String(64))
    scope: Mapped[str] = mapped_column(Text)
    declared_evidence_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    coverage_complete: Mapped[bool] = mapped_column(Boolean)
    content_digest: Mapped[str] = mapped_column(String(80))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)


class ExecutionConfiguration(Base):
    __tablename__ = "execution_configurations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    policy_kind: Mapped[str] = mapped_column(String(32))
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB)
    known_limitation: Mapped[str] = mapped_column(Text, default="")


class ScenarioRevision(Base):
    __tablename__ = "scenario_revisions"

    scenario_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    tags: Mapped[list[str]] = mapped_column(JSONB)
    defect_statement: Mapped[str] = mapped_column(Text)
    event: Mapped[dict[str, Any]] = mapped_column(JSONB)
    decision_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    target: Mapped[dict[str, Any]] = mapped_column(JSONB)
    catalog_revision_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("catalog_revisions.id")
    )
    pinned_snapshot_ids: Mapped[list[str]] = mapped_column(JSONB)


class ExpectationRevision(Base):
    __tablename__ = "expectation_revisions"
    __table_args__ = (UniqueConstraint("scenario_id", "revision", "configuration_id", name="uq_expectation"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    scenario_id: Mapped[str] = mapped_column(String(64))
    revision: Mapped[int] = mapped_column(Integer)
    configuration_id: Mapped[str] = mapped_column(String(64))
    assertions: Mapped[dict[str, Any]] = mapped_column(JSONB)


class ReplayAttempt(Base):
    __tablename__ = "replay_attempts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    idempotency_key: Mapped[str] = mapped_column(String(120), unique=True)
    scenario_id: Mapped[str] = mapped_column(String(64))
    scenario_revision: Mapped[int] = mapped_column(Integer)
    configuration_id: Mapped[str] = mapped_column(String(64))
    lifecycle: Mapped[str] = mapped_column(String(16), default="RUNNING", index=True)
    domain_outcome: Mapped[str | None] = mapped_column(String(32), nullable=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    expectation_verdict: Mapped[str | None] = mapped_column(String(16), nullable=True)
    expectation_failures: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    context_digest: Mapped[str | None] = mapped_column(String(80), nullable=True)
    manifest_digest: Mapped[str | None] = mapped_column(String(80), nullable=True)
    request_payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(tz=UTC)
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
