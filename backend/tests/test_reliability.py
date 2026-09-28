"""Reliability and public-mode limit tests.

Startup recovery (RUNNING -> INTERRUPTED), the public-mode execution
limits (rate limiting, absent comparison execution), and the saved-report
fallback endpoint.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from flooreplay.api import app, create_app
from flooreplay.config import settings as app_settings
from flooreplay.models import ReplayAttempt
from flooreplay.seeding import run_seed
from flooreplay.service import recover_interrupted

pytestmark = pytest.mark.skipif(
    os.environ.get("FLOORREPLAY_SKIP_DB") == "1", reason="database not available"
)


@pytest.fixture(scope="module")
def client() -> TestClient:
    run_seed()  # idempotent
    return TestClient(app)


def _seed_attempt(lifecycle: str) -> str:
    """Insert a replay attempt row directly, bypassing execution."""
    from flooreplay.db import session_scope

    attempt_id = f"ATT-TEST-{uuid.uuid4().hex[:12]}"
    with session_scope() as session:
        session.add(
            ReplayAttempt(
                id=attempt_id,
                idempotency_key=f"rel-test-{uuid.uuid4().hex}",
                scenario_id="SCEN-HERO",
                scenario_revision=1,
                configuration_id="CFG-IMPROVED-V1",
                lifecycle=lifecycle,
                request_payload={
                    "scenario_id": "SCEN-HERO",
                    "scenario_revision": 1,
                    "configuration_id": "CFG-IMPROVED-V1",
                },
                created_at=datetime.now(tz=UTC),
            )
        )
        session.commit()
    return attempt_id


def _get_attempt(attempt_id: str) -> ReplayAttempt | None:
    from flooreplay.db import session_scope

    with session_scope() as session:
        return session.get(ReplayAttempt, attempt_id)


def test_recover_interrupted_marks_stuck_rows():
    stuck_id = _seed_attempt("RUNNING")
    done_id = _seed_attempt("COMPLETED")

    from flooreplay.db import session_scope

    with session_scope() as session:
        recover_interrupted(session)
    stuck = _get_attempt(stuck_id)
    assert stuck is not None and stuck.lifecycle == "INTERRUPTED"
    assert stuck.completed_at is None  # it never completed
    done = _get_attempt(done_id)
    assert done is not None and done.lifecycle == "COMPLETED"


def test_recover_interrupted_is_idempotent():
    _seed_attempt("RUNNING")
    from flooreplay.db import session_scope

    with session_scope() as session:
        first = recover_interrupted(session)
    assert first >= 1
    with session_scope() as session:
        assert recover_interrupted(session) == 0


def test_startup_lifespan_runs_recovery():
    stuck_id = _seed_attempt("RUNNING")
    with TestClient(create_app()) as _client:
        pass  # entering the context runs startup; recovery is what we assert on
    recovered = _get_attempt(stuck_id)
    assert recovered is not None and recovered.lifecycle == "INTERRUPTED"


def test_saved_report_fallback_returns_latest_completed(client: TestClient):
    created = client.post(
        "/api/v1/replays",
        json={
            "scenario_id": "SCEN-HERO",
            "scenario_revision": 2,
            "configuration_id": "CFG-IMPROVED-V1",
            "idempotency_key": f"saved-{uuid.uuid4().hex}",
        },
    ).json()
    latest = client.get(
        "/api/v1/replays/latest",
        params={
            "scenario_id": "SCEN-HERO",
            "scenario_revision": 2,
            "configuration_id": "CFG-IMPROVED-V1",
        },
    )
    assert latest.status_code == 200
    body = latest.json()
    assert body["id"] == created["id"]
    assert body["lifecycle"] == "COMPLETED"


def test_saved_report_fallback_404_without_history(client: TestClient):
    response = client.get(
        "/api/v1/replays/latest",
        params={
            "scenario_id": "SCEN-NO-SUCH-SCENARIO",
            "scenario_revision": 9,
            "configuration_id": "CFG-IMPROVED-V1",
        },
    )
    assert response.status_code == 404
    assert response.json()["code"] == "NO_SAVED_REPORT"


@pytest.fixture()
def public_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    # a fresh app per test means a fresh limiter, so rate-limit tests are
    # order-independent
    monkeypatch.setattr(app_settings, "public_replays_per_hour", 2)
    return TestClient(create_app(mode="public"))


def test_public_capabilities_report_limits_honestly(public_client: TestClient):
    body = public_client.get("/api/v1/capabilities").json()
    assert body["mode"] == "public"
    assert body["execution_limits"]["replays_per_hour_per_client"] == 2
    assert body["execution_limits"]["comparison_execution"] == "local_only"


def test_comparison_execution_is_absent_in_public_mode(public_client: TestClient):
    response = public_client.post(
        "/api/v1/comparisons",
        json={
            "suite_id": "SUITE-OPS-V1",
            "baseline_config_id": "CFG-BASELINE-V1",
            "candidate_config_id": "CFG-IMPROVED-V1",
            "idempotency_key": f"pub-{uuid.uuid4().hex}",
        },
    )
    assert response.status_code == 405  # the read route exists; POST is absent


def test_replays_rate_limit_returns_429_with_retry_after(public_client: TestClient):
    last_response = None
    for _ in range(3):
        last_response = public_client.post(
            "/api/v1/replays",
            json={
                "scenario_id": "SCEN-HERO",
                "scenario_revision": 2,
                "configuration_id": "CFG-IMPROVED-V1",
                "idempotency_key": f"rate-{uuid.uuid4().hex}",
            },
        )
    assert last_response is not None and last_response.status_code == 429
    assert last_response.json()["code"] == "RATE_LIMITED"
    assert "retry-after" in {k.lower() for k in last_response.headers}


def test_reads_stay_open_when_execution_is_limited(public_client: TestClient):
    scenarios = public_client.get("/api/v1/scenarios")
    assert scenarios.status_code == 200
    saved = public_client.get(
        "/api/v1/replays/latest",
        params={
            "scenario_id": "SCEN-HERO",
            "scenario_revision": 2,
            "configuration_id": "CFG-IMPROVED-V1",
        },
    )
    assert saved.status_code == 200
