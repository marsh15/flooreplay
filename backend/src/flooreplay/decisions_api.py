"""HTTP surface for the v2 order decisions backend (T13).

Every route needs a signed-in account. The workspace is a required query parameter, never a
body field, and it is checked against the caller's real memberships: a workspace the caller
cannot see answers 404, the same as an unknown id. Writes need membership in that workspace.
Adoption additionally needs the owner role from the membership row, not from the request.

No route here calls a model provider: evaluation is pure replay over stored facts.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .auth import Account, require_reviewer
from .db import session_scope
from .decisions import service
from .decisions.models import DecisionEvaluation, DecisionRecord, PolicyAdoption, RegressionRun
from .decisions.policy import DEFAULT_POLICY_V1, PolicyDocument, parameter_diff
from .decisions.snapshot import Snapshot
from .decisions.types import Classification, Fact, Recommendation
from .errors import ServiceError
from .workspaces import DEMO, WorkspaceMember

WorkspaceQuery = Annotated[str, Query(min_length=1, max_length=64, description="Workspace the caller belongs to")]


class OrderRef(BaseModel):
    order_id: str


class OrderList(BaseModel):
    items: list[OrderRef]


class OrderView(BaseModel):
    order_id: str
    cutoff: datetime
    settled: bool
    snapshot_digest: str
    facts: list[Fact]


class SnapshotView(BaseModel):
    cutoff: datetime
    settled: bool
    snapshot: Snapshot


class EvaluateRequest(BaseModel):
    order_id: str = Field(min_length=1, max_length=120)
    cutoff: datetime
    policy_digest: str | None = Field(default=None, min_length=1, max_length=128)


class EvaluationView(BaseModel):
    id: str
    order_id: str
    cutoff: datetime
    policy_digest: str
    engine_version: str
    snapshot_digest: str
    decision_digest: str
    outcome: Recommendation
    created_at: datetime


class EvaluationDetail(BaseModel):
    evaluation: EvaluationView
    reconstruction: service.Reconstruction


class RecordRequest(BaseModel):
    decision: Recommendation
    reason: str = Field(default="", max_length=2000)


class DecisionRecordView(BaseModel):
    id: str
    evaluation_id: str
    decision: Recommendation
    recommended_outcome: Recommendation
    override: bool
    reason: str
    actor: str
    created_at: datetime


class StoredPolicyView(BaseModel):
    policy_digest: str
    label: str
    engine_version: str
    created_at: datetime
    policy: PolicyDocument


class PolicyList(BaseModel):
    items: list[StoredPolicyView]


class PolicyStored(BaseModel):
    policy_digest: str


class PolicyDiffRequest(BaseModel):
    baseline: PolicyDocument
    candidate: PolicyDocument


class ParameterChange(BaseModel):
    path: str
    before: Any
    after: Any


class PolicyDiffView(BaseModel):
    changes: list[ParameterChange]


class RegressionRequest(BaseModel):
    baseline: PolicyDocument
    candidate: PolicyDocument


class RegressionCaseView(BaseModel):
    case_id: str
    classification: Classification
    baseline: service.CaseRun
    candidate: service.CaseRun


class RegressionRunView(BaseModel):
    id: str
    status: str
    complete: bool
    baseline_policy_digest: str
    candidate_policy_digest: str
    suite_digest: str
    created_at: datetime
    cases: list[RegressionCaseView]


class AdoptRequest(BaseModel):
    acknowledgements: dict[str, str] = Field(default_factory=dict)


class PolicyAdoptionView(BaseModel):
    id: str
    regression_run_id: str
    policy_digest: str
    adopted_by: str
    acknowledgements: dict[str, str]
    created_at: datetime


def _aware(cutoff: datetime) -> datetime:
    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
        raise ServiceError("CUTOFF_INVALID", "cutoff must carry a UTC offset, e.g. 2026-03-02T09:00:00+05:30", 422)
    try:
        cutoff.astimezone(UTC)
    except (OverflowError, ValueError) as exc:
        raise ServiceError("CUTOFF_INVALID", "cutoff is outside the supported date range", 422) from exc
    return cutoff


def _readable(request: Request, workspace_id: str) -> str:
    """A workspace the caller is a member of (or the public demo), otherwise 404."""
    visible: list[str] = request.state.workspace_ids
    if workspace_id not in visible:
        raise ServiceError("WORKSPACE_UNKNOWN", "Workspace not found", 404)
    return workspace_id


def _member(session: Session, user: Account, workspace_id: str) -> WorkspaceMember:
    """The caller's membership in a workspace that accepts writes, otherwise 404."""
    row = session.get(WorkspaceMember, (workspace_id, user.id))
    if row is None or workspace_id == DEMO:
        raise ServiceError("WORKSPACE_UNKNOWN", "Workspace not found", 404)
    return row


