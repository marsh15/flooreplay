"""Database-backed tests for stored evaluations, human decision records and reconstruction.

Rows can never be deleted (the triggers forbid it), so every test works in a uuid workspace
with uuid ids and keys, and the session fixture rolls its transaction back.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from flooreplay.db import SessionLocal
from flooreplay.decisions import service
from flooreplay.decisions.models import DecisionEvaluation, DecisionRecord
from flooreplay.decisions.policy import DEFAULT_POLICY_V1
from flooreplay.decisions.types import Fact, FactKind, Recommendation, SourceProfile
from flooreplay.errors import ServiceError
from flooreplay.schema_head import SCHEMA_HEAD

T0 = datetime(2026, 3, 1, 8, 0, tzinfo=UTC)
CUTOFF = T0 + timedelta(days=1)  # long settled: the real clock is far past it


def uid() -> str:
    return uuid.uuid4().hex


@pytest.fixture
def session() -> Iterator[Session]:
    with SessionLocal() as db:
        yield db
        db.rollback()


@pytest.fixture
def workspace() -> str:
    return "ws-" + uid()


def lot_fact(key: str, *, known_at: datetime = T0) -> Fact:
    return Fact(
        id="F-" + uid(),
        kind=FactKind.FABRIC_LOT,
        entity_key=key,
        payload={
            "qty": {"value": "100", "unit": "kg"},
            "fabric_quality": "SJ180",
            "colour": "NAVY",
        },
        valid_from=T0,
        valid_to=None,
        known_at=known_at,
        supersedes_id=None,
        source=SourceProfile.ERP_FABRIC_STOCK,
        artifact_id=None,
    )


def evaluate(session: Session, workspace: str, order: str | None = None) -> DecisionEvaluation:
    return service.evaluate_order(
        session, workspace, order or "O-" + uid(), CUTOFF, DEFAULT_POLICY_V1
    )


def other_than(outcome: str) -> Recommendation:
    return next(r for r in Recommendation if r.value != outcome)


def _rejected(session: Session, statement: str, params: dict[str, Any]) -> str:
    """Run raw SQL in a SAVEPOINT; assert the database refuses and return its message."""
    with pytest.raises(DBAPIError) as caught, session.begin_nested():
        session.execute(text(statement), params)
    return str(caught.value)


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


def test_schema_head_names_this_migration() -> None:
    assert SCHEMA_HEAD == "20261024_decisions_review"


def test_evaluation_is_idempotent_for_the_same_inputs(session: Session, workspace: str) -> None:
    order = "O-" + uid()
    first = evaluate(session, workspace, order)
    second = evaluate(session, workspace, order)

    assert second.id == first.id
    assert second.decision_digest == first.decision_digest
    count = session.scalar(
        select(func.count())
        .select_from(DecisionEvaluation)
        .where(DecisionEvaluation.workspace_id == workspace, DecisionEvaluation.order_id == order)
    )
    assert count == 1


def test_a_different_cutoff_or_order_is_a_different_evaluation(
    session: Session, workspace: str
) -> None:
    order = "O-" + uid()
    base = evaluate(session, workspace, order)
    later = service.evaluate_order(
        session, workspace, order, CUTOFF + timedelta(hours=1), DEFAULT_POLICY_V1
    )
    other = evaluate(session, workspace, "O-" + uid())
    assert len({base.id, later.id, other.id}) == 3


def test_an_unsettled_cutoff_is_refused(session: Session, workspace: str) -> None:
    with pytest.raises(ServiceError) as caught:
        service.evaluate_order(
            session, workspace, "O-" + uid(), datetime.now(UTC), DEFAULT_POLICY_V1
        )
    assert caught.value.code == "CUTOFF_NOT_SETTLED"


def test_a_naive_cutoff_is_refused(session: Session, workspace: str) -> None:
    with pytest.raises(ServiceError) as caught:
        service.evaluate_order(
            session, workspace, "O-" + uid(), datetime(2026, 3, 1), DEFAULT_POLICY_V1
        )
    assert caught.value.code == "CUTOFF_INVALID"


def test_evaluation_stores_the_replay_result_and_policy(session: Session, workspace: str) -> None:
    row = evaluate(session, workspace)
    assert row.outcome in {r.value for r in Recommendation}
    assert row.result["decision_digest"] == row.decision_digest
    assert row.policy["label"] == DEFAULT_POLICY_V1.label


def test_facts_known_after_the_cutoff_do_not_change_a_stored_evaluation(
    session: Session, workspace: str
) -> None:
    service.append_fact(
        session, lot_fact("lot:" + uid()), workspace_id=workspace, trusted_known_at=T0
    )
    row = evaluate(session, workspace)
    service.append_fact(
        session,
        lot_fact("lot:" + uid(), known_at=CUTOFF + timedelta(days=1)),
        workspace_id=workspace,
        trusted_known_at=CUTOFF + timedelta(days=1),
    )
    again = service.evaluate_order(
        session, workspace, row.order_id, CUTOFF, DEFAULT_POLICY_V1
    )
    assert again.id == row.id


# ---------------------------------------------------------------------------
# Human decision records
# ---------------------------------------------------------------------------


def test_a_decision_matching_the_engine_is_not_an_override(
    session: Session, workspace: str
) -> None:
    row = evaluate(session, workspace)
    record = service.record_decision(
        session, workspace, row.id, Recommendation(row.outcome), "agrees", "planner@example.test"
    )
    assert record.override is False
    assert record.override_reason is None
    assert record.recommended_outcome == row.outcome


def test_an_override_without_a_reason_is_refused(session: Session, workspace: str) -> None:
    row = evaluate(session, workspace)
    with pytest.raises(ServiceError) as caught:
        service.record_decision(
            session, workspace, row.id, other_than(row.outcome), "   ", "planner@example.test"
        )
    assert caught.value.code == "OVERRIDE_REASON_REQUIRED"


def test_a_plain_decision_without_a_reason_is_refused(session: Session, workspace: str) -> None:
    row = evaluate(session, workspace)
    with pytest.raises(ServiceError) as caught:
        service.record_decision(
            session, workspace, row.id, Recommendation(row.outcome), "", "planner@example.test"
        )
    assert caught.value.code == "DECISION_REASON_REQUIRED"


def test_accept_over_needs_review_is_never_stored_without_a_reason(
    session: Session, workspace: str
) -> None:
    # An empty workspace has no evidence, so the engine must not auto-accept it.
    row = evaluate(session, workspace)
    assert row.outcome == Recommendation.NEEDS_REVIEW.value

    with pytest.raises(ServiceError) as caught:
        service.record_decision(
            session, workspace, row.id, Recommendation.ACCEPT, " ", "planner@example.test"
        )
    assert caught.value.code == "OVERRIDE_REASON_REQUIRED"
    stored = session.scalar(
        select(func.count())
        .select_from(DecisionRecord)
        .where(DecisionRecord.workspace_id == workspace, DecisionRecord.evaluation_id == row.id)
    )
    assert stored == 0


def test_accept_over_needs_review_with_a_reason_is_a_recorded_override(
    session: Session, workspace: str
) -> None:
    row = evaluate(session, workspace)
    record = service.record_decision(
        session,
        workspace,
        row.id,
        Recommendation.ACCEPT,
        "customer confirmed the lot by phone",
        "planner@example.test",
    )
    assert record.override is True
    assert record.recommended_outcome == Recommendation.NEEDS_REVIEW.value
    assert record.override_reason == "customer confirmed the lot by phone"


def test_an_empty_actor_is_refused(session: Session, workspace: str) -> None:
    row = evaluate(session, workspace)
    with pytest.raises(ServiceError) as caught:
        service.record_decision(session, workspace, row.id, Recommendation.NEEDS_REVIEW, "x", " ")
    assert caught.value.code == "ACTOR_REQUIRED"


def test_the_database_refuses_an_override_without_a_reason(
    session: Session, workspace: str
) -> None:
    row = evaluate(session, workspace)
    message = _rejected(
        session,
        """
        INSERT INTO decision_records (id, workspace_id, evaluation_id, decision,
            recommended_outcome, override, reason, override_reason, actor, created_at)
        VALUES (:id, :ws, :ev, 'ACCEPT', 'NEEDS_REVIEW', true, 'why', NULL, 'a', now())
        """,
        {"id": "R-" + uid(), "ws": workspace, "ev": row.id},
    )
    assert "ck_decision_records_override_reason" in message


def test_the_database_refuses_an_override_flag_that_lies(session: Session, workspace: str) -> None:
    row = evaluate(session, workspace)
    message = _rejected(
        session,
        """
        INSERT INTO decision_records (id, workspace_id, evaluation_id, decision,
            recommended_outcome, override, reason, override_reason, actor, created_at)
        VALUES (:id, :ws, :ev, 'ACCEPT', 'NEEDS_REVIEW', false, 'why', NULL, 'a', now())
        """,
        {"id": "R-" + uid(), "ws": workspace, "ev": row.id},
    )
    assert "ck_decision_records_override_flag" in message


def test_the_database_refuses_a_record_that_misstates_the_evaluation_outcome(
    session: Session, workspace: str
) -> None:
    row = evaluate(session, workspace)
    assert row.outcome == Recommendation.NEEDS_REVIEW.value
    message = _rejected(
        session,
        """
        INSERT INTO decision_records (id, workspace_id, evaluation_id, decision,
            recommended_outcome, override, reason, override_reason, actor, created_at)
        VALUES (:id, :ws, :ev, 'ACCEPT', 'ACCEPT', false, 'why', NULL, 'a', now())
        """,
        {"id": "R-" + uid(), "ws": workspace, "ev": row.id},
    )
    assert "foreign key" in message.lower()


def test_an_overlong_actor_is_a_service_error(session: Session, workspace: str) -> None:
    row = evaluate(session, workspace)
    with pytest.raises(ServiceError) as caught:
        service.record_decision(
            session, workspace, row.id, Recommendation.NEEDS_REVIEW, "agrees", "x" * 201
        )
    assert caught.value.code == "ACTOR_TOO_LONG"


# ---------------------------------------------------------------------------
# Append-only triggers
# ---------------------------------------------------------------------------


@pytest.fixture
def stored(session: Session, workspace: str) -> dict[str, Any]:
    row = evaluate(session, workspace)
    record = service.record_decision(
        session, workspace, row.id, Recommendation(row.outcome), "agrees", "planner@example.test"
    )
    return {"evaluation": row.id, "record": record.id, "ws": workspace}


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE decision_evaluations SET outcome = 'DECLINE' WHERE id = :evaluation",
        "DELETE FROM decision_evaluations WHERE id = :evaluation",
        "UPDATE decision_records SET reason = 'changed' WHERE id = :record",
        "DELETE FROM decision_records WHERE id = :record",
    ],
)
def test_update_and_delete_are_rejected_by_the_database(
    session: Session, stored: dict[str, Any], statement: str
) -> None:
    assert "append-only" in _rejected(session, statement, stored)


@pytest.mark.parametrize("table", ["decision_evaluations", "decision_records"])
def test_truncate_is_rejected_by_the_database(
    session: Session, stored: dict[str, Any], table: str
) -> None:
    assert "append-only" in _rejected(session, f"TRUNCATE {table} CASCADE", stored)


# ---------------------------------------------------------------------------
# Workspace isolation
# ---------------------------------------------------------------------------


def test_an_evaluation_is_invisible_to_another_workspace(
    session: Session, workspace: str
) -> None:
    row = evaluate(session, workspace)
    other = "ws-" + uid()
    with pytest.raises(ServiceError) as caught:
        service.reconstruct(session, other, row.id)
    assert caught.value.code == "EVALUATION_NOT_FOUND"
    with pytest.raises(ServiceError) as caught_record:
        service.record_decision(session, other, row.id, Recommendation.NEEDS_REVIEW, "x", "a")
    assert caught_record.value.code == "EVALUATION_NOT_FOUND"


def test_the_same_replay_key_in_two_workspaces_gives_two_rows(session: Session) -> None:
    order = "O-" + uid()
    first = evaluate(session, "ws-" + uid(), order)
    second = evaluate(session, "ws-" + uid(), order)
    assert first.workspace_id != second.workspace_id
    assert first.id != second.id


def test_a_record_cannot_point_at_another_workspaces_evaluation(
    session: Session, workspace: str
) -> None:
    row = evaluate(session, workspace)
    message = _rejected(
        session,
        """
        INSERT INTO decision_records (id, workspace_id, evaluation_id, decision,
            recommended_outcome, override, reason, override_reason, actor, created_at)
        VALUES (:id, :ws, :ev, :outcome, :outcome, false, 'why', NULL, 'a', now())
        """,
        {"id": "R-" + uid(), "ws": "ws-" + uid(), "ev": row.id, "outcome": row.outcome},
    )
    assert "decision_records_workspace_id_evaluation_id_fkey" in message or "foreign key" in message


# ---------------------------------------------------------------------------
# Reconstruction
# ---------------------------------------------------------------------------


def test_reconstruct_reproduces_the_stored_decision_digest(
    session: Session, workspace: str
) -> None:
    service.append_fact(
        session, lot_fact("lot:" + uid()), workspace_id=workspace, trusted_known_at=T0
    )
    row = evaluate(session, workspace)
    # A later fact, known after the cutoff, must not leak into the reconstruction.
    service.append_fact(
        session,
        lot_fact("lot:" + uid(), known_at=CUTOFF + timedelta(days=2)),
        workspace_id=workspace,
        trusted_known_at=CUTOFF + timedelta(days=2),
    )

    result = service.reconstruct(session, workspace, row.id)
    assert isinstance(result, service.Reconstruction)
    assert result.matches is True
    assert result.snapshot_matches and result.policy_matches
    assert result.recomputed_decision_digest == row.decision_digest


def test_reconstruct_reports_a_mismatch_without_raising(session: Session, workspace: str) -> None:
    good = evaluate(session, workspace)
    # Forge a row whose stored digest cannot be reproduced (inserts are allowed; edits are not).
    forged = DecisionEvaluation(
        workspace_id=workspace,
        id="E-" + uid(),
        order_id="O-" + uid(),
        cutoff=CUTOFF,
        policy_digest=good.policy_digest,
        policy=good.policy,
        engine_version=good.engine_version,
        snapshot_digest=good.snapshot_digest,
        decision_digest="sha256:" + "0" * 64,
        outcome=good.outcome,
        result=good.result,
        created_at=datetime.now(UTC),
    )
    session.add(forged)
    session.flush()

    result = service.reconstruct(session, workspace, forged.id)
    assert result.matches is False
    assert result.snapshot_matches is True
    assert result.stored_decision_digest == "sha256:" + "0" * 64
    assert result.recomputed_decision_digest != result.stored_decision_digest


def test_reconstruct_detects_a_policy_that_does_not_match_its_digest(
    session: Session, workspace: str
) -> None:
    good = evaluate(session, workspace)
    tampered_policy = dict(good.policy)
    tampered_policy["label"] = "tampered"
    forged = DecisionEvaluation(
        workspace_id=workspace,
        id="E-" + uid(),
        order_id=good.order_id,
        cutoff=CUTOFF,
        policy_digest=good.policy_digest,
        policy=tampered_policy,
        engine_version=good.engine_version,
        snapshot_digest=good.snapshot_digest,
        decision_digest=good.decision_digest,
        outcome=good.outcome,
        result=good.result,
        created_at=datetime.now(UTC),
    )
    # Same replay key as `good` would collide, so pick a different cutoff for the forged row.
    forged.cutoff = CUTOFF + timedelta(hours=3)
    session.add(forged)
    session.flush()

    result = service.reconstruct(session, workspace, forged.id)
    assert result.policy_matches is False
    assert result.matches is False


def test_a_missing_evaluation_is_not_found_not_a_mismatch(
    session: Session, workspace: str
) -> None:
    with pytest.raises(ServiceError) as caught:
        service.reconstruct(session, workspace, "E-" + uid())
    assert caught.value.code == "EVALUATION_NOT_FOUND"


def test_the_replay_key_is_unique_in_the_database(session: Session, workspace: str) -> None:
    # The database backstop behind evaluate_order's "return the winner" path.
    row = evaluate(session, workspace, "O-" + uid())
    with pytest.raises(IntegrityError), session.begin_nested():
        session.add(
            DecisionEvaluation(
                workspace_id=workspace,
                id="E-" + uid(),
                order_id=row.order_id,
                cutoff=CUTOFF,
                policy_digest=row.policy_digest,
                policy=row.policy,
                engine_version=row.engine_version,
                snapshot_digest=row.snapshot_digest,
                decision_digest=row.decision_digest,
                outcome=row.outcome,
                result=row.result,
                created_at=datetime.now(UTC),
            )
        )
        session.flush()
    again = evaluate(session, workspace, row.order_id)
    assert again.id == row.id
