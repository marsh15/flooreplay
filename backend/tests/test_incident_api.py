"""The hero investigation remains revision-bound across API reads and review."""

from __future__ import annotations

import json
import os
import uuid
from copy import deepcopy
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from flooreplay.api import app, create_app
from flooreplay.db import session_scope
from flooreplay.domain.hashing import digest
from flooreplay.incident_fixtures import incident_fixtures
from flooreplay.models import IncidentRevision, IncidentSourceArtifact
from flooreplay.seeding import run_seed

pytestmark = pytest.mark.skipif(os.environ.get("FLOORREPLAY_SKIP_DB") == "1", reason="database not available")


def test_hero_cutoff_revision_and_review_conflict(owner_headers) -> None:
    run_seed()
    client = TestClient(app, headers=owner_headers)
    key = f"incident-api-{uuid.uuid4().hex}"
    first = client.post("/api/v1/incidents/INC-001/analyses", json={"revision": 1, "idempotency_key": key})
    assert first.status_code == 200
    assert client.post("/api/v1/incidents/INC-001/analyses", json={"revision": 1, "idempotency_key": key}).json()["id"] == first.json()["id"]
    assert client.post("/api/v1/incidents/INC-001/analyses", json={"revision": 2, "idempotency_key": key}).status_code == 409
    old = first.json()
    assert old["metrics"]["shortfall"] == 73
    assert old["metrics"]["formula"] == "variance = observed - planned; shortfall = max(0, planned - observed)"
    assert len(old["metrics"]["inputs"]) == 8
    assert client.get(f"/api/v1/analyses/{old['id']}/evidence/plan-0").status_code == 200
    assert client.get(f"/api/v1/analyses/{old['id']}/evidence/out-0").status_code == 200
    assert "EV-MAINT-1" not in {event["id"] for event in old["timeline"]}
    assert old["stale"] is True
    proposal_id = old["proposals"][0]["id"]
    stale = client.post(
        f"/api/v1/analyses/{old['id']}/proposals/{proposal_id}/submit",
        json={"actor": "Production lead", "rationale": "Reviewed the evidence", "decision": "PENDING_REVIEW", "idempotency_key": f"review-{uuid.uuid4().hex}"},
    )
    assert stale.status_code == 409 and stale.json()["code"] == "STALE_ANALYSIS"
    later = client.post("/api/v1/incidents/INC-001/analyses", json={"revision": 2, "idempotency_key": f"later-{uuid.uuid4().hex}"}).json()
    assert "EV-MAINT-1" in {event["id"] for event in later["timeline"]}
    assert client.get(f"/api/v1/analyses/{old['id']}").json()["metrics"]["shortfall"] == 73
    assert client.get(f"/api/v1/analyses/{old['id']}/evidence/EV-MAINT-1").status_code == 404


def test_saved_local_draft_and_honest_evaluation() -> None:
    client = TestClient(app)
    saved = client.get("/api/v1/incidents/INC-001/saved-draft")
    assert saved.status_code == 200
    assert saved.json()["execution_kind"] == "saved_local_ai"
    assert sum(claim["review_status"] == "SUPPORTED" for claim in saved.json()["claims"]) == 1
    evaluation = client.get("/api/v1/evaluation-reports/incident-core-v1")
    assert evaluation.status_code == 200
    assert evaluation.json()["metrics"]["local_draft_validity"] == {"passed": 4, "total": 10}
    assert evaluation.json()["metrics"]["ai_evidence_precision"] == {"passed": 8, "total": 16}
    assert len(evaluation.json()["model_evaluation"]["failed_cases"]) == 6
    comparison = evaluation.json()["baseline_comparison"]
    assert comparison["baseline"]["recall_at_5"] == {"passed": 3, "total": 6}
    assert comparison["candidate"]["recall_at_5"] == {"passed": 6, "total": 6}
    assert comparison["label_revision"] == "retrieval-observable-v1"


def test_public_incident_mode_is_read_only_except_bounded_analysis() -> None:
    client = TestClient(create_app(mode="public"))
    assert client.get("/api/v1/incidents").status_code == 200
    assert client.get("/api/v1/incidents/INC-001/saved-draft").status_code == 200
    assert client.post("/api/v1/incidents/imports/preview", json={}).status_code == 401
    assert client.post("/api/v1/analyses/none/ai-runs", json={}).status_code == 401
    assert client.post("/api/v1/analyses/none/proposals/none/review", json={}).status_code == 401
    assert client.get("/api/v1/capabilities").json()["live_parser_available"] is False


