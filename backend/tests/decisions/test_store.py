"""Database-backed tests for the append-only fact store.

Rows can never be deleted (the triggers forbid it), so every test works in a uuid
workspace with uuid ids and keys, and the session fixture rolls its transaction back.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from decisions.strategies import fact_histories
from flooreplay.db import SessionLocal
from flooreplay.decisions import service, snapshot
from flooreplay.decisions.facts import validate_fact
from flooreplay.decisions.models import DecisionSourceArtifact, FactRow
from flooreplay.decisions.types import Fact, FactKind, SourceProfile
from flooreplay.errors import ServiceError
from flooreplay.workspaces import allowed_workspaces, write_workspace

T0 = datetime(2026, 3, 1, 8, 0, tzinfo=UTC)


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


def lot_fact(
    key: str | None = None,
    *,
    id: str | None = None,
    kg: str = "100",
    kind: FactKind = FactKind.FABRIC_LOT,
    valid_from: datetime = T0,
    valid_to: datetime | None = None,
    known_at: datetime = T0,
    supersedes_id: str | None = None,
) -> Fact:
    payload: dict[str, Any] = {"qty": {"value": kg, "unit": "kg"}}
    if kind is FactKind.FABRIC_LOT:
        payload |= {"fabric_quality": "SJ180", "colour": "NAVY"}
    else:  # fabric_qc shares the lot entity shape
        payload |= {"issue": "shade_fail", "review_state": "checks_passed", "origin": "notes"}
    return Fact(
        id=id or "F-" + uid(),
        kind=kind,
        entity_key=key or "lot:" + uid(),
        payload=payload,
        valid_from=valid_from,
        valid_to=valid_to,
        known_at=known_at,
        supersedes_id=supersedes_id,
        source=SourceProfile.ERP_FABRIC_STOCK,
        artifact_id=None,
    )


def append(session: Session, workspace: str, fact: Fact) -> FactRow:
    return service.append_fact(session, fact, workspace_id=workspace, trusted_known_at=fact.known_at)


def artifact_row(workspace: str, *, key: str | None = None) -> DecisionSourceArtifact:
    return DecisionSourceArtifact(
        id="A-" + uid(),
        workspace_id=workspace,
        profile="erp_fabric_stock",
        filename="stock.csv",
        raw_bytes=b"lot,qty\nL1,10\n",
        raw_digest="sha256:" + "0" * 64,
        as_of=T0,
        known_at=T0 + timedelta(hours=1),
        coverage={"fabric_qualities": ["SJ180"]},
        idempotency_key=key or uid(),
        preview_digest="sha256:" + "1" * 64,
    )


# ---------------------------------------------------------------------------
# Database immutability
# ---------------------------------------------------------------------------


def _rejected(session: Session, statement: str, params: dict[str, Any] | None = None) -> str:
    """Run raw SQL in a SAVEPOINT; assert the database refuses and return its message."""
    with pytest.raises(DBAPIError) as caught, session.begin_nested():
        session.execute(text(statement), params or {})
    return str(caught.value)


@pytest.fixture
def stored(session: Session, workspace: str) -> dict[str, Any]:
    artifact = artifact_row(workspace)
    session.add(artifact)
    session.flush()
    fact = lot_fact()
    row = service.append_fact(
        session,
        fact.model_copy(update={"artifact_id": artifact.id}),
        workspace_id=workspace,
        trusted_known_at=T0,
    )
    return {"fact": row.id, "artifact": artifact.id}


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE facts SET kind = 'bom' WHERE id = :fact",
        "UPDATE facts SET payload = '{}'::jsonb WHERE id = :fact",
        "DELETE FROM facts WHERE id = :fact",
        "UPDATE decision_source_artifacts SET filename = 'x' WHERE id = :artifact",
        "DELETE FROM decision_source_artifacts WHERE id = :artifact",
    ],
)
def test_update_and_delete_are_rejected_by_the_database(
    session: Session, stored: dict[str, Any], statement: str
) -> None:
    assert "append-only" in _rejected(session, statement, stored)


@pytest.mark.parametrize("table", ["facts", "decision_source_artifacts"])
def test_truncate_is_rejected_by_the_database(
    session: Session, stored: dict[str, Any], table: str
) -> None:
    assert "append-only" in _rejected(session, f"TRUNCATE {table} CASCADE")


def test_a_no_op_update_is_rejected_too(session: Session, stored: dict[str, Any]) -> None:
    assert "append-only" in _rejected(session, "UPDATE facts SET kind = kind WHERE id = :fact", stored)


_FACT_INSERT = """
INSERT INTO facts (id, workspace_id, kind, entity_key, payload, valid_from, valid_to, known_at,
                   source, semantic_digest, created_at)
