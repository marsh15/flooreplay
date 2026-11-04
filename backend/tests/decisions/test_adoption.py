"""Database-backed tests for regression runs and owner-only policy adoption (T12).

Rows can never be deleted (the triggers forbid it), so every test works in a uuid workspace
with uuid keys, and the session fixture rolls its transaction back.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from decisions.worlds import ready_world
from flooreplay.db import SessionLocal
from flooreplay.decisions import service
from flooreplay.decisions.expectations import Expectation
from flooreplay.decisions.models import (
    CaseExpectation,
    DecisionCase,
    PolicyAdoption,
    RegressionRun,
    StoredPolicy,
)
from flooreplay.decisions.policy import DEFAULT_POLICY_V1, PolicyDocument, policy_digest
from flooreplay.decisions.types import FactKind, Recommendation
from flooreplay.errors import ServiceError

CANDIDATE_LABEL = "Tiruppur candidate v2"
OWNER = "owner-test"


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


def candidate_policy() -> PolicyDocument:
    """The default policy with one constraint switched off: replay then forces NEEDS_REVIEW."""
    data = DEFAULT_POLICY_V1.model_dump(mode="json")
    data["label"] = CANDIDATE_LABEL
    data["enabled_constraints"] = [c.value for c in DEFAULT_POLICY_V1.enabled_constraints[1:]]
    return PolicyDocument.model_validate(data)


def add_suite(session: Session, workspace: str) -> dict[str, str]:
    """Two cases: a clean order that should ACCEPT, and one missing its BOM that needs review."""
    ready = ready_world()
    review = ready_world().without(kind=FactKind.BOM)
    ids = {"ready": "case-ready-" + uid(), "review": "case-review-" + uid()}
    for key, world, outcome in (
        ("ready", ready, Recommendation.ACCEPT),
        ("review", review, Recommendation.NEEDS_REVIEW),
    ):
        service.create_case(
            session,
            workspace,
            ids[key],
            f"{key} case",
            world.cutoff,
            world.order_id,
            world.facts,
            world.coverage,
            synthetic=True,
        )
        service.add_expectation(
            session, workspace, ids[key], Expectation(correct=outcome, rationale="gold label")
        )
    return ids


def complete_run(session: Session, workspace: str) -> RegressionRun:
    add_suite(session, workspace)
    return service.run_regression(session, workspace, DEFAULT_POLICY_V1, candidate_policy())


def classifications(run: RegressionRun) -> dict[str, str]:
    return {item["case_id"]: item["classification"] for item in run.results}


def _rejected(session: Session, statement: str, params: dict[str, Any]) -> str:
    """Run raw SQL in a SAVEPOINT; assert the database refuses and return its message."""
    with pytest.raises(DBAPIError) as caught, session.begin_nested():
        session.execute(text(statement), params)
    return str(caught.value)


# ---------------------------------------------------------------------------
# Regression runs
# ---------------------------------------------------------------------------


def test_every_case_is_evaluated_under_both_policies(session: Session, workspace: str) -> None:
    ids = add_suite(session, workspace)
    run = service.run_regression(session, workspace, DEFAULT_POLICY_V1, candidate_policy())

    assert run.complete is True
    assert run.status == "COMPLETE"
    assert {item["case_id"] for item in run.results} == set(ids.values())
    for item in run.results:
        assert item["baseline"]["verdict"] is not None
        assert item["candidate"]["verdict"] is not None
    assert classifications(run) == {ids["ready"]: "REGRESSION", ids["review"]: "UNCHANGED_PASS"}


def test_a_case_without_an_expectation_makes_the_run_incomplete(
    session: Session, workspace: str
) -> None:
    world = ready_world()
    lonely = "case-lonely-" + uid()
    service.create_case(
        session, workspace, lonely, "no gold yet", world.cutoff, world.order_id,
        world.facts, world.coverage, synthetic=True,
    )
    run = service.run_regression(session, workspace, DEFAULT_POLICY_V1, candidate_policy())

    assert run.complete is False
    assert run.status == "INCOMPLETE"
    assert classifications(run)[lonely] == "NOT_COMPARABLE"


def test_a_run_that_errors_on_a_case_is_stored_incomplete_and_never_adoptable(
    session: Session, workspace: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    ids = add_suite(session, workspace)
    real_replay = service.replay

    def interrupted(snapshot: Any, order_id: str, policy: PolicyDocument, coverage: Any = None) -> Any:
        if policy.label == CANDIDATE_LABEL:
            raise RuntimeError("worker interrupted mid-run")
        return real_replay(snapshot, order_id, policy, coverage)

    monkeypatch.setattr(service, "replay", interrupted)
    run = service.run_regression(session, workspace, DEFAULT_POLICY_V1, candidate_policy())
    monkeypatch.undo()

    assert run.complete is False
    stored = session.scalar(select(RegressionRun).where(RegressionRun.id == run.id))
    assert stored is not None and stored.status == "INCOMPLETE"
    errored = next(item for item in run.results if item["case_id"] == ids["ready"])
    assert "interrupted" in errored["candidate"]["error"]
    with pytest.raises(ServiceError) as caught:
        service.adopt_policy(
            session, workspace, run.id, "owner", {ids["ready"]: "ack"}, OWNER
        )
    assert caught.value.code == "RUN_INCOMPLETE"
    assert caught.value.http_status == 409


def test_identical_policies_are_stored_once(session: Session, workspace: str) -> None:
    add_suite(session, workspace)
    service.run_regression(session, workspace, DEFAULT_POLICY_V1, candidate_policy())
    service.run_regression(session, workspace, DEFAULT_POLICY_V1, candidate_policy())

    count = session.scalar(
        select(func.count())
        .select_from(StoredPolicy)
        .where(StoredPolicy.workspace_id == workspace)
    )
    assert count == 2  # baseline and candidate, once each


def test_a_duplicate_case_id_is_refused(session: Session, workspace: str) -> None:
    world = ready_world()
    case_id = "case-dup-" + uid()
    args = (session, workspace, case_id, "dup", world.cutoff, world.order_id, world.facts, world.coverage)
    service.create_case(*args, synthetic=True)
    with pytest.raises(ServiceError) as caught:
        service.create_case(*args, synthetic=True)
    assert caught.value.code == "CASE_EXISTS"


# ---------------------------------------------------------------------------
# Adoption
# ---------------------------------------------------------------------------


def test_a_reviewer_cannot_adopt_even_with_every_acknowledgement(
    session: Session, workspace: str
) -> None:
    ids = add_suite(session, workspace)
    run = service.run_regression(session, workspace, DEFAULT_POLICY_V1, candidate_policy())
    for role in ("reviewer", "member"):
        with pytest.raises(ServiceError) as caught:
            service.adopt_policy(
                session, workspace, run.id, role, {ids["ready"]: "Accepted by QC."}, OWNER
            )
        assert caught.value.code == "ADOPTION_FORBIDDEN"
        assert caught.value.http_status == 403


@pytest.mark.parametrize("acknowledgement", [None, "", "   \n\t"])
def test_a_regression_without_a_written_acknowledgement_is_refused(
    session: Session, workspace: str, acknowledgement: str | None
) -> None:
    ids = add_suite(session, workspace)
    run = service.run_regression(session, workspace, DEFAULT_POLICY_V1, candidate_policy())
    acks = {} if acknowledgement is None else {ids["ready"]: acknowledgement}
    with pytest.raises(ServiceError) as caught:
        service.adopt_policy(session, workspace, run.id, "owner", acks, OWNER)
    assert caught.value.code == "ACKNOWLEDGEMENT_REQUIRED"
    assert caught.value.http_status == 409


def test_a_null_acknowledgement_value_is_refused_not_a_crash(
    session: Session, workspace: str
) -> None:
    ids = add_suite(session, workspace)
    run = service.run_regression(session, workspace, DEFAULT_POLICY_V1, candidate_policy())
    with pytest.raises(ServiceError) as caught:
        service.adopt_policy(
            session, workspace, run.id, "owner", {ids["ready"]: None}, OWNER  # type: ignore[dict-item]
        )
    assert caught.value.code == "ACKNOWLEDGEMENT_REQUIRED"


def test_a_run_can_only_be_adopted_once(session: Session, workspace: str) -> None:
    ids = add_suite(session, workspace)
    run = service.run_regression(session, workspace, DEFAULT_POLICY_V1, candidate_policy())
    service.adopt_policy(session, workspace, run.id, "owner", {ids["ready"]: "Accepted."}, OWNER)
    with pytest.raises(ServiceError) as caught:
        service.adopt_policy(session, workspace, run.id, "owner", {ids["ready"]: "Again."}, OWNER)
    assert caught.value.code == "RUN_ALREADY_ADOPTED"
    assert caught.value.http_status == 409


def test_an_acknowledgement_for_a_case_that_did_not_regress_is_refused(
    session: Session, workspace: str
) -> None:
    ids = add_suite(session, workspace)
    run = service.run_regression(session, workspace, DEFAULT_POLICY_V1, candidate_policy())
    with pytest.raises(ServiceError) as caught:
        service.adopt_policy(
            session,
            workspace,
            run.id,
            "owner",
            {ids["ready"]: "Accepted.", ids["review"]: "Not needed."},
            OWNER,
        )
    assert caught.value.code == "ACKNOWLEDGEMENT_UNEXPECTED"
    assert caught.value.http_status == 422


def test_an_acknowledged_regression_adopts_the_candidate(session: Session, workspace: str) -> None:
    ids = add_suite(session, workspace)
    run = service.run_regression(session, workspace, DEFAULT_POLICY_V1, candidate_policy())
    text_written = "Accepted: the ready order would now be held for QC review."

    adoption = service.adopt_policy(
        session, workspace, run.id, "owner", {ids["ready"]: text_written}, OWNER
    )

    assert adoption.regression_run_id == run.id
    assert adoption.policy_digest == run.candidate_policy_digest
    assert adoption.adopted_by == OWNER
    assert adoption.acknowledgements == {ids["ready"]: text_written}
    assert adoption.run_complete is True


def test_adoption_never_mutates_the_stored_policies(session: Session, workspace: str) -> None:
    ids = add_suite(session, workspace)
    run = service.run_regression(session, workspace, DEFAULT_POLICY_V1, candidate_policy())
    before = {
        row.policy_digest: (row.label, row.policy)
        for row in session.scalars(select(StoredPolicy).where(StoredPolicy.workspace_id == workspace))
    }

    service.adopt_policy(session, workspace, run.id, "owner", {ids["ready"]: "Accepted."}, OWNER)

    after = {
        row.policy_digest: (row.label, row.policy)
        for row in session.scalars(select(StoredPolicy).where(StoredPolicy.workspace_id == workspace))
    }
    assert after == before
    assert policy_digest(DEFAULT_POLICY_V1) in after


def test_a_suite_change_after_the_run_blocks_adoption(session: Session, workspace: str) -> None:
    ids = add_suite(session, workspace)
    run = service.run_regression(session, workspace, DEFAULT_POLICY_V1, candidate_policy())
    world = ready_world()
    service.create_case(
        session, workspace, "case-new-" + uid(), "added later", world.cutoff, world.order_id,
        world.facts, world.coverage, synthetic=True,
    )
    with pytest.raises(ServiceError) as caught:
        service.adopt_policy(session, workspace, run.id, "owner", {ids["ready"]: "Accepted."}, OWNER)
    assert caught.value.code == "SUITE_CHANGED"


def test_a_new_expectation_revision_blocks_adoption_of_the_old_run(
    session: Session, workspace: str
) -> None:
    ids = add_suite(session, workspace)
    run = service.run_regression(session, workspace, DEFAULT_POLICY_V1, candidate_policy())
    service.add_expectation(
        session, workspace, ids["review"],
        Expectation(correct=Recommendation.ACCEPT, rationale="re-labelled"),
    )
    with pytest.raises(ServiceError) as caught:
        service.adopt_policy(session, workspace, run.id, "owner", {ids["ready"]: "Accepted."}, OWNER)
    assert caught.value.code == "SUITE_CHANGED"


def test_a_run_in_another_workspace_is_not_found(session: Session, workspace: str) -> None:
    ids = add_suite(session, workspace)
    run = service.run_regression(session, workspace, DEFAULT_POLICY_V1, candidate_policy())
    other = "ws-" + uid()
    with pytest.raises(ServiceError) as caught:
        service.adopt_policy(session, other, run.id, "owner", {ids["ready"]: "Accepted."}, OWNER)
    assert caught.value.code == "RUN_NOT_FOUND"


def test_a_workspace_run_only_covers_its_own_cases(session: Session, workspace: str) -> None:
    ids = add_suite(session, workspace)
    other = "ws-" + uid()
    run = service.run_regression(session, other, DEFAULT_POLICY_V1, candidate_policy())

    assert run.results == []
    assert run.complete is False
    assert ids["ready"] not in {item["case_id"] for item in run.results}


def test_the_database_refuses_an_adoption_of_a_different_digest(
    session: Session, workspace: str
) -> None:
    add_suite(session, workspace)
    run = service.run_regression(session, workspace, DEFAULT_POLICY_V1, candidate_policy())
    message = _rejected(
        session,
        """
        INSERT INTO policy_adoptions (workspace_id, id, regression_run_id, run_complete,
            policy_digest, adopted_by, acknowledgements, created_at)
        VALUES (:ws, :id, :run, true, :digest, 'owner', CAST('{}' AS jsonb), now())
        """,
        {"ws": workspace, "id": uid(), "run": run.id, "digest": run.baseline_policy_digest},
    )
    assert "foreign key" in message.lower()


def test_the_database_refuses_an_adoption_of_an_incomplete_run(
    session: Session, workspace: str
) -> None:
    world = ready_world()
    service.create_case(
        session, workspace, "case-lonely-" + uid(), "no gold", world.cutoff, world.order_id,
        world.facts, world.coverage, synthetic=True,
    )
    run = service.run_regression(session, workspace, DEFAULT_POLICY_V1, candidate_policy())
    assert run.complete is False
    message = _rejected(
        session,
        """
        INSERT INTO policy_adoptions (workspace_id, id, regression_run_id, run_complete,
            policy_digest, adopted_by, acknowledgements, created_at)
        VALUES (:ws, :id, :run, true, :digest, 'owner', CAST('{}' AS jsonb), now())
        """,
        {"ws": workspace, "id": uid(), "run": run.id, "digest": run.candidate_policy_digest},
    )
    assert "foreign key" in message.lower()


# ---------------------------------------------------------------------------
# Append-only guards
# ---------------------------------------------------------------------------


@pytest.fixture
def stored(session: Session, workspace: str) -> dict[str, str]:
    """One row in every new table: a case, a revision, a complete run and its adoption."""
    ids = add_suite(session, workspace)
    run = service.run_regression(session, workspace, DEFAULT_POLICY_V1, candidate_policy())
    adoption = service.adopt_policy(
        session, workspace, run.id, "owner", {ids["ready"]: "Accepted."}, OWNER
    )
    session.flush()
    return {
        "ws": workspace,
        "case": ids["ready"],
        "digest": run.candidate_policy_digest,
        "run": run.id,
        "adoption": adoption.id,
    }


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE policies SET label = 'x' WHERE workspace_id = :ws",
        "DELETE FROM policies WHERE workspace_id = :ws",
        "UPDATE decision_cases SET name = 'x' WHERE workspace_id = :ws AND id = :case",
        "DELETE FROM decision_cases WHERE workspace_id = :ws AND id = :case",
        "UPDATE case_expectations SET revision = 9 WHERE workspace_id = :ws AND case_id = :case",
        "DELETE FROM case_expectations WHERE workspace_id = :ws AND case_id = :case",
        "UPDATE regression_runs SET suite_digest = 'x' WHERE workspace_id = :ws AND id = :run",
        "DELETE FROM regression_runs WHERE workspace_id = :ws AND id = :run",
        "UPDATE policy_adoptions SET adopted_by = 'x' WHERE workspace_id = :ws AND id = :adoption",
        "DELETE FROM policy_adoptions WHERE workspace_id = :ws AND id = :adoption",
    ],
)
def test_update_and_delete_are_rejected_on_regression_tables(
    session: Session, stored: dict[str, str], statement: str
) -> None:
    assert "append-only" in _rejected(session, statement, stored)


@pytest.mark.parametrize(
    "table",
    ["policies", "decision_cases", "case_expectations", "regression_runs", "policy_adoptions"],
)
def test_truncate_is_rejected_on_regression_tables(
    session: Session, stored: dict[str, str], table: str
) -> None:
    assert "append-only" in _rejected(session, f"TRUNCATE {table} CASCADE", stored)


def test_stored_rows_are_readable_as_their_models(session: Session, stored: dict[str, str]) -> None:
    assert session.get(StoredPolicy, (stored["ws"], session.scalar(
        select(StoredPolicy.id).where(StoredPolicy.policy_digest == stored["digest"])
    ))) is not None
    assert session.get(DecisionCase, (stored["ws"], stored["case"])) is not None
    assert session.scalar(
        select(func.count()).select_from(CaseExpectation).where(CaseExpectation.case_id == stored["case"])
    ) == 1
    assert session.get(PolicyAdoption, (stored["ws"], stored["adoption"])) is not None
