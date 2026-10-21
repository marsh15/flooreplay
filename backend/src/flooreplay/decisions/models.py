"""Append-only persistence for v2 decision facts and the source artifacts they came from.

Both tables are guarded in the database: triggers reject UPDATE, DELETE and TRUNCATE, and
CHECK constraints reject inverted intervals and facts known before they were valid
(no backdating). The matching DDL lives in `alembic/versions/20261021_decisions_facts.py`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from flooreplay.decisions.types import FactKind, SourceProfile
from flooreplay.models import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _literals(enum: type[FactKind] | type[SourceProfile]) -> str:
    return ", ".join(f"'{member.value}'" for member in enum)


class DecisionSourceArtifact(Base):
    """An imported source file, kept byte-for-byte, with what it claims to cover."""

    __tablename__ = "decision_source_artifacts"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "idempotency_key", name="uq_decision_source_artifacts_idempotency"
        ),
        CheckConstraint("as_of <= known_at", name="ck_decision_source_artifacts_no_backdating"),
    )

    # Identity is workspace-scoped: the same id may exist in two workspaces.
    workspace_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid)
    profile: Mapped[str] = mapped_column(String(48))
    filename: Mapped[str] = mapped_column(String(200))
    raw_bytes: Mapped[bytes] = mapped_column(LargeBinary)
    raw_digest: Mapped[str] = mapped_column(String(80))
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    known_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    coverage: Mapped[dict[str, Any]] = mapped_column(JSONB)
    idempotency_key: Mapped[str] = mapped_column(String(200))
    preview_digest: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class FactRow(Base):
    """One bitemporal fact. Corrections are new rows that point at the row they replace."""

    __tablename__ = "facts"
    __table_args__ = (
        CheckConstraint("valid_to IS NULL OR valid_to > valid_from", name="ck_facts_valid_interval"),
        CheckConstraint("valid_from <= known_at", name="ck_facts_no_backdating"),
        CheckConstraint("supersedes_id <> id", name="ck_facts_not_self_superseding"),
        CheckConstraint(f"kind IN ({_literals(FactKind)})", name="ck_facts_kind"),
        CheckConstraint(f"source IN ({_literals(SourceProfile)})", name="ck_facts_source"),
        # References never cross workspaces (NULL supersedes_id/artifact_id skips the check).
        ForeignKeyConstraint(
            ["workspace_id", "supersedes_id"], ["facts.workspace_id", "facts.id"]
        ),
        ForeignKeyConstraint(
            ["workspace_id", "artifact_id"],
            ["decision_source_artifacts.workspace_id", "decision_source_artifacts.id"],
        ),
        Index("ix_facts_workspace_kind_entity", "workspace_id", "kind", "entity_key"),
        Index("ix_facts_workspace_known_at", "workspace_id", "known_at"),
    )

    workspace_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    kind: Mapped[str] = mapped_column(String(32))
    entity_key: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    known_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    supersedes_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(32))
    artifact_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    semantic_digest: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
