"""Pure replay of a frozen snapshot under a versioned policy."""

from collections.abc import Mapping

from flooreplay.decisions.constraints import ConstraintResult, evaluate_constraints
from flooreplay.decisions.gate import CoverageDecl, GateResult, evaluate_gate
from flooreplay.decisions.policy import ENGINE_VERSION, PolicyDocument, policy_digest
from flooreplay.decisions.recommend import RecommendationView, recommend
from flooreplay.decisions.snapshot import Snapshot
from flooreplay.decisions.types import ConstraintId, FrozenModel, Recommendation, decision_digest


class ReplayResult(FrozenModel):
    order_id: str
    snapshot_digest: str
    policy_digest: str
    engine_version: str
    gate: GateResult
    constraints: tuple[ConstraintResult, ...]
    recommendation: RecommendationView
    decision_digest: str


def replay(
    snapshot: Snapshot,
    order_id: str,
    policy: PolicyDocument,
    coverage: Mapping[str, CoverageDecl] | None = None,
) -> ReplayResult:
    if policy.engine_version != ENGINE_VERSION:
        raise ValueError(f"Unsupported engine version: {policy.engine_version}")
    gate = evaluate_gate(snapshot, order_id, policy, coverage)
    constraints = evaluate_constraints(snapshot, order_id, policy, gate)
    recommendation = recommend(gate, constraints)
    if set(policy.enabled_constraints) != set(ConstraintId):
        recommendation = RecommendationView(
            outcome=Recommendation.NEEDS_REVIEW,
            reasons=("Policy does not enable every required constraint",),
        )
    body = {
        "order_id": order_id,
        "snapshot_digest": snapshot.digest,
        "policy_digest": policy_digest(policy),
        "engine_version": ENGINE_VERSION,
        "gate": gate,
        "constraints": constraints,
        "recommendation": recommendation,
    }
    return ReplayResult(
        order_id=order_id,
        snapshot_digest=snapshot.digest,
        policy_digest=policy_digest(policy),
        engine_version=ENGINE_VERSION,
        gate=gate,
        constraints=constraints,
        recommendation=recommendation,
        decision_digest=decision_digest(body),
    )
