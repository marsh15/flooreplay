"""Historical analyses keep their identity across source corrections and workflow changes."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from flooreplay.auth import Account, create_account
from flooreplay.db import engine
from flooreplay.domain.hashing import incident_digest
from flooreplay.incident_engine import incident_evidence_card
from flooreplay.incident_fixtures import incident_fixtures
from flooreplay.incident_import import preview_incident_import
from flooreplay.incident_service import (
    analysis_evidence,
    analysis_view,
    create_analysis,
    incident_detail,
    publish_source,
    review_proposal,
)
from flooreplay.incident_workflow import (
    IncidentCheck,
    complete_check,
    create_check,
    resolve_incident,
    respond_check,
    workflow_view,
)
from flooreplay.models import IncidentRevision
from flooreplay.service import ServiceError

pytestmark = pytest.mark.skipif(
    os.environ.get("FLOORREPLAY_SKIP_DB") == "1", reason="database not available"
)

FIXTURE = next(item for item in incident_fixtures() if item["id"] == "INC-001" and item["revision"] == 2)
PASSWORD = "test-password-long-enough"


def _seed(session: Session, *, cutoff: str | None = None) -> str:
    """Store the synthetic INC-001 fixture as revision 1 of a fresh incident."""
    incident_id = f"TEMPORAL-{uuid4().hex}"
    payload = deepcopy(FIXTURE)
    payload.update(id=incident_id, revision=1, cutoff=cutoff or payload["cutoff"])
    session.add(
        IncidentRevision(
            workspace_id="public-demo", incident_id=incident_id, revision=1, title=payload["title"],
            line_id=payload["scope"]["line_id"], cutoff=datetime.fromisoformat(payload["cutoff"]),
            window_start=datetime.fromisoformat(payload["window"]["start"]),
            window_end=datetime.fromisoformat(payload["window"]["end"]), payload=payload,
            content_digest=incident_digest(payload), evidence_card=incident_evidence_card(payload),
        )
    )
    session.flush()
    return incident_id


def _record(incident_id: str, session: Session, revision: int, record_id: str) -> dict:
    payload = session.get(IncidentRevision, (incident_id, revision)).payload
    return next(row for section in ("output_buckets", "plan_buckets", "events") for row in payload.get(section, []) if row["id"] == record_id)


def _correct_output(session: Session, incident_id: str, base_revision: int, target: dict, *, correction_id: str, quantity: int, available_at: str, cutoff: str):
    scope = FIXTURE["scope"]
    row = {
        "id": correction_id, "supersedes_id": target["id"], "record_type": "final_good_delta",
        "available_at": available_at, "factory": scope["factory"], "line_id": scope["line_id"],
        "order_id": scope["order_id"], "style_id": scope["style_id"], "stage": scope["stage"],
        "unit": "good_units", "start": target["start"], "end": target["end"], "quantity": quantity,
    }
    raw = json.dumps([row])
    preview = preview_incident_import(raw.encode(), profile="production-v1", source_system="ledger", timezone="UTC", filename="correction.json", unit="good_units", scope=scope)
    return publish_source(
        session, incident_id=incident_id, base_revision=base_revision, cutoff=cutoff, raw_text=raw,
        profile="production-v1", source_system="ledger", timezone="UTC", filename="correction.json",
        unit="good_units", idempotency_key=uuid4().hex, preview_digest=preview["preview_digest"],
    )


def _pinned(session: Session, analysis) -> dict:
    """The historical report and its identity, without the mutable stale flag."""
    return {key: value for key, value in analysis_view(session, analysis).items() if key != "stale"}


def _corpus_item(analysis, incident_id: str) -> dict:
    return next(item for item in analysis.report["corpus_release"]["items"] if item["id"] == incident_id)


def _account(session: Session, role: str) -> Account:
    created = create_account(f"temporal-{uuid4().hex[:12]}", PASSWORD, role)
    return session.get(Account, created["id"])


def test_pinned_report_survives_a_source_correction():
    with Session(engine) as session:
        incident_id = _seed(session)
        analysis = create_analysis(session, incident_id, 1, uuid4().hex)
        pinned = _pinned(session, analysis)
        digest_before = incident_detail(session, incident_id, 1)["content_digest"]
        target = _record(incident_id, session, 1, "out-7")

        published = _correct_output(
            session, incident_id, 1, target, correction_id="fix-out-7", quantity=target["quantity"] + 1,
            available_at="2026-09-28T11:45:00+05:30", cutoff="2026-09-28T12:00:00+05:30",
        )
        assert published["revision"] == 2

        assert _pinned(session, analysis) == pinned
        assert analysis_view(session, analysis)["stale"] is True
        assert incident_detail(session, incident_id, 1)["content_digest"] == digest_before
        assert analysis_evidence(session, analysis, "out-7")["record"]["quantity"] == target["quantity"]
        with pytest.raises(ServiceError) as unknown:
            analysis_evidence(session, analysis, "fix-out-7")
        assert unknown.value.code == "EVIDENCE_UNKNOWN"
        with pytest.raises(ServiceError) as stale:
            review_proposal(session, analysis, "verify-machine", "PENDING_REVIEW", "Production lead", "Reviewed", uuid4().hex)
        assert stale.value.code == "STALE_ANALYSIS"

        current = create_analysis(session, incident_id, 2, uuid4().hex)
        assert analysis_evidence(session, current, "fix-out-7")["record"]["quantity"] == target["quantity"] + 1
        assert analysis_evidence(session, current, "out-7")["record"]["quantity"] == target["quantity"]
        assert "fix-out-7" in {row["id"] for row in current.report["correction_history"]}
        assert "fix-out-7" not in {row["id"] for row in analysis.report["correction_history"]}


def test_precedent_corpus_identity_survives_a_later_correction_of_the_precedent():
    with Session(engine) as session:
        precedent_id = _seed(session)
        query_id = _seed(session, cutoff="2026-09-28T12:30:00+05:30")
        pinned = create_analysis(session, query_id, 1, uuid4().hex)
        before = _pinned(session, pinned)
        precedent_before = _corpus_item(pinned, precedent_id)
        assert precedent_before["revision"] == 1
        target = _record(precedent_id, session, 1, "out-7")

        _correct_output(
            session, precedent_id, 1, target, correction_id="fix-precedent-out-7", quantity=target["quantity"] + 1,
            available_at="2026-09-28T11:35:00+05:30", cutoff="2026-09-28T11:40:00+05:30",
        )

        assert _pinned(session, pinned) == before
        assert _corpus_item(pinned, precedent_id) == precedent_before
        refreshed = create_analysis(session, query_id, 1, uuid4().hex)
        assert _corpus_item(refreshed, precedent_id)["revision"] == 2
        assert _corpus_item(refreshed, precedent_id)["digest"] != precedent_before["digest"]


def test_workflow_responses_and_resolution_do_not_rewrite_the_pinned_report():
    with Session(engine) as session:
        owner, assignee = _account(session, "owner"), _account(session, "reviewer")
        incident_id = _seed(session)
        analysis = create_analysis(session, incident_id, 1, uuid4().hex)
        pinned = _pinned(session, analysis)
        digest_rev1 = incident_detail(session, incident_id, 1)["content_digest"]
        now = datetime.now(UTC)
        task = create_check(session, analysis.id, owner, {
            "proposal_id": "verify-machine", "assignee_id": assignee.id,
            "due_at": (now + timedelta(days=1)).isoformat(), "idempotency_key": uuid4().hex,
        })

        respond_check(session, task["id"], assignee, {
            "base_revision": 1,
            "summary": "Maintenance confirms a station repair; the effect on good output remains unknown.",
            "occurred_at": FIXTURE["window"]["start"], "source_ref": "Maintenance ticket MT-123",
            "details": {field: "Recorded observation; further verification remains open" for field in task["requested_fields"]},
            "line_blocking": False, "start": None, "end": None, "idempotency_key": uuid4().hex,
        })
        complete_check(session, task["id"], assignee, {
            "action_taken": "Reviewed the source response and confirmed the repair handoff.",
            "actual_completed_at": datetime.now(UTC).isoformat(), "observed_good_units": None, "observed_at": None,
            "assessment": "Check answered; causal production improvement has not been measured.",
            "remaining_uncertainty": "No post-action comparable production interval available.",
            "idempotency_key": uuid4().hex,
        })
        resolve_incident(session, incident_id, owner, {
            "base_revision": 2, "state": "RESOLVED", "rationale": "Source check complete, known limitations retained",
            "idempotency_key": uuid4().hex,
        })

        assert _pinned(session, analysis) == pinned
        assert incident_detail(session, incident_id, 1)["content_digest"] == digest_rev1
        with pytest.raises(ServiceError) as unknown:
            analysis_evidence(session, analysis, f"check-{task['id']}")
        assert unknown.value.code == "EVIDENCE_UNKNOWN"
        stored = session.get(IncidentCheck, task["id"])
        assert (stored.analysis_id, stored.revision, stored.response["revision"]) == (analysis.id, 1, 2)
        resolved = workflow_view(session, incident_id)
        assert (resolved["resolution"], resolved["resolved_revision"], resolved["current_revision"]) == ("RESOLVED", 2, 2)
        digest_rev2 = incident_detail(session, incident_id, 2)["content_digest"]

        target = _record(incident_id, session, 2, "out-7")
        _correct_output(
            session, incident_id, 2, target, correction_id="fix-after-resolution", quantity=target["quantity"] + 1,
            available_at=now.isoformat(), cutoff=(now + timedelta(minutes=1)).isoformat(),
        )

        reopened = workflow_view(session, incident_id)
        assert (reopened["current_revision"], reopened["resolution"], reopened["resolved_revision"]) == (3, "OPEN", 2)
        assert _pinned(session, analysis) == pinned
        assert incident_detail(session, incident_id, 2)["content_digest"] == digest_rev2


def test_a_proposal_cannot_be_queued_for_review_twice():
    with Session(engine) as session:
        incident_id = _seed(session)
        analysis = create_analysis(session, incident_id, 1, uuid4().hex)
        key = uuid4().hex
        pending = review_proposal(session, analysis, "verify-machine", "PENDING_REVIEW", "Production lead", "Checked the cited records", key)
        assert review_proposal(session, analysis, "verify-machine", "PENDING_REVIEW", "Production lead", "Checked the cited records", key).id == pending.id
        with pytest.raises(ServiceError) as duplicate:
            review_proposal(session, analysis, "verify-machine", "PENDING_REVIEW", "Production lead", "Checked the cited records", uuid4().hex)
        assert duplicate.value.code == "ALREADY_PENDING"
        approved = review_proposal(session, analysis, "verify-machine", "APPROVED", "Production lead", "Checked the cited records", uuid4().hex)
        assert approved.state == "APPROVED"


def test_analysis_and_review_response_survive_database_reload():
    with Session(engine) as session:
        session.execute(text("SET LOCAL TIME ZONE 'Asia/Kolkata'"))
        incident_id = _seed(session)
        analysis = create_analysis(session, incident_id, 1, uuid4().hex)
        review_proposal(session, analysis, "verify-machine", "PENDING_REVIEW", "Production lead", "Checked the cited records", uuid4().hex)
        before = analysis_view(session, analysis)
        session.expire_all()
        assert analysis_view(session, analysis) == before
        assert before["created_at"].endswith("+00:00")