def _evaluation_view(row: DecisionEvaluation) -> EvaluationView:
    return EvaluationView(
        id=row.id,
        order_id=row.order_id,
        cutoff=row.cutoff,
        policy_digest=row.policy_digest,
        engine_version=row.engine_version,
        snapshot_digest=row.snapshot_digest,
        decision_digest=row.decision_digest,
        outcome=Recommendation(row.outcome),
        created_at=row.created_at,
    )


def _record_view(row: DecisionRecord) -> DecisionRecordView:
    return DecisionRecordView(
        id=row.id,
        evaluation_id=row.evaluation_id,
        decision=Recommendation(row.decision),
        recommended_outcome=Recommendation(row.recommended_outcome),
        override=row.override,
        reason=row.reason,
        actor=row.actor,
        created_at=row.created_at,
    )


def _run_view(row: RegressionRun) -> RegressionRunView:
    return RegressionRunView(
        id=row.id,
        status=row.status,
        complete=row.complete,
        baseline_policy_digest=row.baseline_policy_digest,
        candidate_policy_digest=row.candidate_policy_digest,
        suite_digest=row.suite_digest,
        created_at=row.created_at,
        cases=[RegressionCaseView.model_validate(item) for item in row.results],
    )


def _adoption_view(row: PolicyAdoption) -> PolicyAdoptionView:
    return PolicyAdoptionView(
        id=row.id,
        regression_run_id=row.regression_run_id,
        policy_digest=row.policy_digest,
        adopted_by=row.adopted_by,
        acknowledgements=dict(row.acknowledgements),
        created_at=row.created_at,
    )


