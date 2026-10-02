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
    LargeBinary,
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
    workspace_id: Mapped[str] = mapped_column(String(64), default="public-demo", server_default="public-demo", index=True)

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
    workspace_id: Mapped[str] = mapped_column(String(64), default="public-demo", server_default="public-demo", index=True)

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
    workspace_id: Mapped[str] = mapped_column(String(64), default="public-demo", server_default="public-demo", index=True)
    __table_args__ = (UniqueConstraint("scenario_id", "revision", "configuration_id", name="uq_expectation"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    scenario_id: Mapped[str] = mapped_column(String(64))
    revision: Mapped[int] = mapped_column(Integer)
    configuration_id: Mapped[str] = mapped_column(String(64))
    assertions: Mapped[dict[str, Any]] = mapped_column(JSONB)


class ReplayAttempt(Base):
    __tablename__ = "replay_attempts"
    workspace_id: Mapped[str] = mapped_column(String(64), default="public-demo", server_default="public-demo", index=True)

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
    elapsed_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)


class ImportAudit(Base):
    """One published import: the exact preview digest, the raw bytes, and
    the snapshot they became. Publication is all-or-nothing and idempotent
    by preview digest."""

    __tablename__ = "import_audits"
    workspace_id: Mapped[str] = mapped_column(String(64), default="public-demo", server_default="public-demo", index=True)

    preview_digest: Mapped[str] = mapped_column(String(80), primary_key=True)
    profile_id: Mapped[str] = mapped_column(String(32))
    snapshot_id: Mapped[str] = mapped_column(String(64), ForeignKey("source_snapshots.id"))
    raw_digest: Mapped[str] = mapped_column(String(80))
    raw_bytes: Mapped[bytes] = mapped_column(LargeBinary)
    row_count: Mapped[int] = mapped_column(Integer)
    blocking_issue_count: Mapped[int] = mapped_column(Integer)
    warning_issue_count: Mapped[int] = mapped_column(Integer)
    declared_evidence_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    coverage_complete: Mapped[bool] = mapped_column(Boolean)
    scope: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(tz=UTC)
    )


class SuiteRevision(Base):
    """An ordered, pinned suite membership: scenario revisions plus their
    expectation revisions, content-addressed as one unit."""

    __tablename__ = "suite_revisions"
    workspace_id: Mapped[str] = mapped_column(String(64), default="public-demo", server_default="public-demo", index=True)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer)
    label: Mapped[str] = mapped_column(Text)
    items: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    content_digest: Mapped[str] = mapped_column(String(80), unique=True)


class ComparisonReport(Base):
    """One suite execution under two configurations and its classifications."""

    __tablename__ = "comparison_reports"
    workspace_id: Mapped[str] = mapped_column(String(64), default="public-demo", server_default="public-demo", index=True)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    idempotency_key: Mapped[str] = mapped_column(String(120), unique=True)
    suite_id: Mapped[str] = mapped_column(String(64))
    suite_revision: Mapped[int] = mapped_column(Integer)
    baseline_config_id: Mapped[str] = mapped_column(String(64))
    candidate_config_id: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))  # COMPLETED | INTERRUPTED
    items: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    totals: Mapped[dict[str, Any]] = mapped_column(JSONB)
    manifest_digest: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(tz=UTC)
    )


class ParserCall(Base):
    """One draft extraction call. Raw note text is retained for the
    confirmation workflow (a local-owner tool); it is never written to
    application logs. Live-provider responses are recorded with model,
    prompt digest, schema version, and token usage."""

    __tablename__ = "parser_calls"
    workspace_id: Mapped[str] = mapped_column(String(64), default="public-demo", server_default="public-demo", index=True)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    note_text: Mapped[str] = mapped_column(Text)
    note_digest: Mapped[str] = mapped_column(String(80))
    parser_kind: Mapped[str] = mapped_column(String(32))
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    prompt_digest: Mapped[str] = mapped_column(String(80), default="")
    schema_version: Mapped[int] = mapped_column(Integer, default=1)
    response: Mapped[dict[str, Any]] = mapped_column(JSONB)
    resolution: Mapped[dict[str, Any]] = mapped_column(JSONB)
    usage: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(tz=UTC)
    )


