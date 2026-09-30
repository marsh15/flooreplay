"""Suite execution and baseline comparison."""

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
def client(owner_headers) -> TestClient:
    from flooreplay.seeding import run_seed

    run_seed()
    return TestClient(app, headers=owner_headers)


def _compare(client: TestClient, baseline: str, candidate: str) -> dict:
    response = client.post(
        "/api/v1/comparisons",
        json={
            "suite_id": "SUITE-OPS-V1",
            "baseline_config_id": baseline,
            "candidate_config_id": candidate,
            "idempotency_key": f"cmp-{uuid.uuid4().hex}",
        },
    )
    assert response.status_code == 200
    return response.json()


def test_suite_is_seeded_with_32_cases(client: TestClient):
    suites = client.get("/api/v1/suites").json()["items"]
    assert any(s["id"] == "SUITE-OPS-V1" and s["case_count"] == 32 for s in suites)


def test_baseline_vs_improved_all_pass(client: TestClient):
    """The baseline meets its documented limitations; the improved config
    meets the same demands: every case passes on both sides."""
    report = _compare(client, "CFG-BASELINE-V1", "CFG-IMPROVED-V1")
    assert report["status"] == "COMPLETED"
    t = report["totals"]
    assert t["completed"] == 32 and t["total"] == 32
    assert t["unchanged_pass"] == 32
    assert t["regression"] == 0 and t["fixed"] == 0 and t["unchanged_fail"] == 0
    # Passing configurations still behave differently; changes are shown
    # separately from pass/fail.
    assert sum(1 for item in report["items"] if item["behavior_changed"]) > 0


def test_defect_regression_is_caught_by_the_suite(client: TestClient):
    report = _compare(client, "CFG-IMPROVED-V1", "CFG-DEFECT-SKILLFRESH")
    t = report["totals"]
    assert t["regression"] == 3
    regressed = {item["scenario_id"] for item in report["items"] if item["classification"] == "REGRESSION"}
    assert regressed == {"SUITE-B1", "SUITE-F1", "SUITE-F4"}
    for item in report["items"]:
        if item["classification"] == "REGRESSION":
            assert item["candidate"]["failures"], "regressions must carry their reasons"


def test_improved_config_meets_every_demand(client: TestClient):
    """Single-configuration integrity: the improved config passes all 32,
    visible as the candidate column of a baseline-vs-improved report."""
    report = _compare(client, "CFG-BASELINE-V1", "CFG-IMPROVED-V1")
    assert all(item["candidate"]["verdict"] == "PASS" for item in report["items"])


def test_identical_configurations_rejected(client: TestClient):
    response = client.post(
        "/api/v1/comparisons",
        json={
            "suite_id": "SUITE-OPS-V1",
            "baseline_config_id": "CFG-IMPROVED-V1",
            "candidate_config_id": "CFG-IMPROVED-V1",
            "idempotency_key": f"cmp-{uuid.uuid4().hex}",
        },
    )
    assert response.status_code == 422
    assert response.json()["code"] == "COMPARISON_CONFIGS_IDENTICAL"


def test_comparison_idempotency(client: TestClient):
    key = f"cmp-idem-{uuid.uuid4().hex}"
    body = {
        "suite_id": "SUITE-OPS-V1",
        "baseline_config_id": "CFG-IMPROVED-V1",
        "candidate_config_id": "CFG-DEFECT-SKILLFRESH",
        "idempotency_key": key,
    }
    first = client.post("/api/v1/comparisons", json=body).json()
    same = client.post("/api/v1/comparisons", json=body).json()
    assert first["id"] == same["id"]
    body["candidate_config_id"] = "CFG-BASELINE-V1"
    conflict = client.post("/api/v1/comparisons", json=body)
    assert conflict.status_code == 409


def test_unknown_suite_rejected(client: TestClient):
    response = client.post(
        "/api/v1/comparisons",
        json={
            "suite_id": "SUITE-NOPE",
            "baseline_config_id": "CFG-BASELINE-V1",
            "candidate_config_id": "CFG-IMPROVED-V1",
            "idempotency_key": f"cmp-{uuid.uuid4().hex}",
        },
    )
    assert response.status_code == 404


def test_comparison_listing_and_detail(client: TestClient):
    _compare(client, "CFG-BASELINE-V1", "CFG-IMPROVED-V1")
    listing = client.get("/api/v1/comparisons").json()["items"]
    assert listing
    detail = client.get(f"/api/v1/comparisons/{listing[0]['id']}")
    assert detail.status_code == 200
    assert detail.json()["items"]