VALUES (:id, :ws, 'fabric_lot', :key, '{}'::jsonb, :valid_from, :valid_to, :known_at,
        'erp_fabric_stock', 'sha256:x', now())
"""


def _insert_params(workspace: str, **override: Any) -> dict[str, Any]:
    params: dict[str, Any] = {
        "id": "F-" + uid(),
        "ws": workspace,
        "key": "lot:" + uid(),
        "valid_from": T0,
        "valid_to": None,
        "known_at": T0,
    }
    return params | override


def test_raw_insert_baseline_is_accepted(session: Session, workspace: str) -> None:
    session.execute(text(_FACT_INSERT), _insert_params(workspace))


@pytest.mark.parametrize(
    ("override", "constraint"),
    [
        ({"valid_to": T0}, "ck_facts_valid_interval"),
        ({"valid_to": T0 - timedelta(hours=1)}, "ck_facts_valid_interval"),
        ({"known_at": T0 - timedelta(seconds=1)}, "ck_facts_no_backdating"),
    ],
)
def test_check_constraints_reject_inverted_and_backdated_facts(
    session: Session, workspace: str, override: dict[str, Any], constraint: str
) -> None:
    with pytest.raises(IntegrityError) as caught, session.begin_nested():
        session.execute(text(_FACT_INSERT), _insert_params(workspace, **override))
    assert constraint in str(caught.value)


def test_artifact_as_of_cannot_be_after_known_at(session: Session, workspace: str) -> None:
    row = artifact_row(workspace)
    row.as_of = row.known_at + timedelta(seconds=1)
    with pytest.raises(IntegrityError) as caught, session.begin_nested():
        session.add(row)
        session.flush()
    assert "ck_decision_source_artifacts_no_backdating" in str(caught.value)


def test_artifact_idempotency_key_is_unique_per_workspace(session: Session, workspace: str) -> None:
    key = uid()
    session.add(artifact_row(workspace, key=key))
    session.add(artifact_row("ws-" + uid(), key=key))  # another workspace may reuse it
    session.flush()
    with pytest.raises(IntegrityError), session.begin_nested():
        session.add(artifact_row(workspace, key=key))
        session.flush()


# ---------------------------------------------------------------------------
# append_fact
# ---------------------------------------------------------------------------


def test_append_round_trips_a_fact(session: Session, workspace: str) -> None:
    fact = lot_fact(valid_to=T0 + timedelta(days=2), known_at=T0 + timedelta(hours=1))
    row = append(session, workspace, fact)
    assert row.workspace_id == workspace
    assert row.semantic_digest.startswith("sha256:")
    # The store keeps the validated (normalised) form of what it was given.
    assert service.load_facts(session, workspace) == [validate_fact(fact)]


def test_invalid_payload_and_entity_key_are_fact_invalid(session: Session, workspace: str) -> None:
    bad_key = lot_fact("order:" + uid())  # a fabric_lot must be keyed lot:{id}
    with pytest.raises(ServiceError) as caught:
        append(session, workspace, bad_key)
    assert caught.value.code == "FACT_INVALID"
    bad_payload = lot_fact().model_copy(update={"payload": {"qty": {"value": "1", "unit": "kg"}}})
    with pytest.raises(ServiceError) as caught:
        append(session, workspace, bad_payload)
    assert caught.value.code == "FACT_INVALID"
    assert service.load_facts(session, workspace) == []


def test_duplicate_id_is_rejected(session: Session, workspace: str) -> None:
    first = lot_fact()
    append(session, workspace, first)
    with pytest.raises(ServiceError) as caught:
        append(session, workspace, first.model_copy(update={"known_at": T0 + timedelta(hours=1)}))
    assert caught.value.code == "FACT_ID_TAKEN"


def test_id_owned_by_another_workspace_is_rejected_without_poisoning_the_session(
    session: Session, workspace: str
) -> None:
    shared = lot_fact()
    append(session, "ws-" + uid(), shared)
    with pytest.raises(ServiceError) as caught:
        append(session, workspace, shared.model_copy(update={"entity_key": "lot:" + uid()}))
    assert caught.value.code == "FACT_REJECTED"
    assert append(session, workspace, lot_fact()) is not None  # the session is still usable


def test_valid_correction_chain_is_accepted(session: Session, workspace: str) -> None:
    key = "lot:" + uid()
    first = lot_fact(key)
    second = lot_fact(key, kg="90", known_at=T0 + timedelta(hours=1), supersedes_id=first.id)
    append(session, workspace, first)
    append(session, workspace, second)
    third = lot_fact(key, kg="80", known_at=T0 + timedelta(hours=2), supersedes_id=second.id)
    append(session, workspace, third)
    visible = service.snapshot_at(session, workspace, T0 + timedelta(hours=3)).facts
    assert [f.id for f in visible] == [third.id]


def test_correction_of_an_unknown_target_is_rejected(session: Session, workspace: str) -> None:
    fact = lot_fact(supersedes_id="F-" + uid())
    with pytest.raises(ServiceError) as caught:
        append(session, workspace, fact)
    assert caught.value.code == "CORRECTION_INVALID"
    assert "unknown_target" in caught.value.message


def test_correction_of_another_workspaces_fact_is_unknown(session: Session, workspace: str) -> None:
    key = "lot:" + uid()
    foreign = lot_fact(key)
    append(session, "ws-" + uid(), foreign)
    fact = lot_fact(key, known_at=T0 + timedelta(hours=1), supersedes_id=foreign.id)
    with pytest.raises(ServiceError) as caught:
        append(session, workspace, fact)
    assert "unknown_target" in caught.value.message


def test_correction_must_be_known_strictly_after_its_target(session: Session, workspace: str) -> None:
    key = "lot:" + uid()
    base = lot_fact(key)
    middle = lot_fact(key, known_at=T0 + timedelta(hours=2), supersedes_id=base.id)
    for fact in (base, middle):
        append(session, workspace, fact)
    # Earlier than the target it replaces, and also equal to it: both are rejected.
    for known_at in (T0 + timedelta(hours=1), T0 + timedelta(hours=2)):
        late = lot_fact(key, known_at=known_at, supersedes_id=middle.id)
        with pytest.raises(ServiceError) as caught:
            append(session, workspace, late)
        assert caught.value.code == "CORRECTION_INVALID"
        assert "not_after_target" in caught.value.message


def test_correction_of_a_different_kind_is_rejected(session: Session, workspace: str) -> None:
    key = "lot:" + uid()
    lot = lot_fact(key)
    append(session, workspace, lot)
    qc = lot_fact(
        key, kind=FactKind.FABRIC_QC, known_at=T0 + timedelta(hours=1), supersedes_id=lot.id
    )
    with pytest.raises(ServiceError) as caught:
        append(session, workspace, qc)
    assert caught.value.code == "CORRECTION_INVALID"
    assert "kind_mismatch" in caught.value.message


def test_correction_of_a_different_entity_is_rejected(session: Session, workspace: str) -> None:
    first = lot_fact()
    append(session, workspace, first)
    other = lot_fact(known_at=T0 + timedelta(hours=1), supersedes_id=first.id)
    with pytest.raises(ServiceError) as caught:
        append(session, workspace, other)
    assert "entity_mismatch" in caught.value.message


def test_rejected_appends_leave_nothing_behind(session: Session, workspace: str) -> None:
    with pytest.raises(ServiceError):
        append(session, workspace, lot_fact(supersedes_id="F-" + uid()))
    assert service.load_facts(session, workspace) == []


# ---------------------------------------------------------------------------
# known_at is the server's
# ---------------------------------------------------------------------------


def test_client_supplied_known_at_is_rejected_without_the_trusted_flag(
    session: Session, workspace: str
) -> None:
    for known_at in (T0, datetime.now(UTC) - timedelta(days=1), datetime.now(UTC) + timedelta(days=1)):
        fact = lot_fact(valid_from=T0 - timedelta(days=30), known_at=known_at)
        with pytest.raises(ServiceError) as caught:
            service.append_fact(session, fact, workspace_id=workspace)
        assert caught.value.code == "KNOWN_AT_CLIENT_SUPPLIED"
    assert service.load_facts(session, workspace) == []


def test_untrusted_append_stores_the_server_clock(
    session: Session, workspace: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    server_time = datetime.now(UTC) + timedelta(seconds=7)
    monkeypatch.setattr(service, "utc_now", lambda: server_time)
    fact = lot_fact(valid_from=server_time - timedelta(hours=1), known_at=server_time)
    row = service.append_fact(session, fact, workspace_id=workspace)
    assert row.known_at == server_time


def test_trusted_known_at_overrides_the_fact(session: Session, workspace: str) -> None:
    fact = lot_fact(known_at=T0)
    row = service.append_fact(
        session, fact, workspace_id=workspace, trusted_known_at=T0 + timedelta(hours=5)
    )
    assert row.known_at == T0 + timedelta(hours=5)


def test_trusted_known_at_must_be_timezone_aware(session: Session, workspace: str) -> None:
    with pytest.raises(ServiceError) as caught:
        service.append_fact(
            session, lot_fact(), workspace_id=workspace, trusted_known_at=datetime(2026, 3, 1)
        )
    assert caught.value.code == "KNOWN_AT_INVALID"


def test_no_backdating_valid_from_cannot_be_after_known_at(session: Session, workspace: str) -> None:
    future = lot_fact(valid_from=T0 + timedelta(hours=1))
    with pytest.raises(ServiceError) as caught:
        service.append_fact(session, future, workspace_id=workspace, trusted_known_at=T0)
    assert caught.value.code == "BACKDATED"
    now = datetime.now(UTC)
    with pytest.raises(ServiceError) as caught:  # same rule against the server clock
        service.append_fact(
            session,
            lot_fact(valid_from=now + timedelta(hours=1), known_at=now),
            workspace_id=workspace,
        )
    assert caught.value.code == "BACKDATED"


# ---------------------------------------------------------------------------
# Workspace isolation
# ---------------------------------------------------------------------------


def test_facts_are_invisible_across_workspaces(session: Session) -> None:
    ws_a, ws_b = "ws-" + uid(), "ws-" + uid()
    key = "lot:" + uid()
    fact = lot_fact(key)
    append(session, ws_a, fact)
    assert service.load_facts(session, ws_a) == [validate_fact(fact)]
    assert service.load_facts(session, ws_b) == []
    assert service.load_facts(session, ws_b, entity_keys=[key]) == []
    assert service.snapshot_at(session, ws_b, T0 + timedelta(days=1)).facts == ()
    # The same entity key in B starts a fresh history, unaffected by A.
    other = lot_fact(key, kg="5")
    append(session, ws_b, other)
    assert service.load_facts(session, ws_a, entity_keys=[key]) == [validate_fact(fact)]
    assert service.load_facts(session, ws_b, entity_keys=[key]) == [validate_fact(other)]


def test_workspace_scope_hides_other_workspaces_even_by_explicit_id(session: Session) -> None:
    ws_a, ws_b = "ws-" + uid(), "ws-" + uid()
    append(session, ws_a, lot_fact())
    append(session, ws_b, lot_fact())
    token = allowed_workspaces.set((ws_a,))
    try:
        assert len(service.load_facts(session, ws_a)) == 1
        assert service.load_facts(session, ws_b) == []
        assert session.query(DecisionSourceArtifact).count() == 0
        with pytest.raises(ServiceError) as caught:
            append(session, ws_b, lot_fact())
        assert caught.value.code == "WORKSPACE_UNKNOWN"
    finally:
        allowed_workspaces.reset(token)


def test_new_rows_default_to_the_write_workspace(session: Session) -> None:
    ws = "ws-" + uid()
    allowed = allowed_workspaces.set((ws,))
    writing = write_workspace.set(ws)
    try:
        fact = lot_fact()
        row = FactRow(
            id=fact.id,
            kind=fact.kind.value,
            entity_key=fact.entity_key,
            payload={},
            valid_from=T0,
            known_at=T0,
            source="erp_fabric_stock",
            semantic_digest="sha256:x",
        )
        artifact = DecisionSourceArtifact(**{
            k: v for k, v in vars(artifact_row(ws)).items() if not k.startswith("_") and k != "workspace_id"
        })
        session.add_all([artifact, row])
        session.flush()
        assert row.workspace_id == ws
        assert artifact.workspace_id == ws
    finally:
        write_workspace.reset(writing)
        allowed_workspaces.reset(allowed)


# ---------------------------------------------------------------------------
# Database versus pure snapshot
# ---------------------------------------------------------------------------


@settings(
    max_examples=25,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
@given(history=fact_histories(), picks=st.lists(st.integers(0, 10**6), min_size=1, max_size=4))
def test_db_snapshot_equals_the_pure_snapshot(
    session: Session, history: list[Fact], picks: list[int]
) -> None:
    workspace = "ws-" + uid()
    prefix = uid()[:12] + "-"
    artifact = artifact_row(workspace)
    session.add(artifact)
    session.flush()

    def remap(fact: Fact) -> Fact:
        return fact.model_copy(
            update={
                "id": prefix + fact.id,
                "supersedes_id": prefix + fact.supersedes_id if fact.supersedes_id else None,
                "artifact_id": artifact.id if fact.artifact_id else None,
            }
        )

    # The store persists the validated, normalised form of each fact (for example payload
    # decimals lose trailing zeros), so the pure side is fed the same normalised facts.
    mapped = [validate_fact(remap(f)) for f in history]
    try:
        for fact in mapped:
            service.append_fact(session, fact, workspace_id=workspace, trusted_known_at=fact.known_at)
        cutoffs = {
            max(f.known_at for f in mapped) + timedelta(days=1),
            min(f.known_at for f in mapped) - timedelta(seconds=1),
            *(mapped[pick % len(mapped)].known_at for pick in picks),
        }
        for cutoff in sorted(cutoffs):
            from_db = service.snapshot_at(session, workspace, cutoff)
            pure = snapshot.snapshot_at(mapped, cutoff)
            assert from_db.digest == pure.digest
            assert from_db == pure
    finally:
        session.rollback()