class ReviewCheck(Base):
    """A later-context review of an original proposal. Never alters the
    original replay; records which paths of the decision context changed."""

    __tablename__ = "review_checks"
    workspace_id: Mapped[str] = mapped_column(String(64), default="public-demo", server_default="public-demo", index=True)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    original_replay_id: Mapped[str] = mapped_column(String(64), index=True)
    target_scenario_id: Mapped[str] = mapped_column(String(64))
    target_scenario_revision: Mapped[int] = mapped_column(Integer)
    outcome: Mapped[str] = mapped_column(String(32))  # STILL_SUPPORTED | STALE_RECOMMENDATION | BLOCKED_CONTEXT
    changed_paths: Mapped[list[str]] = mapped_column(JSONB, default=list)
    reason_codes: Mapped[list[str]] = mapped_column(JSONB, default=list)
    issues: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    target_context_digest: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(tz=UTC)
    )


class IncidentRevision(Base):
    __tablename__ = "incident_revisions"
    workspace_id: Mapped[str] = mapped_column(String(64), default="public-demo", server_default="public-demo", index=True)

    incident_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    line_id: Mapped[str] = mapped_column(String(64), index=True)
    cutoff: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    content_digest: Mapped[str] = mapped_column(String(80))
    evidence_card: Mapped[str] = mapped_column(Text, default="")


class IncidentAnalysis(Base):
    __tablename__ = "incident_analyses"
    workspace_id: Mapped[str] = mapped_column(String(64), default="public-demo", server_default="public-demo", index=True)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    idempotency_key: Mapped[str] = mapped_column(String(120), unique=True)
    incident_id: Mapped[str] = mapped_column(String(64), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    manifest_digest: Mapped[str] = mapped_column(String(80))
    report: Mapped[dict[str, Any]] = mapped_column(JSONB)
    execution_kind: Mapped[str] = mapped_column(String(32), default="live_deterministic")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(tz=UTC))
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class IncidentReview(Base):
    __tablename__ = "incident_reviews"
    workspace_id: Mapped[str] = mapped_column(String(64), default="public-demo", server_default="public-demo", index=True)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    idempotency_key: Mapped[str] = mapped_column(String(120), unique=True)
    analysis_id: Mapped[str] = mapped_column(String(64), index=True)
    proposal_id: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(32))
    actor: Mapped[str] = mapped_column(String(120))
    rationale: Mapped[str] = mapped_column(Text)
    proposal_digest: Mapped[str] = mapped_column(String(80))
    analysis_digest: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(tz=UTC))


class IncidentModelJob(Base):
    __tablename__ = "incident_model_jobs"
    workspace_id: Mapped[str] = mapped_column(String(64), default="public-demo", server_default="public-demo", index=True)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    idempotency_key: Mapped[str] = mapped_column(String(120), unique=True)
    analysis_id: Mapped[str] = mapped_column(String(64), index=True)
    question: Mapped[str] = mapped_column(Text)
    packet: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(32), index=True)
    owner: Mapped[str | None] = mapped_column(String(120), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(tz=UTC))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class IncidentSourceArtifact(Base):
    __tablename__ = "incident_source_artifacts"
    workspace_id: Mapped[str] = mapped_column(String(64), default="public-demo", server_default="public-demo", index=True)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    idempotency_key: Mapped[str] = mapped_column(String(120), unique=True)
    incident_id: Mapped[str] = mapped_column(String(64), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    profile: Mapped[str] = mapped_column(String(32))
    source_system: Mapped[str] = mapped_column(String(64))
    filename: Mapped[str] = mapped_column(String(120))
    raw_digest: Mapped[str] = mapped_column(String(80))
    raw_bytes: Mapped[bytes] = mapped_column(LargeBinary)
    preview: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(tz=UTC))
