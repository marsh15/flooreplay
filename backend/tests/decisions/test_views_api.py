"""HTTP tests for the order views the frontend reads: summaries, the decision view, the
timeline, recording by order, the adopted policy, stored runs and anonymous demo reads.

Worlds are written into uuid workspaces (the facts trigger forbids cleanup). The public demo
workspace is only read here, never written.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from decisions.test_api import (
    KNOWN_AT,
    ROUTE,
    add_suite,
    candidate_policy,
    client_for,
    evaluate_body,
    owner_workspace,
    seed_world,
    uid,
)
from decisions.worlds import AS_OF, ERP_ARTIFACT, ready_world
from flooreplay.api import app
from flooreplay.db import session_scope
from flooreplay.decisions import service
from flooreplay.decisions.models import DecisionSourceArtifact
from flooreplay.decisions.policy import DEFAULT_POLICY_V1, policy_digest
from flooreplay.decisions.types import FactKind

CUTOFF = "2026-03-02T09:00:00%2B00:00"
DEFAULT_DIGEST = policy_digest(DEFAULT_POLICY_V1)


def test_order_summaries_carry_the_order_request_and_latest_outcome() -> None:
    owner, _ = client_for("owner")
    ws = owner_workspace(owner)
    seed_world(ws)
    [summary] = owner.get(f"{ROUTE}/orders?workspace_id={ws}").json()["items"]
    assert summary["order_id"] == "O1"
    assert summary["buyer"] == "BUYER-1"
    assert summary["style_id"] == "S1"
    assert summary["ship_date"] == "2026-03-30"
    assert summary["total_qty"] == "1000"
    assert summary["latest"] is None

    owner.post(f"{ROUTE}/evaluate?workspace_id={ws}", json=evaluate_body())
    [after] = owner.get(f"{ROUTE}/orders?workspace_id={ws}").json()["items"]
    assert after["latest"]["outcome"] == "ACCEPT"
    assert after["latest"]["gate_state"] == "READY"
    assert after["latest"]["cutoff"].startswith("2026-03-02T09:00:00")


def test_decision_view_replays_without_storing_anything() -> None:
    owner, _ = client_for("owner")
    ws = owner_workspace(owner)
    seed_world(ws)
    response = owner.get(f"{ROUTE}/orders/O1?workspace_id={ws}&cutoff={CUTOFF}")
    assert response.status_code == 200, response.text
    view = response.json()
    assert view["order_id"] == "O1"
    assert view["settled"] is True
    assert view["policy"] == {
        "digest": DEFAULT_DIGEST,
        "label": DEFAULT_POLICY_V1.label,
        "engine_version": DEFAULT_POLICY_V1.engine_version,
    }
    assert view["gate"]["state"] == "READY"
    assert view["recommendation"]["outcome"] == "ACCEPT"
    assert {c["constraint"] for c in view["constraints"]} >= {"FABRIC", "TRIMS", "CAPACITY", "APPROVAL"}
    assert view["facts"][0]["entity_key"] == "order:O1"
    assert view["records"] == []
    assert view["decision_digest"] and view["snapshot_digest"]
    # A read stores no evaluation: the order has no latest outcome afterwards.
    [summary] = owner.get(f"{ROUTE}/orders?workspace_id={ws}").json()["items"]
    assert summary["latest"] is None


def test_decision_view_lists_the_facts_its_findings_and_constraints_cite() -> None:
    owner, _ = client_for("owner")
    ws = owner_workspace(owner)
    seed_world(ws)
    view = owner.get(f"{ROUTE}/orders/O1?workspace_id={ws}&cutoff={CUTOFF}").json()
    shown = {fact["id"] for fact in view["facts"]}
    cited = {fid for c in view["constraints"] for fid in c["fact_ids"]}
    assert cited and cited <= shown
    # Every shown fact carries the fields the fact drawer needs.
    for fact in view["facts"]:
        assert set(fact) >= {"id", "kind", "entity_key", "payload", "valid_from", "known_at", "source"}


def test_decision_view_matches_the_stored_evaluation_and_lists_records() -> None:
    owner, _ = client_for("owner")
    ws = owner_workspace(owner)
    seed_world(ws)
    evaluation = owner.post(f"{ROUTE}/evaluate?workspace_id={ws}", json=evaluate_body()).json()
    view = owner.get(f"{ROUTE}/orders/O1?workspace_id={ws}&cutoff={CUTOFF}").json()
    assert view["decision_digest"] == evaluation["decision_digest"]
    assert view["records"] == []

    recorded = owner.post(
        f"{ROUTE}/orders/O1/records?workspace_id={ws}",
        json={
            "cutoff": "2026-03-02T09:00:00Z",
            "policy_digest": DEFAULT_DIGEST,
            "final_outcome": "ACCEPT",
            "reason": "Stock and capacity confirmed with the store.",
        },
    )
    assert recorded.status_code == 200, recorded.text
    body = recorded.json()
    assert body["engine_outcome"] == "ACCEPT"
    assert body["final_outcome"] == "ACCEPT"
    assert body["override"] is False
    assert body["reason"] == "Stock and capacity confirmed with the store."
    assert body["reviewer"] and body["recorded_at"] and body["id"]

    again = owner.get(f"{ROUTE}/orders/O1?workspace_id={ws}&cutoff={CUTOFF}").json()
    assert [r["id"] for r in again["records"]] == [body["id"]]


def test_recording_an_override_needs_a_reason_and_is_marked() -> None:
    owner, _ = client_for("owner")
    ws = owner_workspace(owner)
    seed_world(ws)
    url = f"{ROUTE}/orders/O1/records?workspace_id={ws}"
    base = {"cutoff": "2026-03-02T09:00:00Z", "policy_digest": DEFAULT_DIGEST, "final_outcome": "DECLINE"}
    refused = owner.post(url, json={**base, "reason": "  "})
    assert refused.status_code == 422
    assert refused.json()["code"] == "OVERRIDE_REASON_REQUIRED"
    overridden = owner.post(url, json={**base, "reason": "Buyer wants a price we cannot meet."})
    assert overridden.status_code == 200, overridden.text
    assert overridden.json()["override"] is True
    assert overridden.json()["engine_outcome"] == "ACCEPT"


def test_recording_for_an_unknown_order_or_policy_is_not_found() -> None:
    owner, _ = client_for("owner")
    ws = owner_workspace(owner)
    seed_world(ws)
    base = {"cutoff": "2026-03-02T09:00:00Z", "policy_digest": DEFAULT_DIGEST, "final_outcome": "ACCEPT", "reason": "x"}
    assert owner.post(f"{ROUTE}/orders/NOPE/records?workspace_id={ws}", json=base).status_code == 404
    unknown_policy = owner.post(f"{ROUTE}/orders/O1/records?workspace_id={ws}", json={**base, "policy_digest": "sha256:" + "f" * 64})
    assert unknown_policy.status_code == 404
    assert unknown_policy.json()["code"] == "POLICY_UNKNOWN"


def test_decision_view_without_a_cutoff_uses_the_latest_settled_time() -> None:
    owner, _ = client_for("owner")
    ws = owner_workspace(owner)
    seed_world(ws)
    response = owner.get(f"{ROUTE}/orders/O1?workspace_id={ws}")
    assert response.status_code == 200, response.text
    view = response.json()
    assert view["settled"] is True
    assert datetime.fromisoformat(view["cutoff"].replace("Z", "+00:00")) > KNOWN_AT
    # Months after the exports, their freshness windows have lapsed.
    assert view["gate"]["state"] == "STALE"


def test_decision_view_with_an_unknown_order_or_policy_is_not_found() -> None:
    owner, _ = client_for("owner")
    ws = owner_workspace(owner)
    seed_world(ws)
    assert owner.get(f"{ROUTE}/orders/NOPE?workspace_id={ws}&cutoff={CUTOFF}").status_code == 404
    bad = owner.get(f"{ROUTE}/orders/O1?workspace_id={ws}&cutoff={CUTOFF}&policy=sha256:{'f' * 64}")
    assert bad.status_code == 404
    assert bad.json()["code"] == "POLICY_UNKNOWN"


def test_timeline_lists_what_became_known_and_when() -> None:
    owner, _ = client_for("owner")
    ws = owner_workspace(owner)
    seed_world(ws)
    timeline = owner.get(f"{ROUTE}/orders/O1/timeline?workspace_id={ws}")
    assert timeline.status_code == 200, timeline.text
    body = timeline.json()
    assert body["knowledge_times"] == sorted(set(body["knowledge_times"]))
    assert KNOWN_AT.strftime("%Y-%m-%dT%H:%M:%S") in body["knowledge_times"][0]
    ids = {event["fact_id"] for event in body["events"]}
    assert "w-order" in ids
    first = body["events"][0]
    assert set(first) == {"known_at", "fact_id", "kind", "entity_key", "source", "summary"}
    assert first["summary"]
    times = [event["known_at"] for event in body["events"]]
    assert times == sorted(times)
    assert owner.get(f"{ROUTE}/orders/NOPE/timeline?workspace_id={ws}").status_code == 404


def test_policy_list_always_offers_the_default_and_names_the_adopted_one() -> None:
    owner, _ = client_for("owner")
    ws = owner_workspace(owner)
    listed = owner.get(f"{ROUTE}/policies?workspace_id={ws}").json()
    assert listed["adopted"] == DEFAULT_DIGEST
    assert [item["policy_digest"] for item in listed["items"]] == [DEFAULT_DIGEST]

    seed_world(ws)
    add_suite(ws)
    candidate = candidate_policy()
    run = owner.post(
        f"{ROUTE}/regression-runs?workspace_id={ws}",
        json={"baseline": DEFAULT_POLICY_V1.model_dump(mode="json"), "candidate": candidate.model_dump(mode="json")},
    ).json()
    after_run = owner.get(f"{ROUTE}/policies?workspace_id={ws}").json()
    assert after_run["adopted"] == DEFAULT_DIGEST
    assert {item["policy_digest"] for item in after_run["items"]} == {DEFAULT_DIGEST, policy_digest(candidate)}

    case_id = run["cases"][0]["case_id"]
    adopted = owner.post(
        f"{ROUTE}/regression-runs/{run['id']}/adopt?workspace_id={ws}",
        json={"acknowledgements": {case_id: "The candidate drops a constraint on purpose."}},
    )
    assert adopted.status_code == 200, adopted.text
    assert owner.get(f"{ROUTE}/policies?workspace_id={ws}").json()["adopted"] == policy_digest(candidate)


def test_regression_run_views_name_each_case_and_the_engine_version() -> None:
    owner, _ = client_for("owner")
    ws = owner_workspace(owner)
    seed_world(ws)
    case_id = add_suite(ws)
    candidate = candidate_policy()
    run = owner.post(
        f"{ROUTE}/regression-runs?workspace_id={ws}",
        json={"baseline": DEFAULT_POLICY_V1.model_dump(mode="json"), "candidate": candidate.model_dump(mode="json")},
    ).json()
    assert run["engine_version"] == DEFAULT_POLICY_V1.engine_version
    assert [(c["case_id"], c["title"]) for c in run["cases"]] == [(case_id, "ready case")]

    listed = owner.get(
        f"{ROUTE}/regression-runs?workspace_id={ws}&candidate={policy_digest(candidate)}"
    ).json()
    assert [item["id"] for item in listed["items"]] == [run["id"]]
    other = owner.get(f"{ROUTE}/regression-runs?workspace_id={ws}&candidate=sha256:{'e' * 64}").json()
    assert other["items"] == []


def test_stored_coverage_lets_a_known_zero_colour_through_the_gate() -> None:
    """A colour with no lot is a known zero only when a stock export declared the quality covered."""
    owner, _ = client_for("owner")
    ws = owner_workspace(owner)
    world = ready_world().without(entity_key="lot:LOT-W1")
    declared = {"profile": "erp_fabric_stock", "as_of": AS_OF.isoformat(), "qualities": ["SJ180"]}
    with session_scope() as session:
        session.add(
            DecisionSourceArtifact(
                id=ERP_ARTIFACT,
                workspace_id=ws,
                profile="erp_fabric_stock",
                filename="stock.csv",
                raw_bytes=b"lot,qty\nL1,10\n",
                raw_digest="sha256:" + "0" * 64,
                as_of=AS_OF,
                known_at=KNOWN_AT,
                coverage=declared,
                idempotency_key=uid(),
                preview_digest="sha256:" + "1" * 64,
            )
        )
        service.append_facts(session, world.facts, workspace_id=ws, trusted_known_at=KNOWN_AT)

    view = owner.get(f"{ROUTE}/orders/O1?workspace_id={ws}&cutoff={CUTOFF}").json()
    assert view["gate"]["state"] == "READY"
    assert view["gate"]["coverage_used"]["artifact_id"] == ERP_ARTIFACT
    white = [c for c in view["constraints"] if c["constraint"] == "FABRIC" and "WHITE" in c["subject"]]
    assert white and white[0]["status"] == "FAIL"

    # The stored evaluation replays to the same digest, so coverage is part of reconstruction.
    evaluation = owner.post(f"{ROUTE}/evaluate?workspace_id={ws}", json=evaluate_body()).json()
    detail = owner.get(f"{ROUTE}/evaluations/{evaluation['id']}?workspace_id={ws}").json()
    assert detail["reconstruction"]["matches"] is True
    assert evaluation["decision_digest"] == view["decision_digest"]


def test_coverage_not_yet_known_at_the_cutoff_is_not_used() -> None:
    owner, _ = client_for("owner")
    ws = owner_workspace(owner)
    world = ready_world().without(entity_key="lot:LOT-W1")
    declared = {"profile": "erp_fabric_stock", "as_of": AS_OF.isoformat(), "qualities": ["SJ180"]}
    with session_scope() as session:
        session.add(
            DecisionSourceArtifact(
                id=ERP_ARTIFACT,
                workspace_id=ws,
                profile="erp_fabric_stock",
                filename="stock.csv",
                raw_bytes=b"x",
                raw_digest="sha256:" + "0" * 64,
                as_of=AS_OF,
                known_at=datetime(2026, 3, 2, 12, 0, tzinfo=UTC),  # learned after the cutoff
                coverage=declared,
                idempotency_key=uid(),
                preview_digest="sha256:" + "1" * 64,
            )
        )
        service.append_facts(session, world.facts, workspace_id=ws, trusted_known_at=KNOWN_AT)
    view = owner.get(f"{ROUTE}/orders/O1?workspace_id={ws}&cutoff={CUTOFF}").json()
    assert view["gate"]["state"] == "INCOMPLETE"
    assert view["gate"]["coverage_used"] is None


def test_the_public_demo_workspace_is_readable_without_signing_in() -> None:
    anonymous = TestClient(app)
    listed = anonymous.get(f"{ROUTE}/orders?workspace_id=public-demo")
    assert listed.status_code == 200, listed.text
    assert "items" in listed.json()
    assert anonymous.get(f"{ROUTE}/policies?workspace_id=public-demo").status_code == 200
    assert anonymous.get(f"{ROUTE}/regression-runs?workspace_id=public-demo").status_code == 200
    assert anonymous.get(f"{ROUTE}/snapshot?workspace_id=public-demo&cutoff={CUTOFF}").status_code == 200


def test_anonymous_callers_cannot_read_private_workspaces_or_write_anywhere() -> None:
    owner, _ = client_for("owner")
    ws = owner_workspace(owner)
    seed_world(ws)
    anonymous = TestClient(app)
    for path in (f"/orders?workspace_id={ws}", f"/orders/O1?workspace_id={ws}&cutoff={CUTOFF}", f"/orders/O1/timeline?workspace_id={ws}"):
        denied = anonymous.get(ROUTE + path)
        assert denied.status_code == 401, path
        assert denied.json()["code"] == "SIGN_IN_REQUIRED"
    body = {"cutoff": "2026-03-02T09:00:00Z", "policy_digest": DEFAULT_DIGEST, "final_outcome": "ACCEPT", "reason": "x"}
    for workspace in (ws, "public-demo"):
        write = anonymous.post(f"{ROUTE}/orders/O1/records?workspace_id={workspace}", json=body)
        assert write.status_code == 401, workspace
    # A signed-in caller cannot write to the demo workspace either.
    assert owner.post(f"{ROUTE}/orders/O1/records?workspace_id=public-demo", json=body).status_code == 404


def test_order_summaries_only_list_orders_with_an_order_request() -> None:
    owner, _ = client_for("owner")
    ws = owner_workspace(owner)
    with session_scope() as session:
        assert service.list_order_ids(session, ws) == []
    assert owner.get(f"{ROUTE}/orders?workspace_id={ws}").json() == {"items": []}
    assert FactKind.ORDER_REQUEST.value == "order_request"


def load_demo(workspace: str) -> None:
    """What the `decisions-demo` command does: seeding authors known_at, so it never runs over HTTP."""
    from flooreplay.decisions import demo

    with session_scope() as session:
        demo.seed_demo(session, workspace)


def test_a_private_workspace_loaded_with_the_demo_supports_the_whole_write_path() -> None:
    from flooreplay.decisions import demo

    owner, _ = client_for("owner")
    ws = owner_workspace(owner)
    load_demo(ws)
    with session_scope() as session:
        assert set(demo.seed_demo(session, ws).values()) == {0}

    orders = {o["order_id"]: o for o in owner.get(f"{ROUTE}/orders?workspace_id={ws}").json()["items"]}
    assert orders["POLO-221"]["latest"]["outcome"] == "ACCEPT"
    recorded = owner.post(
        f"{ROUTE}/orders/POLO-221/records?workspace_id={ws}",
        json={
            "cutoff": orders["POLO-221"]["latest"]["cutoff"],
            "policy_digest": DEFAULT_DIGEST,
            "final_outcome": "ACCEPT",
            "reason": "QA resolved the stock conflict.",
        },
    )
    assert recorded.status_code == 200, recorded.text
    policies = owner.get(f"{ROUTE}/policies?workspace_id={ws}").json()
    candidate = next(p for p in policies["items"] if p["policy_digest"] != policies["adopted"])
    run = owner.get(f"{ROUTE}/regression-runs?workspace_id={ws}&candidate={candidate['policy_digest']}").json()["items"][0]
    adopted = owner.post(
        f"{ROUTE}/regression-runs/{run['id']}/adopt?workspace_id={ws}",
        json={"acknowledgements": {"case-03-overtime-covers": "Overtime cap of one hour is acceptable."}},
    )
    assert adopted.status_code == 200, adopted.text
    assert owner.get(f"{ROUTE}/policies?workspace_id={ws}").json()["adopted"] == candidate["policy_digest"]
