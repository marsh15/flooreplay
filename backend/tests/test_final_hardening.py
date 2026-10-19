"""Regression cases for private replay reviews and bounded public execution."""
from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from flooreplay.api import app
from flooreplay.auth import create_account, sign_in
from flooreplay.db import session_scope
from flooreplay.models import ReviewCheck, ScenarioRevision
from flooreplay.paid_models import SpendEntry, now
from flooreplay.ratelimit import SlidingWindowLimiter
from flooreplay.seeding import run_seed
from flooreplay.spending import usage_view


def account_client(role):
    username = "review-scope-" + uuid4().hex
    user = create_account(username, "dummy-review-regression-password", role)
    token = sign_in(username, "dummy-review-regression-password", username)["token"]
    return TestClient(app, headers={"Authorization": "Bearer " + token}), user


def test_review_inherits_evidence_workspace_for_reviewers_and_owners():
    run_seed()
    owner, _ = account_client("owner")
    reviewer, member = account_client("reviewer")
    workspace = owner.post("/api/v1/workspaces", json={"name": "Private review regression"}).json()["id"]
    assert owner.post(f"/api/v1/workspaces/{workspace}/members", json={"account_id": member["id"]}).status_code == 200
    scenario_id = "PRIVATE-REVIEW-" + uuid4().hex
    with session_scope() as session:
        template = session.get(ScenarioRevision, ("SCEN-HERO", 2))
        assert template is not None
        values = {column.name: deepcopy(getattr(template, column.name)) for column in ScenarioRevision.__table__.columns}
        values.update(workspace_id=workspace, scenario_id=scenario_id)
        session.add(ScenarioRevision(**values))
    replay = reviewer.post("/api/v1/replays", json={"scenario_id": scenario_id, "scenario_revision": 2, "configuration_id": "CFG-IMPROVED-V1", "idempotency_key": "private-review-" + uuid4().hex})
    assert replay.status_code == 200, replay.text
    assert replay.json()["result"]["proposal"]
    body = {"original_replay_id": replay.json()["id"], "target_scenario_id": scenario_id, "target_scenario_revision": 2}
    for client in (reviewer, owner):
        result = client.post("/api/v1/review-checks", json=body)
        assert result.status_code == 200, result.text
        with session_scope() as session:
            row = session.get(ReviewCheck, result.json()["id"])
            assert row is not None and row.workspace_id == workspace
        public_ids = {item["id"] for item in TestClient(app).get("/api/v1/review-checks").json()["items"]}
        assert result.json()["id"] not in public_ids
    mixed = reviewer.post("/api/v1/review-checks", json={**body, "target_scenario_id": "SCEN-HERO"})
    assert mixed.status_code == 422
    assert mixed.json()["code"] == "REVIEW_INCOMPATIBLE"


def test_public_limit_preserves_existing_clients_and_releases_expired_capacity(monkeypatch):
    clock = [1.0]
    monkeypatch.setattr("flooreplay.ratelimit.time.monotonic", lambda: clock[0])
    limiter = SlidingWindowLimiter(1, 60)
    for index in range(10_000):
        assert limiter.allow(str(index))[0]
    assert not limiter.allow("new-client")[0]
    assert not limiter.allow("0")[0]
    clock[0] = 62.0
    assert limiter.allow("new-client")[0]


def test_hybrid_cutoff_is_rejected_before_paid_work(owner_headers):
    client = TestClient(app, headers=owner_headers)
    for cutoff in ("invalid", "2026-10-02T09:00:00"):
        response = client.post("/api/v1/incidents/search/hybrid", json={"query": "stoppage", "corpus_id": "unused", "cutoff": cutoff, "idempotency_key": "invalid-cutoff-" + uuid4().hex})
        assert response.status_code == 422


def test_allowance_totals_include_ledger_rows_beyond_display_page():
    with session_scope() as session:
        before = usage_view(session)["committed_inr"]
        session.add_all([SpendEntry(user_id="dummy-ledger-regression", purpose="development", operation="generation", status="SETTLED", reserved_inr=0.1, charged_inr=0.02, price_table={"inr_per_usd": 90}, expires_at=now()) for _ in range(121)])
        session.flush()
        report = usage_view(session)
        assert report["committed_inr"] == pytest.approx(before + 121 * 0.02)
        assert len(report["entries"]) == 100
        assert usage_view(session, include_entries=False)["committed_inr"] == report["committed_inr"]
        session.rollback()
