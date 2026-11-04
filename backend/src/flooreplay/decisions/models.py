"""Append-only persistence for v2 decision facts and the source artifacts they came from.

Both tables are guarded in the database: triggers reject UPDATE, DELETE and TRUNCATE, and
CHECK constraints reject inverted intervals and facts known before they were valid
(no backdating). The matching DDL lives in `alembic/versions/20261021_decisions_facts.py`.

Evaluations and human decision records are guarded the same way; their DDL lives in
`alembic/versions/20261022_decisions_records.py`; policies, cases, expectations, regression runs
and adoptions in `alembic/versions/20261023_decisions_regression.py`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from flooreplay.decisions.types import FactKind, Recommendation, SourceProfile
from flooreplay.models import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _literals(enum: type[FactKind] | type[SourceProfile] | type[Recommendation]) -> str:
    return ", ".join(f"'{member.value}'" for member in enum)


def _literals_text(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


REVIEW_SOURCE_KINDS = ("EXTRACTION_FIELD", "EVALUATION")
REVIEW_FIELD_STATUSES = ("failed", "missing", "needs_review")
REVIEW_EVENT_KINDS = ("ASSIGNED", "CONFIRMED", "CORRECTED", "REJECTED", "UNASSIGNED")


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


_OUTCOME_LITERALS = _literals(Recommendation)


class DecisionEvaluation(Base):
    """A stored replay: the snapshot cutoff, the policy that was used, and the full result.

    Unique on the replay key, so the same inputs always map to the same row. `policy` is kept
    so `reconstruct` can replay without any other source.
    """

    __tablename__ = "decision_evaluations"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "order_id",
            "cutoff",
            "policy_digest",
            "engine_version",
            "snapshot_digest",
            name="uq_decision_evaluations_replay_key",
        ),
        # Lets decision_records reference the stored outcome, so a record cannot misstate it.
        UniqueConstraint(
            "workspace_id", "id", "outcome", name="uq_decision_evaluations_id_outcome"
        ),
        CheckConstraint(f"outcome IN ({_OUTCOME_LITERALS})", name="ck_decision_evaluations_outcome"),
    )

    workspace_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid)
    order_id: Mapped[str] = mapped_column(Text)
    cutoff: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    policy_digest: Mapped[str] = mapped_column(String(80))
    policy: Mapped[dict[str, Any]] = mapped_column(JSONB)
    engine_version: Mapped[str] = mapped_column(String(32))
    snapshot_digest: Mapped[str] = mapped_column(String(80))
    decision_digest: Mapped[str] = mapped_column(String(80))
    outcome: Mapped[str] = mapped_column(String(32))
    result: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class DecisionRecord(Base):
    """A human final decision against one evaluation. Append-only; the latest row is final.

    `override` is derived (decision differs from the engine outcome), and a true override
    must carry `override_reason`. The database enforces both, so an ACCEPT over a
    NEEDS_REVIEW recommendation can never be stored without a reason.
    """

    __tablename__ = "decision_records"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "evaluation_id", "recommended_outcome"],
            [
                "decision_evaluations.workspace_id",
                "decision_evaluations.id",
                "decision_evaluations.outcome",
            ],
        ),
        CheckConstraint(f"decision IN ({_OUTCOME_LITERALS})", name="ck_decision_records_decision"),
        CheckConstraint(
            f"recommended_outcome IN ({_OUTCOME_LITERALS})", name="ck_decision_records_recommended"
        ),
        CheckConstraint(
            "override = (decision <> recommended_outcome)", name="ck_decision_records_override_flag"
        ),
        CheckConstraint(
            "NOT override OR (override_reason IS NOT NULL AND btrim(override_reason) <> '')",
            name="ck_decision_records_override_reason",
        ),
        CheckConstraint("btrim(reason) <> ''", name="ck_decision_records_reason"),
        CheckConstraint("btrim(actor) <> ''", name="ck_decision_records_actor"),
        Index("ix_decision_records_workspace_evaluation", "workspace_id", "evaluation_id"),
    )

    workspace_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid)
    evaluation_id: Mapped[str] = mapped_column(Text)
    decision: Mapped[str] = mapped_column(String(32))
    recommended_outcome: Mapped[str] = mapped_column(String(32))
    override: Mapped[bool] = mapped_column(Boolean)
    reason: Mapped[str] = mapped_column(Text)
    override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class StoredPolicy(Base):
    """A policy document as it was used in a regression run. Digest-keyed and never edited."""

    __tablename__ = "policies"
    __table_args__ = (
        UniqueConstraint("workspace_id", "policy_digest", name="uq_policies_digest"),
        CheckConstraint("btrim(label) <> ''", name="ck_policies_label"),
    )

    workspace_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid)
    policy_digest: Mapped[str] = mapped_column(String(80))
    label: Mapped[str] = mapped_column(Text)
    engine_version: Mapped[str] = mapped_column(String(32))
    policy: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class DecisionCase(Base):
    """A frozen regression case: the order's facts and coverage as known at `cutoff`.

    `synthetic` marks cases whose facts and labels were drafted, not taken from a real order.
    """

    __tablename__ = "decision_cases"
    __table_args__ = (
        CheckConstraint("btrim(name) <> ''", name="ck_decision_cases_name"),
        CheckConstraint("btrim(order_id) <> ''", name="ck_decision_cases_order"),
    )

    workspace_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    cutoff: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    order_id: Mapped[str] = mapped_column(Text)
    facts: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    coverage: Mapped[dict[str, Any]] = mapped_column(JSONB)
    synthetic: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class CaseExpectation(Base):
    """One revision of a case's hand-written expectation. Revisions are only ever added."""

    __tablename__ = "case_expectations"
    __table_args__ = (
        UniqueConstraint("workspace_id", "case_id", "revision", name="uq_case_expectations_revision"),
        ForeignKeyConstraint(
            ["workspace_id", "case_id"], ["decision_cases.workspace_id", "decision_cases.id"]
        ),
        CheckConstraint("revision >= 1", name="ck_case_expectations_revision"),
    )

    workspace_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid)
    case_id: Mapped[str] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(Integer)
    expectation: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class RegressionRun(Base):
    """A stored baseline-vs-candidate comparison over the whole suite. Never updated.

    `complete` is true only when every case was evaluated under both policies with no error
    and a classification. A run that is not complete can never be adopted.
    """

    __tablename__ = "regression_runs"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "id",
            "complete",
            "candidate_policy_digest",
            name="uq_regression_runs_adoptable",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "baseline_policy_digest"],
            ["policies.workspace_id", "policies.policy_digest"],
        ),
        ForeignKeyConstraint(
            ["workspace_id", "candidate_policy_digest"],
            ["policies.workspace_id", "policies.policy_digest"],
        ),
        CheckConstraint("status IN ('COMPLETE', 'INCOMPLETE')", name="ck_regression_runs_status"),
        CheckConstraint("complete = (status = 'COMPLETE')", name="ck_regression_runs_complete_flag"),
    )

    workspace_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid)
    baseline_policy_digest: Mapped[str] = mapped_column(String(80))
    candidate_policy_digest: Mapped[str] = mapped_column(String(80))
    suite_digest: Mapped[str] = mapped_column(String(80))
    results: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(16))
    complete: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class PolicyAdoption(Base):
    """An owner's adoption of a candidate policy that a COMPLETE run covered. Append-only.

    The composite foreign key requires the run to be complete and to have stored
    `policy_digest` as its candidate, so the database refuses anything else.
    """

    __tablename__ = "policy_adoptions"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "regression_run_id", name="uq_policy_adoptions_run"
        ),
        ForeignKeyConstraint(
            ["workspace_id", "regression_run_id", "run_complete", "policy_digest"],
            [
                "regression_runs.workspace_id",
                "regression_runs.id",
                "regression_runs.complete",
                "regression_runs.candidate_policy_digest",
            ],
        ),
        CheckConstraint("run_complete", name="ck_policy_adoptions_run_complete"),
        CheckConstraint("btrim(adopted_by) <> ''", name="ck_policy_adoptions_actor"),
        CheckConstraint(
            "jsonb_typeof(acknowledgements) = 'object'", name="ck_policy_adoptions_acknowledgements"
        ),
    )

    workspace_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid)
    regression_run_id: Mapped[str] = mapped_column(Text)
    run_complete: Mapped[bool] = mapped_column(Boolean)
    policy_digest: Mapped[str] = mapped_column(String(80))
    adopted_by: Mapped[str] = mapped_column(String(200))
    acknowledgements: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


