"""API integration tests against the seeded local database.

These exercise the HTTP surface end to end: execution outcomes, the error
envelope, idempotency semantics, and immutable artifact reads.
"""

from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient

from flooreplay.api import app

pytestmark = pytest.mark.skipif(
    os.environ.get("FLOORREPLAY_SKIP_DB") == "1", reason="database not available"
)


@pytest.fixture(scope="module")
def client() -> TestClient:
    from flooreplay.seeding import run_seed

    run_seed()  # idempotent
    return TestClient(app)


def _replay(client: TestClient, rev: int, cfg: str) -> dict:
    response = client.post(
        "/api/v1/replays",
        json={
            "scenario_id": "SCEN-HERO",
            "scenario_revision": rev,
            "configuration_id": cfg,
            "idempotency_key": f"api-test-{uuid.uuid4().hex}",
        },
    )
    assert response.status_code == 200
    return response.json()


def test_capabilities(client: TestClient):
    body = client.get("/api/v1/capabilities").json()
    assert body["mode"] in ("local", "public")
    assert len(body["configurations"]) == 3


def test_hero_outcomes_through_api(client: TestClient):
    assert _replay(client, 1, "CFG-IMPROVED-V1")["domain_outcome"] == "NEEDS_CONTEXT"
    baseline = _replay(client, 2, "CFG-BASELINE-V1")
    assert baseline["domain_outcome"] == "REJECTED_BY_CONSTRAINT"
    assert baseline["result"]["proposal"]["operator_id"] == "O204"
    improved = _replay(client, 2, "CFG-IMPROVED-V1")
    assert improved["domain_outcome"] == "READY_FOR_REVIEW"
    assert improved["result"]["proposal"]["operator_id"] == "O219"
    assert improved["manifest_digest"].startswith("sha256:")


def test_defect_regression_is_detected(client: TestClient):
    body = _replay(client, 1, "CFG-DEFECT-SKILLFRESH")
    assert body["domain_outcome"] == "READY_FOR_REVIEW"  # the defect runs
    assert body["expectation_verdict"] == "FAIL"  # and the suite catches it


def test_idempotency_semantics(client: TestClient):
    key = f"idem-{uuid.uuid4().hex}"
    first = client.post(
        "/api/v1/replays",
        json={
            "scenario_id": "SCEN-HERO",
            "scenario_revision": 2,
            "configuration_id": "CFG-IMPROVED-V1",
            "idempotency_key": key,
        },
    )
    same = client.post(
        "/api/v1/replays",
        json={
            "scenario_id": "SCEN-HERO",
            "scenario_revision": 2,
            "configuration_id": "CFG-IMPROVED-V1",
            "idempotency_key": key,
        },
    )
    conflict = client.post(
        "/api/v1/replays",
        json={
            "scenario_id": "SCEN-HERO",
            "scenario_revision": 1,
            "configuration_id": "CFG-IMPROVED-V1",
            "idempotency_key": key,
        },
    )
    assert first.json()["id"] == same.json()["id"]
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "IDEMPOTENCY_CONFLICT"


def test_error_envelope(client: TestClient):
    response = client.post(
        "/api/v1/replays",
        json={
            "scenario_id": "SCEN-MISSING",
            "scenario_revision": 1,
            "configuration_id": "CFG-IMPROVED-V1",
            "idempotency_key": f"err-{uuid.uuid4().hex}",
        },
    )
    assert response.status_code == 404
    body = response.json()
    assert set(body) == {"code", "message", "details", "trace_id"}


def test_snapshot_detail_immutable_read(client: TestClient):
    body = client.get("/api/v1/snapshots/SNAP-SKILL-2026-09-18-B").json()
    assert body["kind"] == "SKILLS"
    assert body["content_digest"].startswith("sha256:")
    assert client.get("/api/v1/snapshots/NOPE").status_code == 404


def test_scenario_listing_includes_latest_attempts(client: TestClient):
    _replay(client, 2, "CFG-IMPROVED-V1")
    body = client.get("/api/v1/scenarios").json()
    assert body["items"], "scenario library must not be empty"
    improved_rows = [
        a for a in body["latest_attempts"] if a["configuration_id"] == "CFG-IMPROVED-V1"
    ]
    assert improved_rows