def test_final_proposal_review_cannot_be_reversed(owner_headers) -> None:
    client = TestClient(app, headers=owner_headers)
    report = client.post("/api/v1/incidents/INC-001/analyses", json={"revision": 2, "idempotency_key": f"review-final-{uuid.uuid4().hex}"}).json()
    proposal_id = report["proposals"][0]["id"]
    url = f"/api/v1/analyses/{report['id']}/proposals/{proposal_id}"
    body = {"actor": "Production lead", "rationale": "Checked the cited records", "idempotency_key": f"submit-{uuid.uuid4().hex}", "decision": "PENDING_REVIEW"}
    assert client.post(url + "/submit", json=body).status_code == 200
    body = {**body, "idempotency_key": f"approve-{uuid.uuid4().hex}", "decision": "APPROVED"}
    assert client.post(url + "/review", json=body).status_code == 200
    body = {**body, "idempotency_key": f"reject-{uuid.uuid4().hex}", "decision": "REJECTED"}
    rejected = client.post(url + "/review", json=body)
    assert rejected.status_code == 409 and rejected.json()["code"] == "ALREADY_REVIEWED"


def test_lexical_search_uses_as_known_visible_card() -> None:
    from flooreplay.db import session_scope
    from flooreplay.incident_service import search_incidents

    run_seed()
    with session_scope() as session:
        cutoff = datetime.fromisoformat("2026-09-28T11:15:00+05:30")
        assert "INC-001" not in {row["id"] for row in search_incidents(session, "technician", cutoff=cutoff)}
        later = datetime.fromisoformat("2026-09-29T09:00:00+05:30")
        assert "INC-001" in {row["id"] for row in search_incidents(session, "technician", cutoff=later)}
        assert "line-wide" not in session.get(IncidentRevision, ("INC-001", 2)).evidence_card


def test_recorded_model_packets_remain_historical() -> None:
    recorded = json.loads((Path(__file__).resolve().parents[1] / "evaluation" / "local-model-2026-09-28.json").read_text())
    assert recorded["model"].startswith("qwen")
    assert recorded["cases_attempted"] == 10
    # The archived v1 packets stay attached to that recorded run.
    assert all(case["packet"]["incident_id"] == case["id"].split("@")[0] for case in recorded["cases"])


def test_import_preview_and_immutable_publication(owner_headers) -> None:
    incident_id = f"INC-TEST-{uuid.uuid4().hex[:12]}"
    fixture = deepcopy(next(item for item in incident_fixtures() if item["id"] == "INC-110"))
    fixture["id"] = incident_id
    with session_scope() as session:
        session.add(IncidentRevision(
            incident_id=incident_id, revision=1, title=fixture["title"],
            line_id=fixture["scope"]["line_id"], cutoff=datetime.fromisoformat(fixture["cutoff"]),
            window_start=datetime.fromisoformat(fixture["window"]["start"]),
            window_end=datetime.fromisoformat(fixture["window"]["end"]),
            payload=fixture, content_digest=digest(fixture),
        ))
    client = TestClient(app, headers=owner_headers)
    row = {
        "id": "corrected-0", "record_type": "final_good_delta", "available_at": "2026-09-19T12:20:00+05:30",
        "start": "2026-09-19T09:00:00+05:30", "end": "2026-09-19T09:15:00+05:30", "quantity": 10,
        "unit": "good_units", "factory": "Synthetic Factory A", "line_id": "S8", "order_id": "ORD-19",
        "style_id": "ST-42", "stage": "sewing", "supersedes_id": "out-0",
    }
    raw = json.dumps([row])
    request = {"incident_id": incident_id, "base_revision": 1, "cutoff": "2026-09-19T12:30:00+05:30", "raw_text": raw, "profile": "production-v1", "source_system": "output-ledger", "timezone": "Asia/Kolkata", "filename": "correction.json", "unit": "good_units", "scope": fixture["scope"]}
    try:
        wrong = {**row, "line_id": "S9", "id": "wrong-line"}
        wrong_request = {**request, "raw_text": json.dumps([wrong])}
        wrong_preview = client.post("/api/v1/incidents/imports/preview", json=wrong_request).json()
        assert client.post("/api/v1/incidents/imports/publish", json={**wrong_request, "preview_digest": wrong_preview["preview_digest"], "idempotency_key": f"wrong-{uuid.uuid4().hex}"}).status_code == 422
        preview = client.post("/api/v1/incidents/imports/preview", json=request)
        assert preview.status_code == 200 and preview.json()["status"] == "READY"
        publication = {**request, "preview_digest": preview.json()["preview_digest"], "idempotency_key": f"import-{uuid.uuid4().hex}"}
        published = client.post("/api/v1/incidents/imports/publish", json=publication)
        assert published.status_code == 200
        assert published.json()["revision"] == 2
        assert client.post("/api/v1/incidents/imports/publish", json=publication).json()["revision"] == 2
        assert client.post("/api/v1/incidents/imports/publish", json={**publication, "raw_text": raw + " "}).status_code == 409
        report = client.post(f"/api/v1/incidents/{incident_id}/analyses", json={"revision": 2, "idempotency_key": f"analysis-{uuid.uuid4().hex}"})
        assert report.status_code == 200 and report.json()["metrics"]["shortfall"] == 10
        assert client.get(f"/api/v1/incidents/{incident_id}/revisions/1").json()["output_buckets"][0]["quantity"] == 20
    finally:
        from sqlalchemy import delete

        from flooreplay.models import IncidentAnalysis
        with session_scope() as session:
            session.execute(delete(IncidentAnalysis).where(IncidentAnalysis.incident_id == incident_id))
            session.execute(delete(IncidentSourceArtifact).where(IncidentSourceArtifact.incident_id == incident_id))
            session.execute(delete(IncidentRevision).where(IncidentRevision.incident_id == incident_id))


