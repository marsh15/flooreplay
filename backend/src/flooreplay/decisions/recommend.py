"""Conservative recommendation from deterministic gate and constraint results."""

from flooreplay.decisions.constraints import ConstraintResult
from flooreplay.decisions.gate import GateResult
from flooreplay.decisions.types import (
    ConstraintId,
    ConstraintStatus,
    FrozenModel,
    GateState,
    Recommendation,
)


class OvertimeCondition(FrozenModel):
    type: str = "overtime"
    lines: int
    hours_per_line_per_day: int
    days: int


class RecommendationView(FrozenModel):
    outcome: Recommendation
    candidate_outcome: Recommendation | None = None
    conditions: tuple[OvertimeCondition, ...] = ()
    reasons: tuple[str, ...] = ()


def recommend(gate: GateResult, constraints: tuple[ConstraintResult, ...]) -> RecommendationView:
    """Apply the gate, review and approval rules without consulting a provider.

    Split-shipment calculation is not yet implemented: material shortfalls require review
    rather than a claim that a partial delivery is feasible.
    """
    if gate.state is not GateState.READY:
        return RecommendationView(
            outcome=Recommendation.NEEDS_REVIEW, reasons=(f"Gate: {gate.state}",)
        )
    if any(c.pending_review_fact_ids for c in constraints):
        return RecommendationView(
            outcome=Recommendation.NEEDS_REVIEW, reasons=("Evidence requires review",)
        )
    if not constraints or any(c.status is ConstraintStatus.NOT_EVALUATED for c in constraints):
        return RecommendationView(
            outcome=Recommendation.NEEDS_REVIEW, reasons=("A constraint could not be evaluated",)
        )

    failed = [c for c in constraints if c.status is ConstraintStatus.FAIL]
    approval_failed = any(c.constraint is ConstraintId.APPROVAL for c in failed)
    other = [c for c in failed if c.constraint is not ConstraintId.APPROVAL]
    conditions: tuple[OvertimeCondition, ...] = ()
    capacity = any(c.constraint is ConstraintId.CAPACITY for c in other)
    overtime = next((c for c in constraints if c.constraint is ConstraintId.OVERTIME), None)
    if capacity and overtime and overtime.status is ConstraintStatus.PASS and overtime.overtime:
        need = overtime.overtime
        if need.hours_per_line_per_day is not None:
            conditions = (
                OvertimeCondition(
                    lines=need.lines,
                    days=need.days,
                    hours_per_line_per_day=need.hours_per_line_per_day,
                ),
            )
            other = [c for c in other if c.constraint is not ConstraintId.CAPACITY]
    if any(c.constraint in (ConstraintId.FABRIC, ConstraintId.TRIMS) for c in other):
        return RecommendationView(
            outcome=Recommendation.NEEDS_REVIEW,
            reasons=("Material shortfall requires split-shipment assessment",),
        )
    if other:
        return RecommendationView(
            outcome=Recommendation.DECLINE, reasons=tuple(c.detail for c in other)
        )
    candidate = Recommendation.ACCEPT_WITH_CONDITIONS if conditions else Recommendation.ACCEPT
    if approval_failed:
        return RecommendationView(
            outcome=Recommendation.NEEDS_REVIEW,
            candidate_outcome=candidate,
            conditions=conditions,
            reasons=("Approval threshold exceeded",),
        )
    return RecommendationView(outcome=candidate, conditions=conditions)
