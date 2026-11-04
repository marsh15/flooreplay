"""Review queue tests (T20): service rules and the HTTP surface.

Mock data only, uuid workspaces and keys, because the append-only triggers forbid cleanup.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from flooreplay.api import app
from flooreplay.auth import create_account, sign_in
from flooreplay.db import session_scope
from flooreplay.decisions import review_service as rs
from flooreplay.decisions import service, snapshot
from flooreplay.decisions.models import (
    DecisionEvaluation,
    FactRow,
    NoteExtraction,
    ReviewEvent,
    ReviewItem,
)
from flooreplay.decisions.review_service import FactDraft
from flooreplay.decisions.types import Fact, FactKind, Recommendation, SourceProfile
from flooreplay.errors import ServiceError
from flooreplay.workspaces import DEMO, Workspace, WorkspaceMember

PASSWORD = "review-test-password-long"
ROUTE = "/api/v1/decisions/review-items"
PAST = datetime(2026, 3, 1, 8, 0, tzinfo=UTC)


def uid() -> str:
    return uuid.uuid4().hex


def new_account() -> str:
    return str(create_account("review-" + uid(), PASSWORD, "reviewer")["id"])


def new_workspace(session: Any) -> str:
    ws = str(uuid.uuid4())
    session.add(Workspace(id=ws, name="ws-" + uid(), visibility="private"))
    session.flush()
    return ws


def add_member(session: Any, ws: str, account_id: str, role: str = "member") -> None:
    session.add(WorkspaceMember(workspace_id=ws, account_id=account_id, role=role))
    session.flush()


def checks_for(failed: dict[str, str], missing: tuple[str, ...] = ()) -> dict[str, Any]:
    """Mock `checks-v2` output: `qty` and `issue` are checked, `lot_id` passed."""
    fields: list[dict[str, Any]] = [
        {"field": "lot_id", "status": "passed", "value": "L9", "span": {"start": 0, "end": 2, "text": "L9"}}
    ]
    results: list[dict[str, Any]] = [
        {"field": "lot_id", "check": "lot", "status": "passed", "code": "ok", "detail": ""}
    ]
    failed_fields: list[str] = []
    for name, code in failed.items():
        fields.append({"field": name, "status": "failed", "value": None, "span": None})
        results.append({"field": name, "check": "span", "status": "claimed_and_failed", "code": code, "detail": ""})
        failed_fields.append(name)
    for name in missing:
        fields.append({"field": name, "status": "missing", "value": None, "span": None})
        results.append({"field": name, "check": "presence", "status": "missing", "code": "missing", "detail": ""})
        failed_fields.append(name)
    return {
        "fields": fields,
        "results": results,
        "failed_fields": failed_fields,
        "outcome": "needs_review" if failed_fields else "checks_passed",
    }


def make_extraction(session: Any, ws: str, checks: dict[str, Any], claimed_qty: str = "50") -> str:
    eid = str(uuid.uuid4())
    signal = {
        "lot_id": {"value": "L9", "evidence": "L9"},
        "qty": {"value": claimed_qty, "evidence": claimed_qty + " kg"},
        "issue": {"value": "shade_fail", "evidence": "shade off"},
    }
    session.add(
        NoteExtraction(
            workspace_id=ws,
            id=eid,
            note_id="note-" + uid(),
            note_digest="sha256:" + uid() + uid(),
            model="mock-model",
            prompt_version="review-test",
            schema_version="note-signal-v2",
            status="COMPLETED",
            language="en",
            raw_output={},
            signal=signal,
            checks=checks,
            field_status={f["field"]: f["status"] for f in checks["fields"]},
            cost_usd=0.0,
            created_by="review-test",
        )
    )
    session.flush()
    return eid


def make_evaluation(session: Any, ws: str, outcome: Recommendation) -> str:
    eid = str(uuid.uuid4())
    session.add(
        DecisionEvaluation(
            workspace_id=ws,
            id=eid,
            order_id="order-" + uid(),
            cutoff=datetime(2026, 3, 2, 9, 0, tzinfo=UTC),
            policy_digest="sha256:" + uid() + uid(),
            policy={},
            engine_version="engine-test",
            snapshot_digest="sha256:" + uid() + uid(),
            decision_digest="sha256:" + uid() + uid(),
            outcome=outcome.value,
            result={},
        )
    )
    session.flush()
    return eid


def qc_draft(lot: str, qty: str, supersedes_id: str | None = None) -> FactDraft:
    return FactDraft(
        kind=FactKind.FABRIC_QC,
        entity_key=f"lot:{lot}",
        payload={"issue": "shade_fail", "qty": {"value": qty, "unit": "kg"}},
        supersedes_id=supersedes_id,
    )


def fact_count(ws: str) -> int:
    with session_scope() as session:
        return int(session.scalar(select(func.count()).select_from(FactRow).where(FactRow.workspace_id == ws)) or 0)


def failed_item(ws: str) -> tuple[str, str]:
    """One extraction with a failed qty and a missing issue. Returns (extraction id, qty item id)."""
    with session_scope() as session:
        eid = make_extraction(session, ws, checks_for({"qty": "span_not_found"}, missing=("issue",)))
    with session_scope() as session:
        items = rs.enqueue_from_extraction(session, ws, eid)
        qty = next(item.id for item in items if item.field_name == "qty")
    return eid, qty


# ---------------------------------------------------------------------------
# Service rules
# ---------------------------------------------------------------------------


def test_enqueue_is_idempotent_and_keeps_the_claim() -> None:
    with session_scope() as session:
        ws = new_workspace(session)
        eid = make_extraction(session, ws, checks_for({"qty": "span_not_found"}, missing=("issue",)))
    with session_scope() as session:
        first = sorted(item.id for item in rs.enqueue_from_extraction(session, ws, eid))
    with session_scope() as session:
        again = sorted(item.id for item in rs.enqueue_from_extraction(session, ws, eid))
    assert first == again and len(first) == 2
    with session_scope() as session:
        qty = session.execute(
            select(ReviewItem).where(ReviewItem.workspace_id == ws, ReviewItem.field_name == "qty")
        ).scalar_one()
        assert qty.field_status == "failed"
        assert qty.check_codes == ["span_not_found"]
        assert qty.claimed_value == "50"
        assert qty.evidence_span is None


def test_clean_extraction_adds_no_items() -> None:
    with session_scope() as session:
        ws = new_workspace(session)
        eid = make_extraction(session, ws, checks_for({}))
    with session_scope() as session:
        assert rs.enqueue_from_extraction(session, ws, eid) == []


def test_state_is_derived_from_the_latest_event() -> None:
    owner = new_account()
    with session_scope() as session:
        ws = new_workspace(session)
        add_member(session, ws, owner, "owner")
    _, item = failed_item(ws)
    with session_scope() as session:
        assert rs.get_item(session, ws, item).item.state == "OPEN"
        rs.assign(session, ws, item, owner, owner)
    with session_scope() as session:
        view = rs.get_item(session, ws, item).item
        assert (view.state, view.assignee_id) == ("ASSIGNED", owner)
        assert [v.id for v in rs.list_items(session, ws, state="ASSIGNED")] == [item]
        assert rs.list_items(session, ws, assignee=owner)[0].id == item
    with session_scope() as session:
        rs.assign(session, ws, item, owner, None)
    with session_scope() as session:
        view = rs.get_item(session, ws, item).item
        assert (view.state, view.assignee_id) == ("OPEN", None)
        assert view.claimed_value == "50"  # the state never touches the claim


def test_confirm_needs_a_written_note() -> None:
    owner = new_account()
    with session_scope() as session:
        ws = new_workspace(session)
        add_member(session, ws, owner, "owner")
        eid = make_extraction(session, ws, checks_for({}, missing=("issue",)))
        item = next(i.id for i in rs.enqueue_from_extraction(session, ws, eid) if i.field_name == "issue")
    with session_scope() as session, pytest.raises(ServiceError) as exc:
        rs.confirm(session, ws, item, owner, note="   ")
    assert exc.value.code == "NOTE_REQUIRED" and exc.value.http_status == 422
    with session_scope() as session:
        view = rs.confirm(session, ws, item, owner, note="checked the source note")
    assert view.state == "CONFIRMED" and view.resulting_fact_id is None


def test_confirming_a_failed_field_needs_the_attested_value_and_fact() -> None:
    owner = new_account()
    with session_scope() as session:
        ws = new_workspace(session)
        add_member(session, ws, owner, "owner")
    _, item = failed_item(ws)
    with session_scope() as session, pytest.raises(ServiceError) as exc:
        rs.confirm(session, ws, item, owner, note="I checked it", fact=qc_draft("L9", "50"))
    assert exc.value.code == "VALUE_REQUIRED"
    with session_scope() as session, pytest.raises(ServiceError) as exc:
        rs.confirm(session, ws, item, owner, note="I checked it", value="50")
    assert exc.value.code == "FACT_REQUIRED"
    with session_scope() as session:
        view = rs.confirm(session, ws, item, owner, note="I checked it", value="50", fact=qc_draft("L9", "50"))
    assert view.state == "CONFIRMED" and view.resulting_fact_id == "review-" + item
    with session_scope() as session:
        row = session.get(FactRow, (ws, "review-" + item))
        assert row is not None
        assert row.payload["origin"] == "human_review"
        assert row.source == SourceProfile.REVIEW_QUEUE.value


def test_correct_appends_a_superseding_fact_visible_in_a_later_snapshot() -> None:
    owner = new_account()
    prior_id = "qc-" + uid()[:12]
    with session_scope() as session:
        ws = new_workspace(session)
        add_member(session, ws, owner, "owner")
        service.append_facts(
            session,
            [
                Fact(
                    id=prior_id,
                    kind=FactKind.FABRIC_QC,
                    entity_key="lot:L9",
                    payload={
                        "issue": "shade_fail",
                        "qty": {"value": "50", "unit": "kg"},
                        "review_state": "checks_passed",
                        "origin": "notes",
                    },
                    valid_from=PAST,
                    valid_to=None,
                    known_at=PAST + timedelta(minutes=30),
                    supersedes_id=None,
                    source=SourceProfile.NOTES,
                    artifact_id=None,
                )
            ],
            workspace_id=ws,
            trusted_known_at=PAST + timedelta(minutes=30),
        )
    _, item = failed_item(ws)
    with session_scope() as session:
        view = rs.correct(
            session, ws, item, owner, note="qty on the delivery note is 60", value="60",
            fact=qc_draft("L9", "60", supersedes_id=prior_id),
        )
        assert view.state == "CORRECTED" and view.resulting_fact_id == "review-" + item
    before = PAST + timedelta(hours=1)
    after = datetime.now(UTC) + timedelta(minutes=5)
    with session_scope() as session:
        seen_before = snapshot.events(service.snapshot_at(session, ws, before), FactKind.FABRIC_QC, "lot:L9")
        seen_after = snapshot.events(service.snapshot_at(session, ws, after), FactKind.FABRIC_QC, "lot:L9")
    assert [f.id for f in seen_before] == [prior_id]
    assert [f.id for f in seen_after] == ["review-" + item]
    assert seen_after[0].supersedes_id == prior_id
    assert seen_after[0].payload["qty"]["value"] == "60"
    assert seen_after[0].payload["origin"] == "human_review"
    with session_scope() as session:
        assert rs.get_item(session, ws, item).item.claimed_value == "50"  # the claim is still readable


def test_correct_without_a_fact_or_value_is_refused() -> None:
    owner = new_account()
    with session_scope() as session:
        ws = new_workspace(session)
        add_member(session, ws, owner, "owner")
    _, item = failed_item(ws)
    with session_scope() as session, pytest.raises(ServiceError) as exc:
        rs.correct(session, ws, item, owner, note="fix", value="60", fact=None)
    assert exc.value.code == "FACT_REQUIRED"
    with session_scope() as session, pytest.raises(ServiceError) as exc:
        rs.correct(session, ws, item, owner, note="fix", value=None, fact=qc_draft("L9", "60"))
    assert exc.value.code == "VALUE_REQUIRED"


def test_reject_creates_no_fact_and_keeps_the_claim() -> None:
    owner = new_account()
    with session_scope() as session:
        ws = new_workspace(session)
        add_member(session, ws, owner, "owner")
    _, item = failed_item(ws)
    before = fact_count(ws)
    with session_scope() as session:
        view = rs.reject(session, ws, item, owner, note="the note is about another lot")
    assert view.state == "REJECTED" and view.resulting_fact_id is None
    assert fact_count(ws) == before
    with session_scope() as session:
        assert rs.get_item(session, ws, item).item.claimed_value == "50"


def test_a_decided_item_cannot_be_decided_again() -> None:
    owner = new_account()
    with session_scope() as session:
        ws = new_workspace(session)
        add_member(session, ws, owner, "owner")
    _, item = failed_item(ws)
    with session_scope() as session:
        rs.reject(session, ws, item, owner, note="not a defect")
    for attempt in (
        lambda s: rs.reject(s, ws, item, owner, note="again"),
        lambda s: rs.confirm(s, ws, item, owner, note="again"),
        lambda s: rs.correct(s, ws, item, owner, note="again", value="60", fact=qc_draft("L9", "60")),
        lambda s: rs.assign(s, ws, item, owner, owner),
    ):
        with session_scope() as session, pytest.raises(ServiceError) as exc:
            attempt(session)
        assert exc.value.code == "REVIEW_ALREADY_DECIDED" and exc.value.http_status == 409


def test_only_the_assignee_or_an_owner_can_decide() -> None:
    owner = new_account()
    member = new_account()
    with session_scope() as session:
        ws = new_workspace(session)
        add_member(session, ws, owner, "owner")
        add_member(session, ws, member, "member")
    _, item = failed_item(ws)
    with session_scope() as session:
        rs.assign(session, ws, item, owner, member)
    with session_scope() as session, pytest.raises(ServiceError) as exc:
        rs.reject(session, ws, item, new_account(), note="not mine")
    assert exc.value.code == "REVIEW_ASSIGNEE_REQUIRED" and exc.value.http_status == 403
    with session_scope() as session:
        assert rs.reject(session, ws, item, member, note="my call").state == "REJECTED"


def test_assignee_must_be_a_workspace_member() -> None:
    owner = new_account()
    with session_scope() as session:
        ws = new_workspace(session)
        add_member(session, ws, owner, "owner")
    _, item = failed_item(ws)
    with session_scope() as session, pytest.raises(ServiceError) as exc:
        rs.assign(session, ws, item, owner, new_account())
    assert exc.value.code == "ASSIGNEE_NOT_MEMBER" and exc.value.http_status == 422


def test_needs_review_evaluations_enqueue_once() -> None:
    with session_scope() as session:
        ws = new_workspace(session)
        needs = make_evaluation(session, ws, Recommendation.NEEDS_REVIEW)
        accepted = make_evaluation(session, ws, Recommendation.ACCEPT)
    with session_scope() as session:
        first = rs.enqueue_needs_review(session, ws, needs).id
    with session_scope() as session:
        assert rs.enqueue_needs_review(session, ws, needs).id == first
    with session_scope() as session, pytest.raises(ServiceError) as exc:
        rs.enqueue_needs_review(session, ws, accepted)
    assert exc.value.code == "EVALUATION_NOT_NEEDS_REVIEW" and exc.value.http_status == 422
    with session_scope() as session:
        view = rs.get_item(session, ws, first).item
        assert view.source_kind == "EVALUATION" and view.field == "outcome" and view.state == "OPEN"


def test_another_workspace_cannot_see_or_decide_an_item() -> None:
    owner = new_account()
    with session_scope() as session:
        ws = new_workspace(session)
        other = new_workspace(session)
        add_member(session, ws, owner, "owner")
    _, item = failed_item(ws)
    with session_scope() as session, pytest.raises(ServiceError) as exc:
        rs.get_item(session, other, item)
    assert exc.value.code == "REVIEW_ITEM_UNKNOWN" and exc.value.http_status == 404
    with session_scope() as session, pytest.raises(ServiceError) as exc:
        rs.reject(session, other, item, owner, note="wrong workspace")
    assert exc.value.code == "REVIEW_ITEM_UNKNOWN"


def test_append_only_triggers_block_update_and_delete() -> None:
    with session_scope() as session:
        ws = new_workspace(session)
        eid = make_extraction(session, ws, checks_for({"qty": "span_not_found"}))
        session.flush()
    with session_scope() as session:
        rs.enqueue_from_extraction(session, ws, eid)
    with session_scope() as session, pytest.raises(DBAPIError):
        session.execute(text("UPDATE review_items SET field_name = 'x' WHERE workspace_id = :ws"), {"ws": ws})
    with session_scope() as session, pytest.raises(DBAPIError):
        session.execute(text("DELETE FROM review_items WHERE workspace_id = :ws"), {"ws": ws})
    with session_scope() as session:
        triggers = session.execute(
            text(
                "SELECT tgrelid::regclass::text FROM pg_trigger "
                "WHERE tgname IN ('review_items_no_update_delete', 'review_events_no_update_delete') "
                "AND NOT tgisinternal"
            )
        ).scalars().all()
    assert sorted(triggers) == ["review_events", "review_items"]


def test_events_are_ordered_by_sequence_not_by_time() -> None:
    owner = new_account()
    with session_scope() as session:
        ws = new_workspace(session)
        add_member(session, ws, owner, "owner")
    _, item = failed_item(ws)
    with session_scope() as session:
        rs.assign(session, ws, item, owner, owner)
        rs.assign(session, ws, item, owner, None)
    with session_scope() as session:
        kinds = [e.kind for e in rs.get_item(session, ws, item).events]
        seqs = session.execute(select(ReviewEvent.seq).where(ReviewEvent.item_id == item).order_by(ReviewEvent.seq)).scalars().all()
    assert kinds == ["ASSIGNED", "UNASSIGNED"] and list(seqs) == sorted(seqs)


# ---------------------------------------------------------------------------
# HTTP surface
# ---------------------------------------------------------------------------


def api_client() -> tuple[TestClient, str, str]:
    """A signed-in account, its personal workspace and a client. Returns (client, account, workspace)."""
    name = "review-api-" + uid()
    account = str(create_account(name, PASSWORD, "owner")["id"])
    token = sign_in(name, PASSWORD, name)["token"]
    client = TestClient(app, headers={"Authorization": "Bearer " + token})
    ws = str(client.get("/api/v1/workspaces").json()["items"][0]["id"])
    return client, account, ws


def test_unauthenticated_requests_are_401() -> None:
    _, _, ws = api_client()
    anonymous = TestClient(app)
    response = anonymous.get(ROUTE, params={"workspace_id": ws})
    assert response.status_code == 401
    assert anonymous.post(f"{ROUTE}/x/reject", params={"workspace_id": ws}, json={"note": "n"}).status_code == 401


def test_http_list_detail_and_decision_flow() -> None:
    client, account, ws = api_client()
    _, item = failed_item(ws)
    listed = client.get(ROUTE, params={"workspace_id": ws, "state": "OPEN"})
    assert listed.status_code == 200
    assert item in [row["id"] for row in listed.json()["items"]]
    detail = client.get(f"{ROUTE}/{item}", params={"workspace_id": ws})
    assert detail.status_code == 200 and detail.json()["item"]["claimed_value"] == "50"
    assigned = client.post(f"{ROUTE}/{item}/assign", params={"workspace_id": ws}, json={"assignee_id": account})
    assert assigned.status_code == 200 and assigned.json()["state"] == "ASSIGNED"
    rejected = client.post(f"{ROUTE}/{item}/reject", params={"workspace_id": ws}, json={"note": "not a defect"})
    assert rejected.status_code == 200 and rejected.json()["state"] == "REJECTED"
    again = client.post(f"{ROUTE}/{item}/confirm", params={"workspace_id": ws}, json={"note": "again"})
    assert again.status_code == 409 and again.json()["code"] == "REVIEW_ALREADY_DECIDED"


def test_http_confirm_without_a_note_is_422() -> None:
    client, account, ws = api_client()
    _, item = failed_item(ws)
    response = client.post(f"{ROUTE}/{item}/confirm", params={"workspace_id": ws}, json={"note": ""})
    assert response.status_code == 422 and response.json()["code"] == "NOTE_REQUIRED"


def test_http_correct_writes_a_human_fact() -> None:
    client, account, ws = api_client()
    _, item = failed_item(ws)
    body = {
        "note": "delivery note says 60",
        "value": "60",
        "fact": {"kind": "fabric_qc", "entity_key": "lot:L9", "payload": {"issue": "shade_fail", "qty": {"value": "60", "unit": "kg"}}},
    }
    response = client.post(f"{ROUTE}/{item}/correct", params={"workspace_id": ws}, json=body)
    assert response.status_code == 200, response.text
    view = response.json()
    assert view["state"] == "CORRECTED" and view["resulting_fact_id"] == "review-" + item
    assert view["claimed_value"] == "50"


def test_http_rejects_unknown_fact_fields_and_bad_states() -> None:
    client, _, ws = api_client()
    bad = client.post(
        f"{ROUTE}/anything/correct",
        params={"workspace_id": ws},
        json={"note": "x", "value": "1", "fact": {"kind": "fabric_qc", "entity_key": "lot:L9", "payload": {}, "origin": "notes"}},
    )
    assert bad.status_code == 422
    assert client.get(f"{ROUTE}/missing", params={"workspace_id": ws}).json()["code"] == "REVIEW_ITEM_UNKNOWN"


def test_http_cross_workspace_ids_are_404() -> None:
    client, account, ws = api_client()
    other_client, other_account, other_ws = api_client()
    _, foreign_item = failed_item(other_ws)
    response = client.get(f"{ROUTE}/{foreign_item}", params={"workspace_id": ws})
    assert response.status_code == 404
    assert client.post(f"{ROUTE}/{foreign_item}/reject", params={"workspace_id": ws}, json={"note": "n"}).status_code == 404
    assert other_client.get(f"{ROUTE}/{foreign_item}", params={"workspace_id": other_ws}).status_code == 200


def test_http_non_member_and_demo_workspace_are_refused() -> None:
    client, account, ws = api_client()
    _, outsider_account, outsider_ws = api_client()
    _, foreign_item = failed_item(outsider_ws)
    # A workspace the caller cannot see answers 404 for reads and writes alike.
    assert client.get(ROUTE, params={"workspace_id": outsider_ws}).status_code == 404
    assert client.post(f"{ROUTE}/{foreign_item}/reject", params={"workspace_id": outsider_ws}, json={"note": "n"}).status_code == 404
    # The demo workspace is readable but never writable.
    demo_write = client.post(f"{ROUTE}/{foreign_item}/assign", params={"workspace_id": DEMO}, json={"assignee_id": account})
    assert demo_write.status_code == 404 and demo_write.json()["code"] == "WORKSPACE_UNKNOWN"


def test_http_member_who_is_assignee_can_decide() -> None:
    client, account, ws = api_client()
    member_client, member, _ = api_client()
    with session_scope() as session:
        add_member(session, ws, member, "member")
    _, item = failed_item(ws)
    assert client.post(f"{ROUTE}/{item}/assign", params={"workspace_id": ws}, json={"assignee_id": member}).status_code == 200
    member_view = member_client.post(f"{ROUTE}/{item}/reject", params={"workspace_id": ws}, json={"note": "mine"})
    assert member_view.status_code == 200 and member_view.json()["state"] == "REJECTED"


# ---------------------------------------------------------------------------
# Assignment rules, entity binding, forks, value matching, input limits, sync
# ---------------------------------------------------------------------------


def seed_prior_qc(ws: str, fact_id: str, lot: str, qty: str) -> None:
    """A visible, earlier qc fact that a correction can supersede."""
    with session_scope() as session:
        service.append_facts(
            session,
            [
                Fact(
                    id=fact_id,
                    kind=FactKind.FABRIC_QC,
                    entity_key=f"lot:{lot}",
                    payload={
                        "issue": "shade_fail",
                        "qty": {"value": qty, "unit": "kg"},
                        "review_state": "checks_passed",
                        "origin": "notes",
                    },
                    valid_from=PAST,
                    valid_to=None,
                    known_at=PAST + timedelta(minutes=30),
                    supersedes_id=None,
                    source=SourceProfile.NOTES,
                    artifact_id=None,
                )
            ],
            workspace_id=ws,
            trusted_known_at=PAST + timedelta(minutes=30),
        )


def expect_code(code: str, status: int, call: Any) -> None:
    with pytest.raises(ServiceError) as exc:
        call()
    assert exc.value.code == code, exc.value.code
    assert exc.value.http_status == status


def test_members_may_only_take_unassigned_items_for_themselves() -> None:
    owner = new_account()
    member_a = new_account()
    member_b = new_account()
    with session_scope() as session:
        ws = new_workspace(session)
        add_member(session, ws, owner, "owner")
        add_member(session, ws, member_a, "member")
        add_member(session, ws, member_b, "member")
    _, item = failed_item(ws)
    with session_scope() as session:
        expect_code("REVIEW_ASSIGNMENT_FORBIDDEN", 403, lambda: rs.assign(session, ws, item, member_a, member_b))
    with session_scope() as session:
        assert rs.assign(session, ws, item, member_a, member_a).state == "ASSIGNED"
    with session_scope() as session:
        # Taken: another member cannot take it, reassign it, or clear it.
        expect_code("REVIEW_ASSIGNMENT_FORBIDDEN", 403, lambda: rs.assign(session, ws, item, member_b, member_b))
        expect_code("REVIEW_ASSIGNMENT_FORBIDDEN", 403, lambda: rs.assign(session, ws, item, member_b, member_a))
        expect_code("REVIEW_ASSIGNMENT_FORBIDDEN", 403, lambda: rs.assign(session, ws, item, member_b, None))
    with session_scope() as session:
        # The current assignee may clear their own item.
        assert rs.assign(session, ws, item, member_a, None).state == "OPEN"


def test_owner_may_reassign_and_clear_any_item() -> None:
    owner = new_account()
    member_a = new_account()
    with session_scope() as session:
        ws = new_workspace(session)
        add_member(session, ws, owner, "owner")
        add_member(session, ws, member_a, "member")
    _, item = failed_item(ws)
    with session_scope() as session:
        assert rs.assign(session, ws, item, owner, member_a).assignee_id == member_a
    with session_scope() as session:
        assert rs.assign(session, ws, item, owner, owner).assignee_id == owner
    with session_scope() as session:
        assert rs.assign(session, ws, item, owner, None).state == "OPEN"


def test_entity_binding_refuses_a_foreign_lot_and_a_foreign_order() -> None:
    owner = new_account()
    with session_scope() as session:
        ws = new_workspace(session)
        add_member(session, ws, owner, "owner")
    _, item = failed_item(ws)  # bound to lot:L9
    expect_code(
        "ENTITY_MISMATCH", 422,
        lambda: rs_correct_call(ws, item, owner, fact=qc_draft("L8", "60"), value="60"),
    )
    with session_scope() as session:
        evaluation = make_evaluation(session, ws, Recommendation.NEEDS_REVIEW)
    with session_scope() as session:
        eval_item = rs.enqueue_needs_review(session, ws, evaluation).id
    foreign_order = FactDraft(kind=FactKind.ORDER_REQUEST, entity_key="order:someone-else", payload={})
    expect_code(
        "ENTITY_MISMATCH", 422,
        lambda: rs_correct_call(ws, eval_item, owner, fact=foreign_order, value="x"),
    )


def rs_correct_call(ws: str, item: str, actor: str, *, fact: FactDraft, value: str) -> None:
    with session_scope() as session:
        rs.correct(session, ws, item, actor, note="correction", value=value, fact=fact)


def test_supersedes_must_name_a_fact_of_the_same_entity_and_kind() -> None:
    owner = new_account()
    prior_other_lot = "qc-" + uid()[:12]
    with session_scope() as session:
        ws = new_workspace(session)
        add_member(session, ws, owner, "owner")
    seed_prior_qc(ws, prior_other_lot, "L8", "50")
    _, item = failed_item(ws)  # bound to lot:L9
    expect_code(
        "SUPERSEDES_MISMATCH", 422,
        lambda: rs_correct_call(ws, item, owner, fact=qc_draft("L9", "60", supersedes_id=prior_other_lot), value="60"),
    )
    with session_scope() as session:
        assert rs.get_item(session, ws, item).item.state == "OPEN"  # nothing was decided


def test_a_prior_fact_has_one_live_successor_even_under_a_race() -> None:
    from concurrent.futures import ThreadPoolExecutor

    owner = new_account()
    prior = "qc-" + uid()[:12]
    with session_scope() as session:
        ws = new_workspace(session)
        add_member(session, ws, owner, "owner")
    seed_prior_qc(ws, prior, "L9", "50")
    items = [failed_item(ws)[1] for _ in range(4)]

    def attempt(item: str) -> str:
        try:
            rs_correct_call(ws, item, owner, fact=qc_draft("L9", "60", supersedes_id=prior), value="60")
            return "ok"
        except ServiceError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=4) as pool:
        outcomes = list(pool.map(attempt, items))
    assert outcomes.count("ok") == 1, outcomes
    assert outcomes.count("FACT_ALREADY_SUPERSEDED") == 3, outcomes
    with session_scope() as session:
        after = snapshot.events(service.snapshot_at(session, ws, datetime.now(UTC) + timedelta(minutes=5)), FactKind.FABRIC_QC, "lot:L9")
    assert len(after) == 1 and after[0].supersedes_id == prior


def test_second_correction_of_a_superseded_fact_is_refused() -> None:
    owner = new_account()
    prior = "qc-" + uid()[:12]
    with session_scope() as session:
        ws = new_workspace(session)
        add_member(session, ws, owner, "owner")
    seed_prior_qc(ws, prior, "L9", "50")
    _, first = failed_item(ws)
    _, second = failed_item(ws)
    rs_correct_call(ws, first, owner, fact=qc_draft("L9", "60", supersedes_id=prior), value="60")
    expect_code(
        "FACT_ALREADY_SUPERSEDED", 409,
        lambda: rs_correct_call(ws, second, owner, fact=qc_draft("L9", "70", supersedes_id=prior), value="70"),
    )


def test_attested_value_must_match_the_fact() -> None:
    owner = new_account()
    with session_scope() as session:
        ws = new_workspace(session)
        add_member(session, ws, owner, "owner")
    _, item = failed_item(ws)
    for bad in ("999", "not a number", "NaN"):
        expect_code(
            "VALUE_FACT_MISMATCH", 422,
            lambda bad=bad: rs_correct_call(ws, item, owner, fact=qc_draft("L9", "60"), value=bad),
        )
        with session_scope() as session, pytest.raises(ServiceError) as exc:
            rs.confirm(session, ws, item, owner, note="attest", value=bad, fact=qc_draft("L9", "60"))
        assert exc.value.code == "VALUE_FACT_MISMATCH"
    with session_scope() as session:
        assert rs.get_item(session, ws, item).item.state == "OPEN"
    with session_scope() as session:
        assert rs.correct(session, ws, item, owner, note="ok", value="60.000", fact=qc_draft("L9", "60")).state == "CORRECTED"


def test_nul_and_oversize_text_is_refused_before_any_write() -> None:
    owner = new_account()
    with session_scope() as session:
        ws = new_workspace(session)
        add_member(session, ws, owner, "owner")
    _, item = failed_item(ws)
    with session_scope() as session:
        events_before = session.scalar(select(func.count()).select_from(ReviewEvent).where(ReviewEvent.workspace_id == ws))
    with session_scope() as session:
        expect_code("NUL_NOT_ALLOWED", 422, lambda: rs.reject(session, ws, item, owner, note="bad\x00note"))
    with session_scope() as session:
        expect_code("TEXT_TOO_LONG", 422, lambda: rs.reject(session, ws, item, owner, note="n" * 2001))
    with session_scope() as session:
        expect_code("NUL_NOT_ALLOWED", 422, lambda: rs.correct(session, ws, item, owner, note="ok", value="6\x000", fact=qc_draft("L9", "60")))
    with session_scope() as session:
        expect_code("TEXT_TOO_LONG", 422, lambda: rs.correct(session, ws, item, owner, note="ok", value="6" * 501, fact=qc_draft("L9", "60")))
    with session_scope() as session:
        events_after = session.scalar(select(func.count()).select_from(ReviewEvent).where(ReviewEvent.workspace_id == ws))
    assert events_after == events_before
    with session_scope() as session:
        assert rs.reject(session, ws, item, owner, note="n" * 2000).state == "REJECTED"


def test_http_text_limits_and_nul_are_422_not_503() -> None:
    client, account, ws = api_client()
    _, item = failed_item(ws)
    url = f"{ROUTE}/{item}/reject"
    nul = client.post(url, params={"workspace_id": ws}, json={"note": "bad\u0000note"})
    assert nul.status_code == 422 and nul.json()["code"] == "NUL_NOT_ALLOWED"
    long = client.post(url, params={"workspace_id": ws}, json={"note": "n" * 2001})
    assert long.status_code == 422 and long.json()["code"] == "TEXT_TOO_LONG"
    body = {"note": "ok", "value": "6\u0000", "fact": {"kind": "fabric_qc", "entity_key": "lot:L9", "payload": {"issue": "shade_fail", "qty": {"value": "60", "unit": "kg"}}}}
    corrected = client.post(f"{ROUTE}/{item}/correct", params={"workspace_id": ws}, json=body)
    assert corrected.status_code == 422 and corrected.json()["code"] == "NUL_NOT_ALLOWED"
    assert client.get(f"{ROUTE}/{item}", params={"workspace_id": ws}).json()["item"]["state"] == "OPEN"


def test_sync_creates_missing_items_once_and_get_has_no_side_effects() -> None:
    client, account, ws = api_client()
    with session_scope() as session:
        make_extraction(session, ws, checks_for({"qty": "span_not_found"}))
        make_extraction(session, ws, checks_for({}))  # clean: adds nothing
        make_evaluation(session, ws, Recommendation.NEEDS_REVIEW)
        make_evaluation(session, ws, Recommendation.ACCEPT)  # not a review case
    assert client.get(ROUTE, params={"workspace_id": ws}).json()["items"] == []  # GET creates nothing
    first = client.post(f"{ROUTE}/sync", params={"workspace_id": ws})
    assert first.status_code == 200 and first.json() == {"extraction_items_created": 1, "evaluation_items_created": 1}
    second = client.post(f"{ROUTE}/sync", params={"workspace_id": ws})
    assert second.json() == {"extraction_items_created": 0, "evaluation_items_created": 0}
    assert len(client.get(ROUTE, params={"workspace_id": ws}).json()["items"]) == 2


def test_sync_refuses_non_members_and_demo() -> None:
    client, _, ws = api_client()
    _, _, outsider_ws = api_client()
    assert client.post(f"{ROUTE}/sync", params={"workspace_id": outsider_ws}).status_code == 404
    demo = client.post(f"{ROUTE}/sync", params={"workspace_id": DEMO})
    assert demo.status_code == 404 and demo.json()["code"] == "WORKSPACE_UNKNOWN"
    assert TestClient(app).post(f"{ROUTE}/sync", params={"workspace_id": ws}).status_code == 401
