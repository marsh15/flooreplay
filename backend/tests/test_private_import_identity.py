"""Private external identifiers and retry keys cannot probe another factory."""
import json
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.orm import Session

from flooreplay.db import engine
from flooreplay.incident_import import preview_incident_import
from flooreplay.incident_service import (
    create_analysis,
    create_incident_from_source,
    publish_source,
    review_proposal,
)
from flooreplay.models import IncidentRevision, IncidentSourceArtifact
from flooreplay.workspaces import Workspace


def test_same_external_identity_and_import_keys_are_isolated_and_retryable():
    scope = dict(factory="F", line_id="L", order_id="O", style_id="S", stage="sewing", unit="good_units")
    window = dict(start="2026-09-01T09:00:00+00:00", end="2026-09-01T09:15:00+00:00")
    plan = {**scope, **window, "id": "p", "record_type": "baseline_plan", "quantity": 20, "available_at": "2026-09-01T08:00:00+00:00"}
    raw = json.dumps([plan])
    preview = preview_incident_import(raw.encode(), profile="production-v1", source_system="ledger", timezone="UTC", filename="data.json", unit="good_units", scope=scope)
    external_id = "SHIFT-" + uuid4().hex
    key = uuid4().hex
    owners = ["isolated-" + uuid4().hex for _ in range(2)]
    with Session(engine) as session:
        session.add_all([Workspace(id=owner, name="Private test", visibility="private") for owner in owners])
        session.flush()
        ids = []
        for owner in owners:
            kwargs = dict(incident_id=external_id, title="Private", scope=scope, window=window, cutoff=window["end"], raw_text=raw, source_system="ledger", timezone="UTC", filename="data.json", preview_digest=preview["preview_digest"], idempotency_key=key, workspace_id=owner)
            created = create_incident_from_source(session, **kwargs)
            assert create_incident_from_source(session, **kwargs) == created
            assert created["external_id"] == external_id
            assert len(created["id"]) <= 64
            ids.append(created["id"])
            output = json.dumps([{**plan, "id": "o", "record_type": "final_good_delta", "quantity": 10, "available_at": "2026-09-01T09:20:00+00:00"}])
            confirmed = preview_incident_import(output.encode(), profile="production-v1", source_system="ledger", timezone="UTC", filename="output.json", unit="good_units", scope=scope)
            publication = dict(incident_id=created["id"], base_revision=1, cutoff="2026-09-01T09:25:00+00:00", raw_text=output, profile="production-v1", source_system="ledger", timezone="UTC", filename="output.json", unit="good_units", preview_digest=confirmed["preview_digest"], idempotency_key=key + "-publish", workspace_id=owner)
            revised = publish_source(session, **publication)
            assert publish_source(session, **publication) == revised
            assert session.get(IncidentRevision, (created["id"], 2)).workspace_id == owner
            analysis = create_analysis(session, created["id"], 2, key + "-analysis")
            assert create_analysis(session, created["id"], 2, key + "-analysis").id == analysis.id
            assert analysis.workspace_id == owner
            # A reviewable proposal is pinned to this exact output for this test.
            analysis.report = {**analysis.report, "proposals": [{"id": "proposal", "description": "Check evidence"}]}
            review = review_proposal(session, analysis, "proposal", "PENDING_REVIEW", "Reviewer", "Investigate", key + "-review")
            assert review_proposal(session, analysis, "proposal", "PENDING_REVIEW", "Reviewer", "Investigate", key + "-review").id == review.id
            assert review.workspace_id == owner
        assert ids[0] != ids[1]
        artifacts = session.query(IncidentSourceArtifact).filter(IncidentSourceArtifact.incident_id.in_(ids)).all()
        assert len({artifact.idempotency_key for artifact in artifacts}) == 4
        assert {artifact.workspace_id for artifact in artifacts} == set(owners)


def test_private_archive_import_and_forks_do_not_collide_across_owners():
    from fastapi.testclient import TestClient

    from flooreplay.api import app
    from flooreplay.auth import create_account, sign_in

    clients = []
    for _ in range(2):
        name = "archive-owner-" + uuid4().hex
        create_account(name, "private-archive-password", "owner")
        token = sign_in(name, "private-archive-password", name)["token"]
        clients.append(TestClient(app, headers={"Authorization": "Bearer " + token}))
    body = {"profile_id": "skills-v1", "csv_text": "operator_id,operation_id,level,assessed_at\nO219,OP-SLM,3,2026-09-21T15:00:00+05:30\n", "declared_evidence_at": "2026-09-22T07:55:00+05:30", "coverage_complete": True}
    snapshot_ids = []
    fork_ids = []
    for client in clients:
        preview = client.post("/api/v1/imports/preview", json=body)
        assert preview.status_code == 200, preview.text
        publication = {**body, "preview_digest": preview.json()["preview_digest"]}
        published = client.post("/api/v1/imports/publish", json=publication)
        assert published.status_code == 200, published.text
        snapshot_id = published.json()["snapshot_id"]
        assert client.post("/api/v1/imports/publish", json=publication).json()["snapshot_id"] == snapshot_id
        snapshot_ids.append(snapshot_id)
        fork = client.post("/api/v1/scenarios/SCEN-HERO/revisions/1/fork", json={"snapshot_id": snapshot_id})
        assert fork.status_code == 200, fork.text
        fork_ids.append(fork.json()["scenario_id"])
        assert "origin:SCEN-HERO@1" in fork.json()["tags"]
    assert snapshot_ids[0] != snapshot_ids[1]
    assert fork_ids[0] != fork_ids[1]
    for index, client in enumerate(clients):
        assert client.get(f"/api/v1/scenarios/{fork_ids[1-index]}/revisions/2").status_code == 404


def test_public_http_retry_key_cannot_collide_with_hidden_legacy_analysis():
    from fastapi.testclient import TestClient

    from flooreplay.api import app
    from flooreplay.models import IncidentAnalysis

    hidden_workspace = "hidden-" + uuid4().hex
    guessed_key = "old-private-key-" + uuid4().hex
    with Session(engine) as session:
        session.add(Workspace(id=hidden_workspace, name="Hidden", visibility="private"))
        session.flush()
        hidden = IncidentAnalysis(workspace_id=hidden_workspace, idempotency_key=guessed_key, incident_id="INC-001", revision=2, manifest_digest="hidden-digest", report={"secret": "factory data"}, completed_at=datetime.now(UTC))
        session.add(hidden)
        session.commit()
        hidden_id = hidden.id
    request = {"revision": 2, "idempotency_key": guessed_key}
    client = TestClient(app)
    result = client.post("/api/v1/incidents/INC-001/analyses", json=request)
    assert result.status_code == 200, result.text
    assert result.json()["id"] != hidden_id
    assert "factory data" not in result.text
    assert client.post("/api/v1/incidents/INC-001/analyses", json=request).json()["id"] == result.json()["id"]
    assert client.get(f"/api/v1/analyses/{hidden_id}").status_code == 404