def install_decisions_routes(app: FastAPI, limit_public_execution: Callable[[Request], None]) -> None:
    """Register the decisions routes on the app. `limit_public_execution` guards evaluate."""
    prefix = "/api/v1/decisions"

    @app.get(prefix + "/orders", response_model=OrderList)
    def list_orders(
        request: Request, user: Annotated[Account, Depends(require_reviewer)], workspace_id: WorkspaceQuery
    ) -> OrderList:
        ws = _readable(request, workspace_id)
        with session_scope() as session:
            return OrderList(items=[OrderRef(order_id=oid) for oid in service.list_order_ids(session, ws)])

    @app.get(prefix + "/orders/{order_id}", response_model=OrderView)
    def get_order(
        order_id: str,
        request: Request,
        cutoff: datetime,
        user: Annotated[Account, Depends(require_reviewer)],
        workspace_id: WorkspaceQuery,
    ) -> OrderView:
        ws = _readable(request, workspace_id)
        cut = _aware(cutoff)
        with session_scope() as session:
            if order_id not in service.list_order_ids(session, ws):
                raise ServiceError("ORDER_UNKNOWN", "order not found in this workspace", 404)
            snap = service.snapshot_at(session, ws, cut)
            return OrderView(
                order_id=order_id,
                cutoff=cut,
                settled=service.is_settled(session, cut),
                snapshot_digest=snap.digest,
                facts=service.order_facts(snap, order_id),
            )

    @app.get(prefix + "/snapshot", response_model=SnapshotView)
    def get_snapshot(
        request: Request,
        cutoff: datetime,
        user: Annotated[Account, Depends(require_reviewer)],
        workspace_id: WorkspaceQuery,
    ) -> SnapshotView:
        ws = _readable(request, workspace_id)
        cut = _aware(cutoff)
        with session_scope() as session:
            return SnapshotView(
                cutoff=cut,
                settled=service.is_settled(session, cut),
                snapshot=service.snapshot_at(session, ws, cut),
            )

    @app.post(prefix + "/evaluate", response_model=EvaluationView)
    def evaluate(
        body: EvaluateRequest,
        request: Request,
        user: Annotated[Account, Depends(require_reviewer)],
        workspace_id: WorkspaceQuery,
        _limits: None = Depends(limit_public_execution),
    ) -> EvaluationView:
        # Idempotent: the same order, cutoff and policy return the stored evaluation (200).
        _readable(request, workspace_id)
        cut = _aware(body.cutoff)
        with session_scope() as session:
            _member(session, user, workspace_id)
            if body.order_id not in service.list_order_ids(session, workspace_id):
                raise ServiceError("ORDER_UNKNOWN", "order not found in this workspace", 404)
            policy = (
                DEFAULT_POLICY_V1
                if body.policy_digest is None
                else service.load_policy(session, workspace_id, body.policy_digest)
            )
            row = service.evaluate_order(session, workspace_id, body.order_id, cut, policy)
            return _evaluation_view(row)

    @app.get(prefix + "/evaluations/{evaluation_id}", response_model=EvaluationDetail)
    def get_evaluation(
        evaluation_id: str,
        request: Request,
        user: Annotated[Account, Depends(require_reviewer)],
        workspace_id: WorkspaceQuery,
    ) -> EvaluationDetail:
        ws = _readable(request, workspace_id)
        with session_scope() as session:
            row = service.load_evaluation(session, ws, evaluation_id)
            return EvaluationDetail(
                evaluation=_evaluation_view(row),
                reconstruction=service.reconstruct(session, ws, evaluation_id),
            )

    @app.post(prefix + "/evaluations/{evaluation_id}/record", response_model=DecisionRecordView)
    def record_decision(
        evaluation_id: str,
        body: RecordRequest,
        request: Request,
        user: Annotated[Account, Depends(require_reviewer)],
        workspace_id: WorkspaceQuery,
    ) -> DecisionRecordView:
        _readable(request, workspace_id)
        with session_scope() as session:
            _member(session, user, workspace_id)
            row = service.record_decision(
                session, workspace_id, evaluation_id, body.decision, body.reason, actor=user.id
            )
            return _record_view(row)

    @app.get(prefix + "/policies", response_model=PolicyList)
    def list_policies(
        request: Request, user: Annotated[Account, Depends(require_reviewer)], workspace_id: WorkspaceQuery
    ) -> PolicyList:
        ws = _readable(request, workspace_id)
        with session_scope() as session:
            return PolicyList(
                items=[
                    StoredPolicyView(
                        policy_digest=row.policy_digest,
                        label=row.label,
                        engine_version=row.engine_version,
                        created_at=row.created_at,
                        policy=PolicyDocument.model_validate(row.policy),
                    )
                    for row in service.list_stored_policies(session, ws)
                ]
            )

    @app.post(prefix + "/policies", response_model=PolicyStored)
    def store_policy(
        body: PolicyDocument,
        request: Request,
        user: Annotated[Account, Depends(require_reviewer)],
        workspace_id: WorkspaceQuery,
    ) -> PolicyStored:
        _readable(request, workspace_id)
        with session_scope() as session:
            _member(session, user, workspace_id)
            return PolicyStored(policy_digest=service.store_policy(session, workspace_id, body))

    @app.post(prefix + "/policies/diff", response_model=PolicyDiffView)
    def diff_policies(
        body: PolicyDiffRequest,
        request: Request,
        user: Annotated[Account, Depends(require_reviewer)],
        workspace_id: WorkspaceQuery,
    ) -> PolicyDiffView:
        _readable(request, workspace_id)
        return PolicyDiffView(
            changes=[
                ParameterChange.model_validate(entry)
                for entry in parameter_diff(body.baseline, body.candidate)
            ]
        )

    @app.post(prefix + "/regression-runs", response_model=RegressionRunView)
    def start_regression_run(
        body: RegressionRequest,
        request: Request,
        user: Annotated[Account, Depends(require_reviewer)],
        workspace_id: WorkspaceQuery,
    ) -> RegressionRunView:
        _readable(request, workspace_id)
        with session_scope() as session:
            _member(session, user, workspace_id)
            row = service.run_regression(session, workspace_id, body.baseline, body.candidate)
            return _run_view(row)

    @app.get(prefix + "/regression-runs/{run_id}", response_model=RegressionRunView)
    def get_regression_run(
        run_id: str,
        request: Request,
        user: Annotated[Account, Depends(require_reviewer)],
        workspace_id: WorkspaceQuery,
    ) -> RegressionRunView:
        ws = _readable(request, workspace_id)
        with session_scope() as session:
            return _run_view(service.load_regression_run(session, ws, run_id))

    @app.post(prefix + "/regression-runs/{run_id}/adopt", response_model=PolicyAdoptionView)
    def adopt_regression_run(
        run_id: str,
        body: AdoptRequest,
        request: Request,
        user: Annotated[Account, Depends(require_reviewer)],
        workspace_id: WorkspaceQuery,
    ) -> PolicyAdoptionView:
        _readable(request, workspace_id)
        with session_scope() as session:
            member = _member(session, user, workspace_id)
            # The role comes from the caller's membership row only; the request cannot name it.
            if member.role != service.ADOPTION_OWNER_ROLE:
                raise ServiceError("ADOPTION_FORBIDDEN", "only the workspace owner can adopt a policy", 403)
            row = service.adopt_policy(
                session,
                workspace_id,
                run_id,
                member.role,
                body.acknowledgements,
                actor=user.id,
            )
            return _adoption_view(row)
