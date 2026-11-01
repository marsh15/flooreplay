"""Private draft overrides belong to workspace owners, not invited account owners."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from flooreplay.ai_evaluation import AIClaimReview
from flooreplay.api import app
from flooreplay.auth import create_account, sign_in
from flooreplay.db import session_scope
from flooreplay.domain.hashing import digest
from flooreplay.paid_models import AIRun
from flooreplay.semantic_review import AIReviewPublication, AIRunAssessment
from flooreplay.workspaces import WorkspaceMember


def account(role):
    name = "ai-authority-" + uuid4().hex
    user = create_account(name, "synthetic-authority-test-password", role)
    token = sign_in(name, "synthetic-authority-test-password", name)["token"]
    return TestClient(app, headers={"Authorization": "Bearer " + token}), user


@pytest.fixture
def private_draft():
    owner, owner_user = account("owner")
    member, member_user = account("owner")
    requester, requester_user = account("reviewer")
    outsider, _ = account("owner")
    workspace = owner.get("/api/v1/workspaces").json()["items"][0]["id"]
    for user in (member_user, requester_user):
        response = owner.post(
            f"/api/v1/workspaces/{workspace}/members", json={"account_id": user["id"]}
        )
        assert response.status_code == 200, response.text
    output = {
        "claims": [
            {
                "text": "The source does not establish a confirmed cause.",
                "evidence_ids": ["note-a"],
                "metric_ids": [],
                "historical_refs": [],
                "source_fields": [],
            }
        ],
        "abstention_reasons": ["The interval remains incomplete."],
    }
    with session_scope() as session:
        run = AIRun(
            workspace_id=workspace,
            user_id=requester_user["id"],
            request_key=uuid4().hex,
            analysis_id="synthetic-private-analysis",
            identity=uuid4().hex,
            task="question",
            question="Unpublished private factory question",
            status="COMPLETED",
            packet={
                "incident_id": "synthetic-review",
                "revision": 1,
                "cutoff": "2026-09-20T09:30:00+05:30",
                "evidence": [{"id": "note-a", "summary": "Private observation; impact unknown."}],
                "metrics": [],
                "historical_evidence": [],
            },
            configuration={"generation_model": "mock-only"},
            attempts=[],
            result={"output": output},
            reservation_id="mock-only",
        )
        session.add(run)
        session.flush()
        run_id = run.id
    try:
        yield dict(
            owner=owner,
            owner_id=owner_user["id"],
            member=member,
            requester=requester,
            outsider=outsider,
            workspace=workspace,
            run_id=run_id,
            prefix=f"/api/v1/ai-runs/{run_id}",
            fingerprint=digest(output),
        )
    finally:
        with session_scope() as session:
            for model in (AIClaimReview, AIRunAssessment, AIReviewPublication):
                session.execute(delete(model).where(model.run_id == run_id))
            session.execute(delete(AIRun).where(AIRun.id == run_id))


def claim_body(case):
    return dict(
        output_digest=case["fingerprint"],
        idempotency_key=uuid4().hex,
        claim_path="claims.0",
        judgment="insufficient_evidence",
        rationale="Further evidence is required.",
        reviewer_kind="unspecified",
        qualifications="",
        independent=False,
    )


def assessment_body(case):
    return dict(
        output_digest=case["fingerprint"],
        idempotency_key=uuid4().hex,
        reviewer_kind="unspecified",
        qualifications="",
        independent=False,
        usefulness="uncertain",
        omitted_contradictions=[],
        attribution_errors=[],
        abstention="appropriate",
        rationale="Synthetic evaluation only.",
        limitations="No practitioner result measured.",
    )


def test_unpublished_draft_is_private_to_requester_and_workspace_owner(private_draft):
    case = private_draft
    for client in (case["requester"], case["owner"]):
        for suffix in ("", "/review-packet", "/review-report"):
            response = client.get(case["prefix"] + suffix)
            assert response.status_code == 200, response.text
    for client in (case["member"], case["outsider"]):
        for suffix in ("", "/review-packet", "/review-report"):
            assert client.get(case["prefix"] + suffix).status_code == 404
        assert (
            client.post(
                case["prefix"] + "/publish-review",
                json={"output_digest": case["fingerprint"], "idempotency_key": uuid4().hex},
            ).status_code
            == 404
        )
        assert (
            client.post(case["prefix"] + "/claim-review", json=claim_body(case)).status_code == 404
        )
        assert (
            client.post(case["prefix"] + "/assessment", json=assessment_body(case)).status_code
            == 404
        )


@pytest.mark.parametrize("publisher", ["requester", "owner"])
def test_published_review_preserves_members_exact_digest_access(private_draft, publisher):
    case = private_draft
    shared = case[publisher].post(
        case["prefix"] + "/publish-review",
        json={"output_digest": case["fingerprint"], "idempotency_key": uuid4().hex},
    )
    assert shared.status_code == 200, shared.text
    assert case["member"].get(case["prefix"] + "/review-packet").status_code == 200
    assert case["outsider"].get(case["prefix"] + "/review-packet").status_code == 404
    annotation = case["member"].post(case["prefix"] + "/claim-review", json=claim_body(case))
    assert annotation.status_code == 200, annotation.text
    assessed = case["member"].post(case["prefix"] + "/assessment", json=assessment_body(case))
    assert assessed.status_code == 200, assessed.text
    wrong = {**claim_body(case), "output_digest": "0" * 64}
    assert case["member"].post(case["prefix"] + "/claim-review", json=wrong).status_code == 409
    # Publication shares the review packet, not unrestricted requester-only run lookup.
    assert case["member"].get(case["prefix"]).status_code == 404


def test_membership_change_removes_unpublished_draft_override(private_draft):
    case = private_draft
    assert case["owner"].get(case["prefix"]).status_code == 200
    with session_scope() as session:
        session.get(WorkspaceMember, (case["workspace"], case["owner_id"])).role = "member"
    assert case["owner"].get(case["prefix"]).status_code == 404
    assert (
        case["owner"]
        .post(
            case["prefix"] + "/publish-review",
            json={"output_digest": case["fingerprint"], "idempotency_key": uuid4().hex},
        )
        .status_code
        == 404
    )
    with session_scope() as session:
        session.get(WorkspaceMember, (case["workspace"], case["owner_id"])).role = "owner"
    assert case["owner"].get(case["prefix"]).status_code == 200
    with session_scope() as session:
        session.delete(session.get(WorkspaceMember, (case["workspace"], case["owner_id"])))
    assert case["owner"].get(case["prefix"]).status_code == 404
    assert case["requester"].get(case["prefix"]).status_code == 200
