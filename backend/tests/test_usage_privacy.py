"""Dummy-owner ledger boundaries, without provider calls."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from flooreplay.api import app
from flooreplay.auth import create_account, sign_in
from flooreplay.db import session_scope
from flooreplay.paid_models import AIRun, SpendEntry, now
from flooreplay.spending import usage_view


def _owner():
    name = "ledger-privacy-" + uuid4().hex
    password = "disposable-ledger-privacy-password"
    account = create_account(name, password, "owner")
    token = sign_in(name, password, name)["token"]
    return TestClient(app, headers={"Authorization": "Bearer " + token}), account


@pytest.fixture
def ledger_case():
    first, first_account = _owner()
    second, second_account = _owner()
    empty, _ = _owner()
    ids = [str(uuid4()), str(uuid4())]
    run_id = str(uuid4())
    workspace = second.get("/api/v1/workspaces").json()["items"][0]["id"]
    marker = "SYNTHETIC_PRIVATE_PROVIDER_OUTPUT_" + uuid4().hex
    before_capabilities = empty.get("/api/v1/capabilities").json()["ai"]
    with session_scope() as session:
        before = usage_view(session, include_entries=False)["committed_inr"]
        for identity, actor, charge in (
            (ids[0], first_account["id"], 1.0),
            (ids[1], second_account["id"], 2.0),
        ):
            session.add(
                SpendEntry(
                    id=identity,
                    user_id=actor,
                    purpose="reviewer",
                    operation="generation",
                    status="SETTLED",
                    reserved_inr=charge,
                    charged_inr=charge,
                    charged_usd=0,
                    price_table={"inr_per_usd": 90},
                    expires_at=now(),
                    details={"attempts": [{"output": {"claims": [{"text": marker}]}}]},
                )
            )
        session.add(
            AIRun(
                id=run_id,
                workspace_id=workspace,
                user_id=second_account["id"],
                request_key=uuid4().hex,
                identity=uuid4().hex,
                analysis_id="synthetic-ledger-test",
                task="summary",
                question="Synthetic private question",
                status="COMPLETED",
                packet={},
                configuration={},
                attempts=[],
                result={"output": {"claims": [{"text": marker}]}},
                reservation_id=ids[1],
            )
        )
    try:
        yield dict(
            first=first,
            second=second,
            empty=empty,
            ids=ids,
            run_id=run_id,
            marker=marker,
            committed=before + 3,
            capabilities=before_capabilities,
        )
    finally:
        with session_scope() as session:
            session.execute(delete(AIRun).where(AIRun.id == run_id))
            session.execute(delete(SpendEntry).where(SpendEntry.id.in_(ids)))


def test_ai_run_stays_workspace_scoped(ledger_case):
    case = ledger_case
    assert case["first"].get(f"/api/v1/ai-runs/{case['run_id']}").status_code == 404
    assert case["marker"] in case["second"].get(f"/api/v1/ai-runs/{case['run_id']}").text


def test_usage_hides_other_owner_details(ledger_case):
    case = ledger_case
    for client, expected in ((case["first"], case["ids"][0]), (case["second"], case["ids"][1])):
        response = client.get("/api/v1/usage")
        assert response.status_code == 200
        report = response.json()
        assert report["committed_inr"] == pytest.approx(case["committed"])
        assert {entry["id"] for entry in report["entries"]} == {expected}
        assert report["entries"][0]["details"] == {}
        assert case["marker"] not in response.text
    with session_scope() as session:
        # Filtering belongs to the HTTP view; the accounting/audit record is preserved.
        entry = session.get(SpendEntry, case["ids"][1])
        assert entry.details["attempts"][0]["output"]["claims"][0]["text"] == case["marker"]
        administrative = usage_view(session)
        assert set(case["ids"]) <= {entry["id"] for entry in administrative["entries"]}


def test_owner_without_entries_sees_only_shared_totals(ledger_case):
    case = ledger_case
    report = case["empty"].get("/api/v1/usage").json()
    assert report["entries"] == []
    assert report["committed_inr"] == pytest.approx(case["committed"])
    response = case["empty"].get("/api/v1/capabilities")
    assert case["marker"] not in response.text
    assert response.json()["ai"]["ready"] == case["capabilities"]["ready"]
    assert response.json()["ai"]["reasons"] == case["capabilities"]["reasons"]


def test_usage_requires_an_owner():
    assert TestClient(app).get("/api/v1/usage").status_code == 401
