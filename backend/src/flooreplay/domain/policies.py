"""Recommendation policies.

A policy ranks eligible operators and returns at most one proposal, or
abstains. Policies may reuse gate evidence but the validator never trusts
their eligibility decisions: every constraint is re-derived independently.

Registered configurations:
- BASELINE_V1: ranks core-eligible candidates but deliberately omits
  assignment-overlap filtering. Its limitation is labeled everywhere.
- IMPROVED_V1: filters every supported eligibility requirement.

Ranking is a transparent tuple: higher skill level, then same-line
preference, then canonical operator id. No weighted utility, no optimality
claim.
"""

from __future__ import annotations

from .gate import CandidateFinding, GateResult
from .types import (
    Abstention,
    CandidateExclusion,
    CoverageTarget,
    PlanSnapshotPayload,
    PolicyActionType,
    Proposal,
    ReplayRequestContext,
    Slot,
)


class PolicyKind:
    BASELINE_V1 = "baseline-v1"
    IMPROVED_V1 = "improved-v1"

    ALL = (BASELINE_V1, IMPROVED_V1)


class PolicyError(RuntimeError):
    """The policy produced output that violates the recommendation contract."""


def _eligible(kind: str, finding: CandidateFinding) -> bool:
    if kind == PolicyKind.BASELINE_V1:
        return finding.core_eligible
    if kind == PolicyKind.IMPROVED_V1:
        return finding.fully_supported
    raise PolicyError(f"unknown policy kind: {kind}")


def _rank(kind: str, findings: list[CandidateFinding], slot: Slot) -> list[CandidateFinding]:
    eligible = [f for f in findings if _eligible(kind, f)]
    eligible.sort(
        key=lambda f: (
            -f.skill_level,
            f.home_line_id != slot.line_id,  # same-line operators first
            f.operator_id,
        )
    )
    return eligible


def select(
    kind: str,
    ctx: ReplayRequestContext,
    gate: GateResult,
    context_digest: str,
) -> tuple[Proposal | Abstention, tuple[str, ...]]:
    if gate.slot is None or gate.plan_payload is None:
        raise PolicyError("policy invoked without a resolved target slot and plan")
    slot: Slot = gate.slot
    plan: PlanSnapshotPayload = gate.plan_payload
    target: CoverageTarget = ctx.target

    ranked = _rank(kind, gate.candidates, slot)
    ranked_ids = tuple(f.operator_id for f in ranked)

    if not ranked:
        exclusions = tuple(
            CandidateExclusion(
                operator_id=f.operator_id,
                issue_codes=tuple(i.code for i in f.issues),
            )
            for f in gate.candidates
            if f.issues
        )
        return (
            Abstention(reason_code="NO_SUPPORTED_CANDIDATE", candidate_exclusions=exclusions),
            ranked_ids,
        )

    chosen = ranked[0]
    proposal = Proposal(
        action_type=PolicyActionType.PROPOSE_SLOT_COVERAGE,
        operator_id=chosen.operator_id,
        target_slot_id=slot.id,
        machine_id=slot.machine_id,
        operation_id=slot.operation_id,
        style_id=slot.style_id,
        plan_revision=plan.revision,
        starts_at=target.starts_at,
        ends_at=target.ends_at,
        context_digest=context_digest,
        ranking_factors=(
            ("skill_level", str(chosen.skill_level)),
            ("same_line", str(chosen.home_line_id == slot.line_id)),
            ("operator_id", chosen.operator_id),
        ),
    )
    return proposal, ranked_ids