def test_new_incident_from_previewed_production_source(owner_headers) -> None:
    incident_id = f"INC-NEW-{uuid.uuid4().hex[:12]}"
    scope = {"factory": "Synthetic Factory A", "line_id": "S9", "order_id": "NEW-1", "style_id": "ST-9", "stage": "sewing", "unit": "good_units"}
    rows = [
        {"id": "plan-new", "record_type": "baseline_plan", "available_at": "2026-09-20T08:00:00+05:30", "start": "2026-09-20T09:00:00+05:30", "end": "2026-09-20T09:15:00+05:30", "quantity": 20, **scope},
        {"id": "out-new", "record_type": "final_good_delta", "available_at": "2026-09-20T09:15:00+05:30", "start": "2026-09-20T09:00:00+05:30", "end": "2026-09-20T09:15:00+05:30", "quantity": 10, **scope},
    ]
    client = TestClient(app, headers=owner_headers)
    raw = json.dumps(rows)
    preview_body = {"incident_id": incident_id, "base_revision": 1, "cutoff": "2026-09-20T09:15:00+05:30", "raw_text": raw, "profile": "production-v1", "source_system": "test-ledger", "timezone": "Asia/Kolkata", "filename": "new.json", "unit": "good_units", "scope": scope}
    preview = client.post("/api/v1/incidents/imports/preview", json=preview_body)
    assert preview.status_code == 200 and preview.json()["status"] == "READY"
    create_body = {"incident_id": incident_id, "title": "Test line start", "scope": scope, "window": {"start": "2026-09-20T09:00:00+05:30", "end": "2026-09-20T09:15:00+05:30"}, "cutoff": preview_body["cutoff"], "raw_text": raw, "source_system": "test-ledger", "timezone": "Asia/Kolkata", "filename": "new.json", "preview_digest": preview.json()["preview_digest"], "idempotency_key": f"new-{uuid.uuid4().hex}"}
    try:
        created = client.post("/api/v1/incidents", json=create_body)
        assert created.status_code == 200
        assert client.post("/api/v1/incidents", json=create_body).json()["revision"] == 1
        analysis = client.post(f"/api/v1/incidents/{incident_id}/analyses", json={"revision": 1, "idempotency_key": f"analysis-{uuid.uuid4().hex}"})
        assert analysis.status_code == 200 and analysis.json()["metrics"]["shortfall"] == 10
    finally:
        from sqlalchemy import delete

        from flooreplay.models import IncidentAnalysis
        with session_scope() as session:
            session.execute(delete(IncidentAnalysis).where(IncidentAnalysis.incident_id == incident_id))
            session.execute(delete(IncidentSourceArtifact).where(IncidentSourceArtifact.incident_id == incident_id))
            session.execute(delete(IncidentRevision).where(IncidentRevision.incident_id == incident_id))
