"""The synthetic Tiruppur demo: its stories, its frozen cases and its idempotent seeding."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from flooreplay.api import app
from flooreplay.db import session_scope
from flooreplay.decisions import demo
from flooreplay.decisions.policy import DEFAULT_POLICY_V1, policy_digest
from flooreplay.decisions.replay import replay
from flooreplay.decisions.snapshot import snapshot_at
from flooreplay.decisions.types import ConstraintId, ConstraintStatus

ROUTE = "/api/v1/decisions"
WS = demo.WORKSPACE


def run(order_id: str, hour: int, minute: int = 0):  # type: ignore[no-untyped-def]
    cutoff = demo.ist(hour, minute)
    known = [f for f in demo.demo_facts() if f.known_at <= cutoff]
    return replay(snapshot_at(known, cutoff), order_id, DEFAULT_POLICY_V1, demo.erp_coverage())


def test_the_conflicting_stock_story_resolves_after_qa_reviews_it() -> None:
    conflicted = run("POLO-221", 11)
    assert conflicted.gate.state.value == "CONFLICTING"
    assert conflicted.recommendation.outcome.value == "NEEDS_REVIEW"
    assert any(f.code == "conflict_rule" for f in conflicted.gate.findings)

    resolved = run("POLO-221", 13)
    assert resolved.gate.state.value == "READY"
    assert resolved.recommendation.outcome.value == "ACCEPT"
    navy = next(c for c in resolved.constraints if c.constraint is ConstraintId.FABRIC and c.subject == "NAVY")
    assert navy.status is ConstraintStatus.PASS


@pytest.mark.parametrize(
    ("order_id", "gate", "outcome"),
    [
        ("POLO-222", "READY", "ACCEPT_WITH_CONDITIONS"),
        ("POLO-223", "READY", "NEEDS_REVIEW"),
        ("POLO-224", "STALE", "NEEDS_REVIEW"),
        ("POLO-225", "READY", "NEEDS_REVIEW"),
    ],
)
def test_each_demo_order_shows_one_outcome(order_id: str, gate: str, outcome: str) -> None:
    result = run(order_id, 13)
    assert (result.gate.state.value, result.recommendation.outcome.value) == (gate, outcome)


def test_the_overtime_order_names_its_condition_and_the_approval_order_keeps_its_candidate() -> None:
    [condition] = run("POLO-222", 13).recommendation.conditions
    assert (condition.lines, condition.hours_per_line_per_day) == (4, 2)
    approval = run("POLO-225", 13).recommendation
    assert approval.candidate_outcome is not None and approval.candidate_outcome.value == "ACCEPT"


def test_the_candidate_policy_fixes_one_case_and_regresses_another() -> None:
    classes = demo.classify_cases()
    assert classes == demo.EXPECTED_CLASSIFICATIONS
    assert sorted(v for v in classes.values() if v in {"FIXED", "REGRESSION"}) == ["FIXED", "REGRESSION"]
    assert classes["case-07-thin-safety-margin"] == "FIXED"
    assert classes["case-03-overtime-covers"] == "REGRESSION"


def test_verification_passes_and_catches_a_wrong_declaration(monkeypatch: pytest.MonkeyPatch) -> None:
    assert demo.verify_cases()["status"] == "PASSED"
    broken = {**demo.EXPECTED_CLASSIFICATIONS, "case-02-qa-resolved": "FIXED"}
    monkeypatch.setattr(demo, "EXPECTED_CLASSIFICATIONS", broken)
    result = demo.verify_cases()
    assert result["status"] == "FAILED"
    assert any("case-02-qa-resolved" in problem for problem in result["problems"])


def test_everything_in_the_demo_is_labelled_synthetic() -> None:
    assert "synthetic" in demo.FACTORY
    assert all(f.id for f in demo.demo_facts())
    assert demo.verify_cases()["synthetic"] is True


def test_seeding_twice_creates_nothing_the_second_time() -> None:
    with session_scope() as session:
        demo.seed_demo(session)
    with session_scope() as session:
        second = demo.seed_demo(session)
    assert second == {"facts": 0, "artifacts": 0, "policies": 0, "cases": 0, "evaluations": 0, "runs": 0}


def test_an_anonymous_visitor_can_walk_the_whole_demo() -> None:
    with session_scope() as session:
        demo.seed_demo(session)
    visitor = TestClient(app)

    orders = visitor.get(f"{ROUTE}/orders?workspace_id={WS}").json()["items"]
    by_id = {order["order_id"]: order for order in orders}
    assert {"POLO-221", "POLO-222", "POLO-223", "POLO-224", "POLO-225"} <= set(by_id)
    assert by_id["POLO-221"]["latest"]["outcome"] == "ACCEPT"
    assert by_id["POLO-221"]["buyer"] == "Synthetic Buyer A"
    assert by_id["POLO-224"]["latest"]["gate_state"] == "STALE"

    def decision(hour_utc_cutoff: str) -> dict[str, object]:
        url = f"{ROUTE}/orders/POLO-221?workspace_id={WS}&cutoff={hour_utc_cutoff}"
        response = visitor.get(url)
        assert response.status_code == 200, response.text
        body: dict[str, object] = response.json()
        return body

    conflicted = decision("2026-10-22T05:30:00Z")
    assert conflicted["gate"]["state"] == "CONFLICTING"  # type: ignore[index]
    resolved = decision("2026-10-22T07:30:00Z")
    assert resolved["recommendation"]["outcome"] == "ACCEPT"  # type: ignore[index]
    shown = {fact["id"] for fact in resolved["facts"]}  # type: ignore[attr-defined]
    assert {"note-L-221-shade", "resolution-L-221"} <= shown

    timeline = visitor.get(f"{ROUTE}/orders/POLO-221/timeline?workspace_id={WS}").json()
    kinds = [event["kind"] for event in timeline["events"]]
    assert "resolution" in kinds and "fabric_qc" in kinds
    assert timeline["knowledge_times"] == sorted(timeline["knowledge_times"])

    policies = visitor.get(f"{ROUTE}/policies?workspace_id={WS}").json()
    assert policies["adopted"] == policy_digest(DEFAULT_POLICY_V1)
    candidate = next(p for p in policies["items"] if p["policy_digest"] != policies["adopted"])
    runs = visitor.get(f"{ROUTE}/regression-runs?workspace_id={WS}&candidate={candidate['policy_digest']}").json()
    classes = {case["case_id"]: case["classification"] for case in runs["items"][0]["cases"]}
    assert classes == demo.EXPECTED_CLASSIFICATIONS
    assert runs["items"][0]["complete"] is True

    adopt = visitor.post(
        f"{ROUTE}/regression-runs/{runs['items'][0]['id']}/adopt?workspace_id={WS}",
        json={"acknowledgements": {"case-03-overtime-covers": "I accept this."}},
    )
    assert adopt.status_code == 401


def test_the_sandbox_command_loads_the_demo_into_the_owners_private_workspace(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    import json
    import sys
    import uuid

    from flooreplay.__main__ import main
    from flooreplay.auth import create_account

    name = "sandbox-" + uuid.uuid4().hex
    create_account(name, "sandbox-test-password", "owner")
    monkeypatch.setattr(sys, "argv", ["flooreplay", "decisions-demo", "--owner", name])
    assert main() == 0
    first = json.loads(capsys.readouterr().out)
    assert first["workspace"].startswith("owner-") and first["cases"] == len(demo.case_specs())
    assert main() == 0
    second = json.loads(capsys.readouterr().out)
    assert second["workspace"] == first["workspace"]
    assert {k: v for k, v in second.items() if k != "workspace"} == dict.fromkeys(
        ("facts", "artifacts", "policies", "cases", "evaluations", "runs"), 0
    )
