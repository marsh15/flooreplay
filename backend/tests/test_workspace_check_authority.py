"""Assigned-check authority follows the workspace's own membership, not the global account role."""

from __future__ import annotations

import os
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, or_, select

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
    create_check,
    task_authority,
)
from flooreplay.models import IncidentAnalysis, IncidentRevision, IncidentSourceArtifact
from flooreplay.workspaces import DEMO, WorkspaceMember

pytestmark = pytest.mark.skipif(
    os.environ.get("FLOORREPLAY_SKIP_DB") == "1", reason="database not available"
)

PASSWORD = "test-password-long-enough"
FIXTURE = next(
    item for item in incident_fixtures() if item["id"] == "INC-001" and item["revision"] == 2
)


def key() -> str:
    return uuid4().hex


def due(days: int) -> str:
    return (datetime.now(UTC) + timedelta(days=days)).isoformat()


def client_for(global_role: str) -> tuple[TestClient, dict]:
    name = f"authority-{global_role}-{key()[:12]}"
    account = create_account(name, PASSWORD, global_role)
    token = sign_in(name, PASSWORD, name)["token"]
    return TestClient(app, headers={"Authorization": "Bearer " + token}), account


@pytest.fixture
def incidents():
    """Remove every incident, check, receipt and analysis a test created."""
    created: list[str] = []
    yield created
    with session_scope() as session:
        for incident_id in created:
            check_ids = session.scalars(
                select(IncidentCheck.id).where(IncidentCheck.incident_id == incident_id)
            ).all()
            analysis_ids = session.scalars(
                select(IncidentAnalysis.id).where(IncidentAnalysis.incident_id == incident_id)
            ).all()
            session.execute(
                delete(WorkflowActivity).where(WorkflowActivity.incident_id == incident_id)
            )
            if check_ids or analysis_ids:
                session.execute(
                    delete(WorkflowReceipt).where(
                        or_(
                            *[
                                WorkflowReceipt.operation.contains(value)
                                for value in [*check_ids, *analysis_ids]
                            ]
                        )
                    )
                )
            session.execute(delete(IncidentCheck).where(IncidentCheck.incident_id == incident_id))
            session.execute(
                delete(IncidentResolution).where(IncidentResolution.incident_id == incident_id)
            )
            session.execute(
                delete(IncidentAnalysis).where(IncidentAnalysis.incident_id == incident_id)
            )
            session.execute(
                delete(IncidentSourceArtifact).where(
                    IncidentSourceArtifact.incident_id == incident_id
                )
            )
            session.execute(
                delete(IncidentRevision).where(IncidentRevision.incident_id == incident_id)
            )


def analysed_incident(
    owner: TestClient, workspace_id: str, incidents: list[str]
) -> tuple[str, str]:
    incident_id = f"AUTHORITY-{key()}"
    payload = deepcopy(FIXTURE)
    payload.update(id=incident_id, revision=1)
    with session_scope() as session:
        session.add(
            IncidentRevision(
                workspace_id=workspace_id,
                incident_id=incident_id,
                revision=1,
                title=payload["title"],
                line_id=payload["scope"]["line_id"],
                cutoff=datetime.fromisoformat(payload["cutoff"]),
                window_start=datetime.fromisoformat(payload["window"]["start"]),
                window_end=datetime.fromisoformat(payload["window"]["end"]),
                payload=payload,
                content_digest=incident_digest(payload),
                evidence_card=incident_evidence_card(payload),
            )
        )
    incidents.append(incident_id)
    analysis = owner.post(
        f"/api/v1/incidents/{incident_id}/analyses", json={"revision": 1, "idempotency_key": key()}
    )
    assert analysis.status_code == 200, analysis.text
    return incident_id, analysis.json()["id"]


def invite(owner: TestClient, workspace_id: str, global_role: str) -> tuple[TestClient, str]:
    member, account = client_for(global_role)
    added = owner.post(
        f"/api/v1/workspaces/{workspace_id}/members", json={"account_id": account["id"]}
    )
    assert added.status_code == 200, added.text
    return member, account["id"]