_EXTRACTION_STATUS_LITERALS = "'COMPLETED', 'FAILED', 'BUDGET_REFUSED'"
_CALL_OUTCOME_LITERALS = "'OK', 'ERROR', 'INVALID_OUTPUT', 'PERSIST_FAILED'"
_FAILURE_KIND_LITERALS = "'PROVIDER_ERROR', 'INVALID_OUTPUT', 'STORE_FAILED'"


class NoteExtraction(Base):
    """One extraction result per (note digest, model, prompt, schema); append-only.

    `raw_output` is the provider's payload as returned, `signal` and `checks` are what the
    deterministic checks accepted and located. A FAILED row records the failure class only.
    """

    __tablename__ = "note_extractions"
    __table_args__ = (
        Index(
            "uq_note_extractions_completed_key",
            "workspace_id", "note_digest", "model", "prompt_version", "schema_version",
            unique=True,
            postgresql_where=text("status = 'COMPLETED'"),
        ),
        CheckConstraint(f"status IN ({_EXTRACTION_STATUS_LITERALS})", name="ck_note_extractions_status"),
        CheckConstraint("(status = 'FAILED') = (failure_kind IS NOT NULL)", name="ck_note_extractions_failure_kind_set"),
        CheckConstraint(f"failure_kind IN ({_FAILURE_KIND_LITERALS}) OR failure_kind IS NULL", name="ck_note_extractions_failure_kind"),
        CheckConstraint(
            "status <> 'COMPLETED' OR (signal IS NOT NULL AND checks IS NOT NULL AND field_status IS NOT NULL)",
            name="ck_note_extractions_completed_payload",
        ),
        CheckConstraint("cost_usd >= 0", name="ck_note_extractions_cost"),
        CheckConstraint("btrim(note_id) <> ''", name="ck_note_extractions_note_id"),
        CheckConstraint("btrim(model) <> ''", name="ck_note_extractions_model"),
        CheckConstraint("btrim(created_by) <> ''", name="ck_note_extractions_actor"),
    )

    workspace_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid)
    note_id: Mapped[str] = mapped_column(Text)
    note_digest: Mapped[str] = mapped_column(String(80))
    model: Mapped[str] = mapped_column(String(64))
    prompt_version: Mapped[str] = mapped_column(String(32))
    schema_version: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16))
    failure_kind: Mapped[str | None] = mapped_column(String(16), nullable=True)
    language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    raw_output: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    signal: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    checks: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    field_status: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error_class: Mapped[str | None] = mapped_column(String(120), nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    spend_entry_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_by: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ProviderCall(Base):
    """Every attempted provider call, failures included. Append-only, no secrets stored."""

    __tablename__ = "provider_calls"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "extraction_id"],
            ["note_extractions.workspace_id", "note_extractions.id"],
        ),
        Index("ix_provider_calls_workspace_digest", "workspace_id", "note_digest"),
        CheckConstraint(f"outcome IN ({_CALL_OUTCOME_LITERALS})", name="ck_provider_calls_outcome"),
        CheckConstraint("(outcome = 'OK') = (error_class IS NULL)", name="ck_provider_calls_error_class"),
        CheckConstraint("cost_usd >= 0", name="ck_provider_calls_cost"),
    )

    workspace_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid)
    extraction_id: Mapped[str] = mapped_column(Text)
    note_digest: Mapped[str] = mapped_column(String(80))
    provider_name: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(64))
    prompt_version: Mapped[str] = mapped_column(String(32))
    schema_version: Mapped[str] = mapped_column(String(32))
    outcome: Mapped[str] = mapped_column(String(24))
    error_class: Mapped[str | None] = mapped_column(String(120), nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    spend_entry_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ReviewItem(Base):
    """One failed or missing extraction field, or one NEEDS_REVIEW evaluation. Append-only.

    The state is never stored here: it is derived from the latest `ReviewEvent`. The claimed
    value and span are what was stored at enqueue time and never change.
    """

    __tablename__ = "review_items"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "extraction_id"],
            ["note_extractions.workspace_id", "note_extractions.id"],
        ),
        ForeignKeyConstraint(
            ["workspace_id", "evaluation_id"],
            ["decision_evaluations.workspace_id", "decision_evaluations.id"],
        ),
        Index(
            "uq_review_items_source_field",
            "workspace_id",
            "source_kind",
            text("coalesce(extraction_id, evaluation_id)"),
            "field_name",
            unique=True,
        ),
        CheckConstraint(
            f"source_kind IN ({_literals_text(REVIEW_SOURCE_KINDS)})", name="ck_review_items_source_kind"
        ),
        CheckConstraint(
            "(source_kind = 'EXTRACTION_FIELD' AND extraction_id IS NOT NULL AND evaluation_id IS NULL) "
            "OR (source_kind = 'EVALUATION' AND evaluation_id IS NOT NULL AND extraction_id IS NULL)",
            name="ck_review_items_source_ref",
        ),
        CheckConstraint(
            f"field_status IN ({_literals_text(REVIEW_FIELD_STATUSES)})", name="ck_review_items_field_status"
        ),
        CheckConstraint("btrim(field_name) <> ''", name="ck_review_items_field_name"),
        CheckConstraint("jsonb_typeof(check_codes) = 'array'", name="ck_review_items_check_codes"),
        CheckConstraint(
            "source_kind <> 'EVALUATION' OR entity_key IS NOT NULL", name="ck_review_items_entity_eval"
        ),
    )

    workspace_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid)
    source_kind: Mapped[str] = mapped_column(String(24))
    extraction_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    evaluation_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    field_name: Mapped[str] = mapped_column(String(64))
    field_status: Mapped[str] = mapped_column(String(24))
    check_codes: Mapped[list[str]] = mapped_column(JSONB)
    claimed_value: Mapped[Any] = mapped_column(JSONB, nullable=True)
    evidence_span: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # The entity the item concerns (`lot:<id>` for an extraction, `order:<id>` for an evaluation).
    # Null only for an extraction whose lot was not checked; a human fact cannot be bound to it.
    entity_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ReviewEvent(Base):
    """One step in an item's history: assignment, then at most one decision. Append-only."""

    __tablename__ = "review_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "item_id"], ["review_items.workspace_id", "review_items.id"]
        ),
        ForeignKeyConstraint(
            ["workspace_id", "resulting_fact_id"], ["facts.workspace_id", "facts.id"]
        ),
        Index("ix_review_events_workspace_item", "workspace_id", "item_id", "seq"),
        CheckConstraint(
            f"kind IN ({_literals_text(REVIEW_EVENT_KINDS)})", name="ck_review_events_kind"
        ),
        CheckConstraint("btrim(actor) <> ''", name="ck_review_events_actor"),
        CheckConstraint(
            "(kind = 'ASSIGNED' AND assignee_id IS NOT NULL) "
            "OR (kind <> 'ASSIGNED' AND assignee_id IS NULL)",
            name="ck_review_events_assignee",
        ),
        CheckConstraint(
            "kind IN ('ASSIGNED', 'UNASSIGNED') OR btrim(note) <> ''", name="ck_review_events_note"
        ),
        CheckConstraint(
            "kind <> 'CORRECTED' OR (corrected_value IS NOT NULL AND resulting_fact_id IS NOT NULL)",
            name="ck_review_events_corrected",
        ),
        CheckConstraint(
            "resulting_fact_id IS NULL OR kind IN ('CONFIRMED', 'CORRECTED')",
            name="ck_review_events_fact_kind",
        ),
    )

    workspace_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid)
    seq: Mapped[int] = mapped_column(BigInteger, Identity(), unique=True)
    item_id: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(16))
    actor: Mapped[str] = mapped_column(String(200))
    assignee_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    note: Mapped[str] = mapped_column(Text, server_default="")
    corrected_value: Mapped[Any] = mapped_column(JSONB, nullable=True)
    resulting_fact_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
