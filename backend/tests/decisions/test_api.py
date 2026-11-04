"""HTTP tests for the decisions router (T13).

Every test signs in real accounts and works in uuid workspaces with uuid keys, because the
facts trigger forbids cleanup. Owners get their personal workspace from the workspaces route.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from decisions.worlds import ERP_ARTIFACT, ready_world
from flooreplay import ai_runs
from flooreplay.api import app, create_app
from flooreplay.auth import create_account, sign_in
from flooreplay.config import settings as app_settings
from flooreplay.db import session_scope
from flooreplay.decisions import service
from flooreplay.decisions.expectations import Expectation
from flooreplay.decisions.models import DecisionSourceArtifact
from flooreplay.decisions.policy import DEFAULT_POLICY_V1, PolicyDocument, policy_digest
from flooreplay.decisions.types import Recommendation
from flooreplay.workspaces import WorkspaceMember

PASSWORD = "decisions-api-test-password"
# Every world fact is valid from 2026-03-01 21:00 at the latest; known just before the 09:00 cutoff.
KNOWN_AT = datetime(2026, 3, 2, 8, 0, tzinfo=UTC)
ROUTE = "/api/v1/decisions"


def uid() -> str:
    return uuid.uuid4().hex


def client_for(role: str = "owner", *, mode: str | None = None) -> tuple[TestClient, str]:
    name = "decisions-" + uid()
    user = create_account(name, PASSWORD, role)
    token = sign_in(name, PASSWORD, name)["token"]
    base = app if mode is None else create_app(mode=mode)
    return TestClient(base, headers={"Authorization": "Bearer " + token}), user["id"]


def owner_workspace(client: TestClient) -> str:
    return str(client.get("/api/v1/workspaces").json()["items"][0]["id"])


def seed_world(workspace: str) -> Any:
    world = ready_world()
    with session_scope() as session:
        session.add(
            DecisionSourceArtifact(
                id=ERP_ARTIFACT,
                workspace_id=workspace,
                profile="erp_fabric_stock",
                filename="stock.csv",
                raw_bytes=b"lot,qty\nL1,10\n",
                raw_digest="sha256:" + "0" * 64,
                as_of=KNOWN_AT - timedelta(hours=2),
                known_at=KNOWN_AT - timedelta(hours=1),
                coverage={"fabric_qualities": ["SJ180"]},
                idempotency_key=uid(),
                preview_digest="sha256:" + "1" * 64,
            )
        )
        service.append_facts(session, world.facts, workspace_id=workspace, trusted_known_at=KNOWN_AT)
    return world


def candidate_policy() -> PolicyDocument:
    data = DEFAULT_POLICY_V1.model_dump(mode="json")
    data["label"] = "candidate " + uid()
    data["enabled_constraints"] = [c.value for c in DEFAULT_POLICY_V1.enabled_constraints[1:]]
    return PolicyDocument.model_validate(data)


def add_suite(workspace: str) -> str:
    """One frozen case whose gold outcome is ACCEPT; the candidate policy will flip it."""
    world = ready_world()
    case_id = "case-" + uid()
    with session_scope() as session:
        service.create_case(
            session,
            workspace,
            case_id,
            "ready case",
            world.cutoff,
            world.order_id,
            world.facts,
            world.coverage,
            synthetic=True,
        )
        service.add_expectation(
            session, workspace, case_id, Expectation(correct=Recommendation.ACCEPT, rationale="gold")
        )
    return case_id


def evaluate_body(order_id: str = "O1") -> dict[str, str]:
    return {"order_id": order_id, "cutoff": "2026-03-02T09:00:00+00:00"}


def test_every_route_requires_sign_in() -> None:
    anonymous = TestClient(app)
    ws = "ws-" + uid()
    calls = [
        ("get", f"{ROUTE}/orders?workspace_id={ws}", None),
        ("get", f"{ROUTE}/snapshot?workspace_id={ws}&cutoff=2026-03-02T09:00:00%2B00:00", None),
        ("post", f"{ROUTE}/evaluate?workspace_id={ws}", evaluate_body()),
        ("get", f"{ROUTE}/policies?workspace_id={ws}", None),
        ("post", f"{ROUTE}/policies/diff?workspace_id={ws}", {"baseline": {}, "candidate": {}}),
        ("get", f"{ROUTE}/regression-runs/x?workspace_id={ws}", None),
        ("post", f"{ROUTE}/regression-runs/x/adopt?workspace_id={ws}", {"acknowledgements": {}}),
    ]
    for method, path, body in calls:
        response = getattr(anonymous, method)(path, json=body) if body is not None else getattr(anonymous, method)(path)
        assert response.status_code == 401, path
        assert response.json()["code"] == "SIGN_IN_REQUIRED"


def test_owner_adopts_and_reviewer_is_refused_by_role() -> None:
    owner, _ = client_for("owner")
    ws = owner_workspace(owner)
    seed_world(ws)
    case_id = add_suite(ws)
    run = owner.post(
        f"{ROUTE}/regression-runs?workspace_id={ws}",
        json={"baseline": DEFAULT_POLICY_V1.model_dump(mode="json"), "candidate": candidate_policy().model_dump(mode="json")},
    )
    assert run.status_code == 200, run.text
    body = run.json()
    assert body["complete"] is True
    assert {c["case_id"]: c["classification"] for c in body["cases"]} == {case_id: "REGRESSION"}

    reviewer, reviewer_id = client_for("reviewer")
    with session_scope() as session:
        session.add(WorkspaceMember(workspace_id=ws, account_id=reviewer_id, role="member"))
    # A reviewer, even one who names the owner role in the body, is refused by the route.
    refused = reviewer.post(
        f"{ROUTE}/regression-runs/{body['id']}/adopt?workspace_id={ws}",
        json={"acknowledgements": {case_id: "Accepted."}, "actor_role": "owner"},
    )
    assert refused.status_code == 403
    assert refused.json()["code"] == "ADOPTION_FORBIDDEN"

    adopted = owner.post(
        f"{ROUTE}/regression-runs/{body['id']}/adopt?workspace_id={ws}",
        json={"acknowledgements": {case_id: "Accepted."}},
    )
    assert adopted.status_code == 200, adopted.text
    assert adopted.json()["adopted_by"]
    assert adopted.json()["acknowledgements"] == {case_id: "Accepted."}


def test_a_global_owner_who_is_only_a_workspace_member_cannot_adopt() -> None:
    owner, _ = client_for("owner")
    ws = owner_workspace(owner)
    seed_world(ws)
    case_id = add_suite(ws)
    run = owner.post(
        f"{ROUTE}/regression-runs?workspace_id={ws}",
        json={"baseline": DEFAULT_POLICY_V1.model_dump(mode="json"), "candidate": candidate_policy().model_dump(mode="json")},
    ).json()
    other_owner, other_id = client_for("owner")
    with session_scope() as session:
        session.add(WorkspaceMember(workspace_id=ws, account_id=other_id, role="member"))
    refused = other_owner.post(
        f"{ROUTE}/regression-runs/{run['id']}/adopt?workspace_id={ws}",
        json={"acknowledgements": {case_id: "Accepted."}},
    )
    assert refused.status_code == 403
    assert refused.json()["code"] == "ADOPTION_FORBIDDEN"


@pytest.mark.parametrize("cutoff", ["0001-01-01T00:00:00+05:30", "9999-12-31T23:59:59-05:00"])
def test_extreme_cutoffs_are_a_client_error_not_a_503(cutoff: str) -> None:
    owner, _ = client_for("owner")
    ws = owner_workspace(owner)
    response = owner.get(f"{ROUTE}/snapshot", params={"workspace_id": ws, "cutoff": cutoff})
    assert response.status_code in {200, 422}, response.text


def test_cross_workspace_ids_are_not_found() -> None:
    owner, _ = client_for("owner")
    other, _ = client_for("owner")
    ws = owner_workspace(owner)
    other_ws = owner_workspace(other)
    seed_world(ws)
    add_suite(ws)
    run = owner.post(
        f"{ROUTE}/regression-runs?workspace_id={ws}",
        json={"baseline": DEFAULT_POLICY_V1.model_dump(mode="json"), "candidate": candidate_policy().model_dump(mode="json")},
    ).json()
    evaluation = owner.post(f"{ROUTE}/evaluate?workspace_id={ws}", json=evaluate_body()).json()

    assert other.get(f"{ROUTE}/orders?workspace_id={ws}").status_code == 404
    assert other.post(f"{ROUTE}/evaluate?workspace_id={ws}", json=evaluate_body()).status_code == 404
    assert other.get(f"{ROUTE}/regression-runs/{run['id']}?workspace_id={other_ws}").status_code == 404
    assert other.get(f"{ROUTE}/evaluations/{evaluation['id']}?workspace_id={other_ws}").status_code == 404
    assert other.post(
        f"{ROUTE}/evaluations/{evaluation['id']}/record?workspace_id={other_ws}",
        json={"decision": "ACCEPT", "reason": "x"},
    ).status_code == 404
    # The owner of the first workspace can still use the second id it does not belong to only as 404.
    assert owner.get(f"{ROUTE}/orders?workspace_id={other_ws}").status_code == 404


def test_evaluate_is_idempotent_and_reconstructs() -> None:
    owner, _ = client_for("owner")
    ws = owner_workspace(owner)
    seed_world(ws)
    first = owner.post(f"{ROUTE}/evaluate?workspace_id={ws}", json=evaluate_body())
    second = owner.post(f"{ROUTE}/evaluate?workspace_id={ws}", json=evaluate_body())
    assert first.status_code == 200, first.text
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert first.json()["outcome"] == "ACCEPT"

    detail = owner.get(f"{ROUTE}/evaluations/{first.json()['id']}?workspace_id={ws}").json()
    assert detail["reconstruction"]["matches"] is True
    assert detail["evaluation"]["id"] == first.json()["id"]


def test_record_override_needs_a_reason() -> None:
    owner, _ = client_for("owner")
    ws = owner_workspace(owner)
    seed_world(ws)
    evaluation = owner.post(f"{ROUTE}/evaluate?workspace_id={ws}", json=evaluate_body()).json()
    url = f"{ROUTE}/evaluations/{evaluation['id']}/record?workspace_id={ws}"
    other = Recommendation.DECLINE.value if evaluation["outcome"] != "DECLINE" else "ACCEPT"

    no_reason = owner.post(url, json={"decision": other, "reason": "   "})
    assert no_reason.status_code == 422
    assert no_reason.json()["code"] == "OVERRIDE_REASON_REQUIRED"

    agreed = owner.post(url, json={"decision": evaluation["outcome"]})
    assert agreed.status_code == 422
    assert agreed.json()["code"] == "DECISION_REASON_REQUIRED"

    overridden = owner.post(url, json={"decision": other, "reason": "Dyeing note is newer than the ERP stock."})
    assert overridden.status_code == 200, overridden.text
    assert overridden.json()["override"] is True
    assert overridden.json()["reason"] == "Dyeing note is newer than the ERP stock."


def test_naive_cutoff_is_rejected() -> None:
    owner, _ = client_for("owner")
    ws = owner_workspace(owner)
    seed_world(ws)
    naive = "2026-03-02T09:00:00"
    snapshot = owner.get(f"{ROUTE}/snapshot?workspace_id={ws}&cutoff={naive}")
    assert snapshot.status_code == 422
    assert snapshot.json()["code"] == "CUTOFF_INVALID"
    evaluate = owner.post(f"{ROUTE}/evaluate?workspace_id={ws}", json={"order_id": "O1", "cutoff": naive})
    assert evaluate.status_code == 422
    assert evaluate.json()["code"] == "CUTOFF_INVALID"
    aware = owner.get(f"{ROUTE}/snapshot?workspace_id={ws}&cutoff=2026-03-02T09:00:00%2B05:30")
    assert aware.status_code == 200
    assert aware.json()["settled"] is True


def test_orders_and_policies_round_trip() -> None:
    owner, _ = client_for("owner")
    ws = owner_workspace(owner)
    seed_world(ws)
    orders = owner.get(f"{ROUTE}/orders?workspace_id={ws}").json()["items"]
    assert [item["order_id"] for item in orders] == ["O1"]
    order = owner.get(f"{ROUTE}/orders/O1?workspace_id={ws}&cutoff=2026-03-02T09:00:00%2B00:00")
    assert order.status_code == 200
    assert order.json()["facts"] and order.json()["facts"][0]["entity_key"] == "order:O1"
    assert owner.get(f"{ROUTE}/orders/NOPE?workspace_id={ws}&cutoff=2026-03-02T09:00:00%2B00:00").status_code == 404

    stored = owner.post(f"{ROUTE}/policies?workspace_id={ws}", json=DEFAULT_POLICY_V1.model_dump(mode="json"))
    assert stored.status_code == 200, stored.text
    assert stored.json()["policy_digest"] == policy_digest(DEFAULT_POLICY_V1)
    listed = owner.get(f"{ROUTE}/policies?workspace_id={ws}").json()["items"]
    assert [item["policy_digest"] for item in listed] == [policy_digest(DEFAULT_POLICY_V1)]

    diff = owner.post(
        f"{ROUTE}/policies/diff?workspace_id={ws}",
        json={
            "baseline": DEFAULT_POLICY_V1.model_dump(mode="json"),
            "candidate": candidate_policy().model_dump(mode="json"),
        },
    )
    assert diff.status_code == 200, diff.text
    paths = {change["path"] for change in diff.json()["changes"]}
    assert "enabled_constraints" in paths or any(p.startswith("label") for p in paths)


def test_evaluate_never_calls_a_model_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("a decisions route must not call a model provider")

    monkeypatch.setattr(ai_runs, "run_ai", refuse)
    owner, _ = client_for("owner")
    ws = owner_workspace(owner)
    seed_world(ws)
    assert owner.post(f"{ROUTE}/evaluate?workspace_id={ws}", json=evaluate_body()).status_code == 200


def test_evaluate_is_rate_limited_in_public_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_settings, "public_replays_per_hour", 2)
    owner, _ = client_for("owner", mode="public")
    ws = owner_workspace(owner)
    seed_world(ws)
    statuses = [owner.post(f"{ROUTE}/evaluate?workspace_id={ws}", json=evaluate_body()).status_code for _ in range(3)]
    assert statuses == [200, 200, 429]
