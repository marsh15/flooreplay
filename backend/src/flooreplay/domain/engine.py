"""The replay engine: gate -> policy -> validator, pure and deterministic.

The engine accepts immutable, validated inputs and returns a structured
result. It never reads the database, calls a model, consults the wall
clock, or discovers plugins. HTTP and CLI entry points both call this
function, which is what makes a replay a replay.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import gate as gate_module
from . import policies, validator
from .hashing import digest
from .types import (
    Abstention,
    ConstraintResult,
    DomainOutcome,
    GateFreshnessSettings,
    ReplayOutcome,
    ReplayRequestContext,
    Verdict,
)


class EngineError(RuntimeError):
    """Policy output or engine state violated the execution contract.

    Execution errors keep their own lifecycle (ERRORED); they are never
    reclassified as a legitimate context block.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def context_digest_for(ctx: ReplayRequestContext) -> str:
    return digest(
        {
            "catalog": ctx.catalog,
            "snapshots": ctx.snapshots,
            "event": ctx.event,
            "decision_at": ctx.decision_at,
            "target": ctx.target,
        }
    )


@dataclass(frozen=True)
class EngineRun:
    outcome: ReplayOutcome


def run_replay(
    ctx: ReplayRequestContext,
    settings: GateFreshnessSettings,
    policy_kind: str,
) -> EngineRun:
    context_digest = context_digest_for(ctx)
    gate_result = gate_module.evaluate_gate(ctx, settings)

    if gate_result.blocked_outcome is not None:
        return EngineRun(
            ReplayOutcome(
                outcome=gate_result.blocked_outcome,
                gate_issues=tuple(gate_result.shared_issues),
                context_digest=context_digest,
            )
        )

    # Evidence-level bar: no policy may run when no candidate in the pool is
    # supported by adequate (fresh, known) evidence. Missing or stale
    # evidence could still conceal a feasible candidate, so the honest
    # outcome is NEEDS_CONTEXT, whatever the policy's blind spots.
    if not any(f.evidence_supported for f in gate_result.candidates) and (
        gate_result.material_candidate_issues
    ):
        return EngineRun(
            ReplayOutcome(
                outcome=DomainOutcome.NEEDS_CONTEXT,
                gate_issues=tuple(gate_result.material_candidate_issues),
                context_digest=context_digest,
            )
        )

    try:
        decision, ranked = policies.select(policy_kind, ctx, gate_result, context_digest)
    except policies.PolicyError as exc:
        raise EngineError("POLICY_OUTPUT_INVALID", str(exc)) from exc

    if isinstance(decision, Abstention):
        # No supported candidate. If material unknown or stale candidate
        # evidence remains, the honest outcome is NEEDS_CONTEXT: missing
        # evidence could still conceal a feasible candidate.
        if gate_result.material_candidate_issues:
            return EngineRun(
                ReplayOutcome(
                    outcome=DomainOutcome.NEEDS_CONTEXT,
                    gate_issues=tuple(gate_result.material_candidate_issues),
                    abstention=decision,
                    context_digest=context_digest,
                    ranked_candidates=ranked,
                )
            )
        return EngineRun(
            ReplayOutcome(
                outcome=DomainOutcome.NO_FEASIBLE_CANDIDATE,
                abstention=decision,
                context_digest=context_digest,
                ranked_candidates=ranked,
            )
        )

    constraints: list[ConstraintResult] = validator.validate_proposal(
        decision, ctx, settings, context_digest
    )
    all_pass = all(c.verdict is Verdict.PASS for c in constraints)
    any_fail = any(c.verdict is Verdict.FAIL for c in constraints)
    if all_pass:
        outcome = DomainOutcome.READY_FOR_REVIEW
    elif any_fail:
        outcome = DomainOutcome.REJECTED_BY_CONSTRAINT
    else:  # required checks unevaluated without an explicit failure
        outcome = DomainOutcome.REJECTED_BY_CONSTRAINT

    return EngineRun(
        ReplayOutcome(
            outcome=outcome,
            proposal=decision,
            constraints=tuple(constraints),
            context_digest=context_digest,
            ranked_candidates=ranked,
        )
    )