def private_case(incidents: list[str]) -> SimpleNamespace:
    """A private workspace: one workspace owner, a global owner who is only a member, an assignee and a creator."""
    owner, owner_account = client_for("owner")
    created = owner.post("/api/v1/workspaces", json={"name": "Authority " + key()[:8]})
    assert created.status_code == 200, created.text
    workspace_id = created.json()["id"]
    global_owner, global_owner_id = invite(owner, workspace_id, "owner")
    assignee, assignee_id = invite(owner, workspace_id, "reviewer")
    creator, creator_id = invite(owner, workspace_id, "reviewer")
    incident_id, analysis_id = analysed_incident(owner, workspace_id, incidents)
    return SimpleNamespace(
        owner=owner,
        owner_id=owner_account["id"],
        workspace_id=workspace_id,
        global_owner=global_owner,
        global_owner_id=global_owner_id,
        assignee=assignee,
        assignee_id=assignee_id,
        creator=creator,
        creator_id=creator_id,
        incident_id=incident_id,
        analysis_id=analysis_id,
    )


def assign(client: TestClient, analysis_id: str, proposal: str, assignee_id: str) -> dict:
    response = client.post(
        f"/api/v1/analyses/{analysis_id}/checks",
        json={
            "proposal_id": proposal,
            "assignee_id": assignee_id,
            "due_at": due(1),
            "idempotency_key": key(),
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def workflow_task(client: TestClient, incident_id: str, task_id: str) -> dict:
    response = client.get(f"/api/v1/incidents/{incident_id}/workflow")
    assert response.status_code == 200, response.text
    workflow = response.json()
    by_id = {task["id"]: task for task in workflow["tasks"]}
    for group in ("outstanding_checks", "completed_checks"):
        for task in workflow["handover"][group]:
            assert task["can_act"] == by_id[task["id"]]["can_act"]
            assert task["can_manage"] == by_id[task["id"]]["can_manage"]
    return by_id[task_id]


def authority(client: TestClient, case: SimpleNamespace, task: dict) -> tuple[bool, bool]:
    view = workflow_task(client, case.incident_id, task["id"])
    return view["can_act"], view["can_manage"]


def update(
    client: TestClient,
    task: dict,
    *,
    comment: str = "Checked against the assignment record",
    **changes,
):
    body = {
        "status": None,
        "comment": comment,
        "assignee_id": None,
        "due_at": None,
        "expected_updated_at": task["updated_at"],
        "idempotency_key": key(),
        **changes,
    }
    return client.post(f"/api/v1/checks/{task['id']}/update", json=body)


def respond(client: TestClient, task: dict):
    body = {
        "base_revision": 1,
        "summary": "Maintenance confirms a station repair; the effect on good output remains unknown.",
        "occurred_at": FIXTURE["window"]["start"],
        "source_ref": "Maintenance ticket MT-123",
        "details": {
            field: "Recorded observation; further verification remains open"
            for field in task["requested_fields"]
        },
        "line_blocking": False,
        "start": None,
        "end": None,
        "idempotency_key": key(),
    }
    return client.post(f"/api/v1/checks/{task['id']}/respond", json=body)


def complete(client: TestClient, task: dict):
    body = {
        "action_taken": "Reviewed the source response and confirmed the repair handoff.",
        "actual_completed_at": datetime.now(UTC).isoformat(),
        "observed_good_units": None,
        "observed_at": None,
        "assessment": "Check answered; causal production improvement has not been measured.",
        "remaining_uncertainty": "No post-action comparable production interval available.",
        "idempotency_key": key(),
    }
    return client.post(f"/api/v1/checks/{task['id']}/complete", json=body)


def set_membership_role(workspace_id: str, account_id: str, role: str) -> None:
    with session_scope() as session:
        session.get(WorkspaceMember, (workspace_id, account_id)).role = role


def revoke_membership(workspace_id: str, account_id: str) -> None:
    with session_scope() as session:
        session.delete(session.get(WorkspaceMember, (workspace_id, account_id)))


def test_global_owner_invited_as_member_cannot_act_on_another_members_check(incidents):
    case = private_case(incidents)
    task = assign(case.owner, case.analysis_id, "verify-machine", case.assignee_id)
    assert authority(case.global_owner, case, task) == (False, False)

    # Membership still allows comments; only the lifecycle and reassignment are gated.
    commented = update(case.global_owner, task)
    assert commented.status_code == 200, commented.text
    task = commented.json()

    # A refused request changes nothing, so the same expected_updated_at stays valid for each attempt.
    refusals = {
        "start": (update(case.global_owner, task, status="IN_PROGRESS"), "CHECK_ASSIGNEE_REQUIRED"),
        "cancel": (update(case.global_owner, task, status="CANCELLED"), "CHECK_CREATOR_REQUIRED"),
        "reassign": (
            update(case.global_owner, task, assignee_id=case.creator_id),
            "CHECK_CREATOR_REQUIRED",
        ),
        "due date": (update(case.global_owner, task, due_at=due(3)), "CHECK_CREATOR_REQUIRED"),
        "respond": (respond(case.global_owner, task), "CHECK_ASSIGNEE_REQUIRED"),
    }
    for action, (response, code) in refusals.items():
        assert response.status_code == 403, (action, response.text)
        assert response.json()["code"] == code, action

    started = update(case.assignee, task, status="IN_PROGRESS")
    assert started.status_code == 200 and started.json()["status"] == "IN_PROGRESS", started.text
    answered = respond(case.assignee, started.json())
    assert answered.status_code == 200, answered.text
    answered = answered.json()

    refused = complete(case.global_owner, answered)
    assert refused.status_code == 403 and refused.json()["code"] == "CHECK_ASSIGNEE_REQUIRED"
    refused = update(case.global_owner, answered, status="CANCELLED")
    assert refused.status_code == 403 and refused.json()["code"] == "CHECK_CREATOR_REQUIRED"

    finished = complete(case.assignee, answered)
    assert finished.status_code == 200 and finished.json()["status"] == "COMPLETED", finished.text
    assert authority(case.global_owner, case, finished.json()) == (False, False)


def test_assignee_and_creator_keep_their_rights_without_workspace_ownership(incidents):
    case = private_case(incidents)
    handed = assign(case.creator, case.analysis_id, "verify-machine", case.assignee_id)
    lifecycle = assign(case.creator, case.analysis_id, "verify-material", case.assignee_id)
    assert authority(case.creator, case, handed) == (False, True)
    assert authority(case.assignee, case, handed) == (True, False)

    # The assignee performs the step; only the creator reassigns or cancels.
    refused = update(case.assignee, handed, assignee_id=case.global_owner_id)
    assert refused.status_code == 403 and refused.json()["code"] == "CHECK_CREATOR_REQUIRED"
    moved = update(case.creator, handed, assignee_id=case.global_owner_id)
    assert moved.status_code == 200 and moved.json()["assignee_id"] == case.global_owner_id, (
        moved.text
    )
    rescheduled = update(case.creator, moved.json(), due_at=due(3))
    assert rescheduled.status_code == 200, rescheduled.text
    cancelled = update(case.creator, rescheduled.json(), status="CANCELLED")
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "CANCELLED", (
        cancelled.text
    )

    started = update(case.assignee, lifecycle, status="IN_PROGRESS")
    assert started.status_code == 200, started.text
    answered = respond(case.assignee, started.json())
    assert answered.status_code == 200, answered.text
    refused = complete(case.creator, answered.json())
    assert refused.status_code == 403 and refused.json()["code"] == "CHECK_ASSIGNEE_REQUIRED"
    finished = complete(case.assignee, answered.json())
    assert finished.status_code == 200 and finished.json()["status"] == "COMPLETED", finished.text


def test_actual_workspace_owner_keeps_override_over_any_members_check(incidents):
    case = private_case(incidents)
    handed = assign(case.creator, case.analysis_id, "verify-machine", case.assignee_id)
    cancelled = assign(case.creator, case.analysis_id, "verify-material", case.assignee_id)
    assert authority(case.owner, case, handed) == (True, True)

    moved = update(case.owner, handed, assignee_id=case.global_owner_id)
    assert moved.status_code == 200, moved.text
    started = update(case.owner, moved.json(), status="IN_PROGRESS")
    assert started.status_code == 200, started.text
    answered = respond(case.owner, started.json())
    assert answered.status_code == 200, answered.text
    finished = complete(case.owner, answered.json())
    assert finished.status_code == 200 and finished.json()["status"] == "COMPLETED", finished.text

    stopped = update(case.owner, cancelled, status="CANCELLED")
    assert stopped.status_code == 200 and stopped.json()["status"] == "CANCELLED", stopped.text
    assert finished.json()["can_act"] is True and finished.json()["can_manage"] is True
    latest = case.owner.get(f"/api/v1/incidents/{case.incident_id}/workflow").json()
    resolved = case.owner.post(
        f"/api/v1/incidents/{case.incident_id}/resolution",
        json={
            "base_revision": latest["current_revision"],
            "state": "RESOLVED",
            "rationale": "All outcomes and remaining uncertainty reviewed",
            "idempotency_key": key(),
        },
    )
    assert resolved.status_code == 200, resolved.text
    assert all(task["can_act"] and task["can_manage"] for task in resolved.json()["tasks"])
    completed = resolved.json()["handover"]["completed_checks"]
    assert completed and all(task["can_act"] and task["can_manage"] for task in completed)


def test_unscoped_check_creation_retains_parent_workspace(incidents):
    case = private_case(incidents)
    with session_scope() as session:
        creator = session.get(Account, case.creator_id)
        task = create_check(
            session,
            case.analysis_id,
            creator,
            {
                "proposal_id": "verify-machine",
                "assignee_id": case.assignee_id,
                "due_at": due(1),
                "idempotency_key": key(),
            },
        )
        assert session.get(IncidentCheck, task["id"]).workspace_id == case.workspace_id
    assert authority(case.global_owner, case, task) == (False, False)


def test_owner_membership_downgrade_and_revocation_change_authority(incidents):
    case = private_case(incidents)
    task = assign(case.creator, case.analysis_id, "verify-machine", case.assignee_id)
    other = assign(case.creator, case.analysis_id, "verify-material", case.assignee_id)

    set_membership_role(case.workspace_id, case.owner_id, "member")
    assert authority(case.owner, case, task) == (False, False)
    refused = update(case.owner, task, status="CANCELLED")
    assert refused.status_code == 403 and refused.json()["code"] == "CHECK_CREATOR_REQUIRED"

    set_membership_role(case.workspace_id, case.owner_id, "owner")
    restored = update(case.owner, task, status="CANCELLED")
    assert restored.status_code == 200, restored.text

    revoke_membership(case.workspace_id, case.owner_id)
    assert case.owner.get(f"/api/v1/incidents/{case.incident_id}/workflow").status_code == 404
    gone = update(case.owner, other, status="CANCELLED")
    assert gone.status_code == 404


def test_authority_is_never_stored_in_receipts_and_replays_recompute_it(incidents):
    case = private_case(incidents)
    task = assign(case.creator, case.analysis_id, "verify-machine", case.assignee_id)
    request_key = key()
    url = f"/api/v1/checks/{task['id']}/update"
    body = {
        "status": "CANCELLED",
        "comment": "Owner cancels after source reconciliation",
        "assignee_id": None,
        "due_at": None,
        "expected_updated_at": task["updated_at"],
        "idempotency_key": request_key,
    }
    first = case.owner.post(url, json=body)
    assert first.status_code == 200 and first.json()["can_manage"] is True, first.text

    with session_scope() as session:
        receipt = session.scalar(
            select(WorkflowReceipt).where(
                WorkflowReceipt.actor == case.owner_id, WorkflowReceipt.request_key == request_key
            )
        )
        assert receipt is not None
        assert not {"can_act", "can_manage"} & set(receipt.result)

    # The stored body replays unchanged, but the authority in it is computed for the request now.
    set_membership_role(case.workspace_id, case.owner_id, "member")
    replayed = case.owner.post(url, json=body)
    assert replayed.status_code == 200, replayed.text
    assert replayed.json() == {**first.json(), "can_act": False, "can_manage": False}

    anonymous = TestClient(app).post(url, json=body)
    assert anonymous.status_code == 401
    with session_scope() as session:
        row = session.get(IncidentCheck, task["id"])
        assert task_authority(session, row, None) == {"can_act": False, "can_manage": False}


def test_offline_trust_root_and_public_demo_keep_their_documented_override(incidents):
    case = private_case(incidents)
    task = assign(case.creator, case.analysis_id, "verify-machine", case.assignee_id)

    # Offline administrative sessions have no HTTP scope; the global owner is the explicit trust root there.
    with session_scope() as session:
        row = session.get(IncidentCheck, task["id"])
        account = session.get(Account, case.global_owner_id)
        assert task_authority(session, row, account) == {"can_act": True, "can_manage": True}
    # The same account over HTTP, as an ordinary member of that private workspace, has none.
    assert authority(case.global_owner, case, task) == (False, False)

    # The synthetic public example has no membership rows, so the global owner keeps the operator override there.
    _, public_analysis = analysed_incident(case.owner, DEMO, incidents)
    public_task = assign(case.creator, public_analysis, "verify-machine", case.assignee_id)
    refused = update(case.assignee, public_task, status="CANCELLED")
    assert refused.status_code == 403 and refused.json()["code"] == "CHECK_CREATOR_REQUIRED"
    cancelled = update(case.global_owner, public_task, status="CANCELLED")
    assert cancelled.status_code == 200, cancelled.text
