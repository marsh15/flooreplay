"""The assigned-check lifecycle runs against a real isolated PostgreSQL database."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from flooreplay.api import app
from flooreplay.auth import Account, create_account, sign_in
from flooreplay.db import session_scope
from flooreplay.domain.hashing import incident_digest
from flooreplay.incident_engine import incident_evidence_card
from flooreplay.incident_fixtures import incident_fixtures
from flooreplay.incident_workflow import (
    IncidentCheck,
    IncidentResolution,
    WorkflowActivity,
    WorkflowReceipt,
)
from flooreplay.models import IncidentAnalysis, IncidentRevision, IncidentSourceArtifact

pytestmark = pytest.mark.skipif(
    os.environ.get("FLOORREPLAY_SKIP_DB") == "1", reason="database not available"
)


def key():
    return uuid4().hex


@pytest.fixture
def case(owner_headers, reviewer_headers):
    incident_id = f"WF-{uuid4().hex}"
    workspace_id = TestClient(app, headers=owner_headers).get("/api/v1/workspaces").json()["items"][0]["id"]
    fixture = deepcopy(
        next(
            item
            for item in incident_fixtures()
            if item["id"] == "INC-001" and item["revision"] == 2
        )
    )
    fixture.update(id=incident_id, revision=1)
    with session_scope() as session:
        session.add(
            IncidentRevision(
                workspace_id=workspace_id,
                incident_id=incident_id,
                revision=1,
                title=fixture["title"],
                line_id=fixture["scope"]["line_id"],
                cutoff=datetime.fromisoformat(fixture["cutoff"]),
                window_start=datetime.fromisoformat(fixture["window"]["start"]),
                window_end=datetime.fromisoformat(fixture["window"]["end"]),
                payload=fixture,
                content_digest=incident_digest(fixture),
                evidence_card=incident_evidence_card(fixture),
            )
        )
    owner = TestClient(app, headers=owner_headers)
    reviewer = TestClient(app, headers=reviewer_headers)
    assigned = create_account(
        "assigned-" + key(), "test-password-long-enough", "reviewer", "Named maintenance reviewer"
    )
    owner.post(f"/api/v1/workspaces/{workspace_id}/members", json={"account_id": reviewer.get("/api/v1/auth/me").json()["id"]})
    owner.post(f"/api/v1/workspaces/{workspace_id}/members", json={"account_id": assigned["id"]})
    assigned_headers = {
        "Authorization": "Bearer "
        + sign_in(assigned["username"], "test-password-long-enough", assigned["username"])["token"]
    }
    analysis = owner.post(
        f"/api/v1/incidents/{incident_id}/analyses", json={"revision": 1, "idempotency_key": key()}
    ).json()
    body = {
        "proposal_id": "verify-machine",
        "assignee_id": assigned["id"],
        "due_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        "idempotency_key": key(),
    }
    response = owner.post(f"/api/v1/analyses/{analysis['id']}/checks", json=body)
    assert response.status_code == 200, response.text
    task = response.json()
    yield {
        "id": incident_id,
        "owner": owner,
        "reviewer": reviewer,
        "assigned": TestClient(app, headers=assigned_headers),
        "account": assigned,
        "fixture": fixture,
        "analysis": analysis,
        "create": body,
        "task": task,
    }
    with session_scope() as session:
        ids = session.scalars(
            select(IncidentCheck.id).where(IncidentCheck.incident_id == incident_id)
        ).all()
        session.execute(delete(WorkflowActivity).where(WorkflowActivity.incident_id == incident_id))
        session.execute(
            delete(IncidentResolution).where(IncidentResolution.incident_id == incident_id)
        )
        session.execute(
            delete(WorkflowReceipt).where(
                WorkflowReceipt.operation.like(f"%{incident_id}%")
                | WorkflowReceipt.operation.in_(
                    [
                        f"{kind}:{task_id}"
                        for task_id in ids
                        for kind in ("update", "respond", "complete")
                    ]
                    + [f"create:{analysis['id']}"]
                )
            )
        )
        session.execute(delete(IncidentCheck).where(IncidentCheck.incident_id == incident_id))
        session.execute(delete(IncidentAnalysis).where(IncidentAnalysis.incident_id == incident_id))
        session.execute(
            delete(IncidentSourceArtifact).where(IncidentSourceArtifact.incident_id == incident_id)
        )
        session.execute(delete(IncidentRevision).where(IncidentRevision.incident_id == incident_id))


def response_body(case):
    return {
        "base_revision": 1,
        "summary": "Maintenance confirms a station repair; the effect on good output remains unknown.",
        "occurred_at": case["fixture"]["window"]["start"],
        "source_ref": "Maintenance ticket MT-123",
        "details": {
            field: "Recorded observation; further verification remains open"
            for field in case["task"]["requested_fields"]
        },
        "line_blocking": False,
        "start": None,
        "end": None,
        "idempotency_key": key(),
    }


def outcome_body():
    return {
        "action_taken": "Reviewed the source response and confirmed the repair handoff.",
        "actual_completed_at": datetime.now(UTC).isoformat(),
        "observed_good_units": None,
        "observed_at": None,
        "assessment": "Check answered; causal production improvement has not been measured.",
        "remaining_uncertainty": "No post-action comparable production interval available.",
        "idempotency_key": key(),
    }


def test_complete_lifecycle_pins_evidence_replay_and_resolution(case):
    owner, assigned, task = case["owner"], case["assigned"], case["task"]
    url = f"/api/v1/checks/{task['id']}"
    assert (
        owner.post(f"/api/v1/analyses/{case['analysis']['id']}/checks", json=case["create"]).json()
        == task
    )
    duplicate = owner.post(
        f"/api/v1/analyses/{case['analysis']['id']}/checks",
        json={**case["create"], "idempotency_key": key()},
    )
    assert duplicate.status_code == 409 and duplicate.json()["code"] == "CHECK_ALREADY_ASSIGNED"
    assert (
        owner.post(
            f"/api/v1/incidents/{case['id']}/resolution",
            json={
                "base_revision": 1,
                "state": "RESOLVED",
                "rationale": "Attempt early resolution",
                "idempotency_key": key(),
            },
        ).status_code
        == 409
    )
    started = assigned.post(
        url + "/update",
        json={
            "status": "IN_PROGRESS",
            "comment": "Maintenance check started",
            "expected_updated_at": task["updated_at"],
            "idempotency_key": key(),
        },
    )
    assert started.status_code == 200 and started.json()["status"] == "IN_PROGRESS"
    response = response_body(case)
    answered = assigned.post(url + "/respond", json=response)
    assert answered.status_code == 200, answered.text
    assert answered.json()["status"] == "ANSWERED" and answered.json()["response"]["revision"] == 2
    assert assigned.post(url + "/respond", json=response).json() == answered.json()
    assert (
        assigned.post(
            url + "/respond", json={**response, "summary": "Different observation"}
        ).status_code
        == 409
    )
    assert (
        owner.get(f"/api/v1/incidents/{case['id']}/revisions/1").json()["events"]
        == case["fixture"]["events"]
    )
    new_analysis = owner.post(
        f"/api/v1/incidents/{case['id']}/analyses", json={"revision": 2, "idempotency_key": key()}
    ).json()
    assert new_analysis["metrics"]["shortfall"] == case["analysis"]["metrics"]["shortfall"]
    evidence_id = answered.json()["response"]["evidence_id"]
    assert (
        owner.get(f"/api/v1/analyses/{case['analysis']['id']}/evidence/{evidence_id}").status_code
        == 404
    )
    evidence = (
        owner.get(f"/api/v1/analyses/{new_analysis['id']}/evidence/{evidence_id}").json()
    )
    assert evidence["record"]["assertion"] is True and evidence["record"]["line_blocking"] is False
    assert evidence["record"]["details"] == response["details"]
    assert evidence["source_artifact"]["profile"] == "workflow-v1"
    assert evidence["source_artifact"]["id"] == evidence["record"]["source_artifact_id"]
    assert set(evidence["source_artifact"]) == {
        "id",
        "raw_digest",
        "profile",
        "source_system",
        "filename",
    }
    with session_scope() as session:
        artifact = session.get(IncidentSourceArtifact, evidence["source_artifact"]["id"])
        assert json.loads(artifact.raw_bytes)["details"] == response["details"]
    complete = assigned.post(url + "/complete", json=outcome_body())
    assert complete.status_code == 200 and complete.json()["status"] == "COMPLETED"
    workflow = owner.get(f"/api/v1/incidents/{case['id']}/workflow").json()
    assert workflow["resolution"] == "OPEN" and not workflow["handover"]["outstanding_checks"]
    resolution_body = {
        "base_revision": 2,
        "state": "RESOLVED",
        "rationale": "All checks closed; remaining uncertainty recorded",
        "idempotency_key": key(),
    }
    resolved = owner.post(f"/api/v1/incidents/{case['id']}/resolution", json=resolution_body)
    assert resolved.status_code == 200 and resolved.json()["resolution"] == "RESOLVED"
    assert resolved.json()["resolution_activities"][-1]["kind"] == "RESOLVED"
    assert (
        owner.post(f"/api/v1/incidents/{case['id']}/resolution", json=resolution_body).json()
        == resolved.json()
    )
    assert (
        owner.post(
            f"/api/v1/analyses/{new_analysis['id']}/checks",
            json={**case["create"], "idempotency_key": key()},
        ).status_code
        == 409
    )
    reopened = owner.post(
        f"/api/v1/incidents/{case['id']}/resolution",
        json={
            "base_revision": 2,
            "state": "OPEN",
            "rationale": "Another verification is needed",
            "idempotency_key": key(),
        },
    )
    assert reopened.status_code == 200 and reopened.json()["resolution"] == "OPEN"
    assert [item["kind"] for item in reopened.json()["resolution_activities"]] == [
        "RESOLVED",
        "OPEN",
    ]
    assert assigned.post(url + "/respond", json=response).json() == answered.json()


def test_permissions_version_and_structured_validation(case):
    owner, reviewer, assigned, task = (
        case["owner"],
        case["reviewer"],
        case["assigned"],
        case["task"],
    )
    url = f"/api/v1/checks/{task['id']}"
    public = TestClient(app)
    assert public.get(f"/api/v1/incidents/{case['id']}/workflow").status_code == 401
    assert public.get("/api/v1/workflow/assignees").status_code == 401
    assert public.post(url + "/respond", json={}).status_code == 401
    assert any(
        item["id"] == case["account"]["id"]
        for item in owner.get("/api/v1/workflow/assignees").json()["items"]
    )
    update = {
        "status": "IN_PROGRESS",
        "comment": "Starting this check",
        "expected_updated_at": task["updated_at"],
        "idempotency_key": key(),
    }
    assert reviewer.post(url + "/update", json=update).status_code == 403
    assert reviewer.post(url + "/update", json={**update, "status": "CANCELLED"}).status_code == 403
    assert reviewer.post(url + "/respond", json=response_body(case)).status_code == 403
    assert assigned.post(url + "/complete", json=outcome_body()).status_code == 409
    comment = reviewer.post(url + "/update", json={**update, "status": None})
    assert (
        comment.status_code == 200
        and comment.json()["activities"][-1]["actor"] != task["created_by"]
    )
    assert (
        owner.post(url + "/update", json={**update, "idempotency_key": key()}).json()["code"]
        == "STALE_CHECK"
    )
    response = response_body(case)
    assert assigned.post(url + "/respond", json={**response, "details": {}}).status_code == 422
    assert (
        assigned.post(
            url + "/respond", json={**response, "occurred_at": datetime.now(UTC).isoformat()}
        ).status_code
        == 422
    )
    assert (
        assigned.post(url + "/respond", json={**response, "line_blocking": True}).status_code == 422
    )
    assert (
        assigned.post(url + "/respond", json={**response, "line_blocking": "true"}).status_code
        == 422
    )
    block = {
        **response,
        "line_blocking": True,
        "start": case["fixture"]["window"]["start"],
        "end": (
            datetime.fromisoformat(case["fixture"]["window"]["start"]) + timedelta(minutes=15)
        ).isoformat(),
    }
    answered = assigned.post(url + "/respond", json=block)
    assert answered.status_code == 200, answered.text
    latest = owner.get(f"/api/v1/incidents/{case['id']}/revisions/2").json()
    event = latest["events"][-1]
    assert event["type"] == "line_block" and event["linked_categories"] == ["machine"]
    stale_analysis = owner.post(
        f"/api/v1/analyses/{case['analysis']['id']}/checks",
        json={**case["create"], "idempotency_key": key()},
    )
    assert stale_analysis.status_code == 409 and stale_analysis.json()["code"] == "STALE_ANALYSIS"
    complete = outcome_body()
    assert (
        assigned.post(url + "/complete", json={**complete, "observed_good_units": 2}).status_code
        == 422
    )
    assert (
        assigned.post(
            url + "/complete",
            json={**complete, "actual_completed_at": case["fixture"]["window"]["start"]},
        ).status_code
        == 422
    )
    assert (
        assigned.post(
            url + "/complete",
            json={
                **complete,
                "observed_good_units": True,
                "observed_at": datetime.now(UTC).isoformat(),
            },
        ).status_code
        == 422
    )
    assert assigned.post(url + "/complete", json=complete).status_code == 200
    assert assigned.post(url + "/complete", json=complete).status_code == 200
    with session_scope() as session:
        account = session.get(Account, case["account"]["id"])
        account.disabled = True
    assert not any(
        item["id"] == case["account"]["id"]
        for item in owner.get("/api/v1/workflow/assignees").json()["items"]
    )


def test_reassignment_cancellation_and_duplicate_concurrency(case):
    from concurrent.futures import ThreadPoolExecutor

    owner, task = case["owner"], case["task"]
    url = f"/api/v1/checks/{task['id']}"
    body = {
        "comment": "Escalate to the owner for source reconciliation",
        "assignee_id": task["created_by"],
        "due_at": (datetime.now(UTC) + timedelta(days=2)).isoformat(),
        "status": None,
        "expected_updated_at": task["updated_at"],
        "idempotency_key": key(),
    }
    assert case["assigned"].post(url + "/update", json=body).status_code == 403
    updated = owner.post(url + "/update", json=body)
    assert updated.status_code == 200 and updated.json()["assignee_id"] == task["created_by"]
    assert owner.post(url + "/update", json=body).json() == updated.json()
    assert case["assigned"].post(url + "/respond", json=response_body(case)).status_code == 403
    cancelled = owner.post(
        url + "/update",
        json={
            "status": "CANCELLED",
            "comment": "Source cannot be independently verified",
            "expected_updated_at": updated.json()["updated_at"],
            "idempotency_key": key(),
        },
    )
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "CANCELLED"
    assert owner.post(url + "/respond", json=response_body(case)).status_code == 409
    creations = [{**case["create"], "idempotency_key": key()} for _ in range(2)]
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(
            workers.map(
                lambda body: TestClient(app, headers=owner.headers).post(
                    f"/api/v1/analyses/{case['analysis']['id']}/checks", json=body
                ),
                creations,
            )
        )
    assert sorted(result.status_code for result in results) == [200, 409]
    conflict = next(result for result in results if result.status_code == 409)
    assert conflict.json()["code"] == "CHECK_ALREADY_ASSIGNED"
    with session_scope() as session:
        account = session.get(Account, case["account"]["id"])
        account.disabled = True
    active = next(result.json() for result in results if result.status_code == 200)
    disabled_assignment = owner.post(
        f"/api/v1/checks/{active['id']}/update",
        json={
            **body,
            "assignee_id": case["account"]["id"],
            "expected_updated_at": active["updated_at"],
            "idempotency_key": key(),
        },
    )
    assert disabled_assignment.status_code == 422


def test_resolution_invalidated_by_new_revision_without_erasing_audit(case):
    owner, task = case["owner"], case["task"]
    url = f"/api/v1/checks/{task['id']}"
    assert case["assigned"].post(url + "/respond", json=response_body(case)).status_code == 200
    assert case["assigned"].post(url + "/complete", json=outcome_body()).status_code == 200
    resolution_body = {
        "base_revision": 2,
        "state": "RESOLVED",
        "rationale": "Source check complete, known limitations retained",
        "idempotency_key": key(),
    }
    resolved = owner.post(f"/api/v1/incidents/{case['id']}/resolution", json=resolution_body)
    assert resolved.status_code == 200
    with session_scope() as session:
        base = session.get(IncidentRevision, (case["id"], 2))
        payload = {
            **base.payload,
            "revision": 3,
            "cutoff": (base.cutoff + timedelta(seconds=1)).isoformat(),
        }
        session.add(
            IncidentRevision(
                incident_id=case["id"],
                revision=3,
                title=base.title,
                line_id=base.line_id,
                cutoff=base.cutoff + timedelta(seconds=1),
                window_start=base.window_start,
                window_end=base.window_end,
                payload=payload,
                content_digest=incident_digest(payload),
                evidence_card=incident_evidence_card(payload),
            )
        )
    changed = owner.get(f"/api/v1/incidents/{case['id']}/workflow").json()
    assert changed["resolution"] == "OPEN" and changed["resolved_revision"] == 2
    assert changed["resolution_activities"] == resolved.json()["resolution_activities"]
    assert changed["handover"]["completed_checks"][0]["outcome"]
    assert (
        owner.post(
            f"/api/v1/incidents/{case['id']}/resolution",
            json={**resolution_body, "idempotency_key": key()},
        ).json()["code"]
        == "STALE_REVISION"
    )
    assert (
        owner.post(f"/api/v1/incidents/{case['id']}/resolution", json=resolution_body).json()
        == resolved.json()
    )


def test_concurrent_responses_append_one_revision_and_replay_original_receipt(case):
    from concurrent.futures import ThreadPoolExecutor

    owner = case["owner"]
    other = owner.post(
        f"/api/v1/analyses/{case['analysis']['id']}/checks",
        json={**case["create"], "proposal_id": "verify-material", "idempotency_key": key()},
    )
    assert other.status_code == 200
    requests = []
    for task in (case["task"], other.json()):
        body = {
            **response_body(case),
            "details": {
                field: "Recorded observation with unknown causal effect"
                for field in task["requested_fields"]
            },
            "idempotency_key": key(),
        }
        requests.append((task["id"], body))

    def respond(item):
        task_id, body = item
        return TestClient(app, headers=owner.headers).post(
            f"/api/v1/checks/{task_id}/respond", json=body
        )

    with ThreadPoolExecutor(max_workers=2) as workers:
        responses = list(workers.map(respond, requests))
    assert sorted(response.status_code for response in responses) == [200, 409]
    assert (
        next(response for response in responses if response.status_code == 409).json()["code"]
        == "STALE_REVISION"
    )
    successful = next(
        index for index, response in enumerate(responses) if response.status_code == 200
    )
    task_id, body = requests[successful]
    assert (
        owner.post(f"/api/v1/checks/{task_id}/respond", json=body).json()
        == responses[successful].json()
    )
    failed = 1 - successful
    other_task_id, other_body = requests[failed]
    assert (
        owner.post(
            f"/api/v1/checks/{other_task_id}/respond", json={**other_body, "base_revision": 2}
        ).status_code
        == 200
    )
    latest = owner.get(f"/api/v1/incidents/{case['id']}/workflow").json()
    assert latest["current_revision"] == 3
    assert (
        owner.post(f"/api/v1/checks/{task_id}/respond", json=body).json()
        == responses[successful].json()
    )
