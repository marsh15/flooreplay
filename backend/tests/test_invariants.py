"""Property-based invariants over the engine and validator."""

from __future__ import annotations

from hypothesis import HealthCheck, given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from flooreplay.domain import validator
from flooreplay.domain.engine import context_digest_for, run_replay
from flooreplay.domain.types import DomainOutcome, OperatorId, Proposal, Verdict
from flooreplay.fixtures import DEFAULT_FRESHNESS, hero_context, hero_snapshots_v2

OPERATOR_IDS = tuple(op.id for op in hero_context(hero_snapshots_v2()).catalog.operators)

CTX = hero_context(hero_snapshots_v2())
DIGEST = context_digest_for(CTX)


def _proposal(operator_id: str) -> Proposal:
    return Proposal(
        operator_id=operator_id,
        target_slot_id="L4-SLM-1",
        machine_id="SN-4407",
        operation_id="OP-SLM",
        style_id="ST-411",
        plan_revision="PLAN-2026-09-22-B",
        starts_at=CTX.target.starts_at,
        ends_at=CTX.target.ends_at,
        context_digest=DIGEST,
    )


@hyp_settings(max_examples=60, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(operator_id=st.sampled_from(OPERATOR_IDS))
def test_disqualified_operators_never_reach_ready_for_review(operator_id: OperatorId):
    """Absent, unavailable, unqualified, or overlapping operators can never
    produce an all-PASS validation, and the engine never emits READY_FOR_REVIEW
    for them. Absent operators: O145, O196. Unavailable: O117. Overlapping:
    O204 (also O126, O158, O190, O133 occupy other slots). Unqualified on
    sleeve attach: level < 3."""
    results = {
        c.code: c for c in validator.validate_proposal(_proposal(operator_id), CTX, DEFAULT_FRESHNESS, DIGEST)
    }
    all_pass = all(c.verdict is Verdict.PASS for c in results.values())
    qualified_idle = operator_id in ("O219", "O112")
    if not qualified_idle:
        assert not all_pass, f"{operator_id} must not pass every constraint"

    run = run_replay(CTX, DEFAULT_FRESHNESS, "improved-v1").outcome
    if run.proposal is not None and not qualified_idle:
        assert run.proposal.operator_id != operator_id


@hyp_settings(max_examples=60)
@given(operator_id=st.sampled_from(OPERATOR_IDS))
def test_engine_never_emits_unvalidated_outcomes(operator_id: OperatorId):
    run = run_replay(CTX, DEFAULT_FRESHNESS, "baseline-v1").outcome
    if run.proposal and run.proposal.operator_id == operator_id:
        # Whatever the baseline proposes must still be independently validated.
        assert run.outcome in (
            DomainOutcome.READY_FOR_REVIEW,
            DomainOutcome.REJECTED_BY_CONSTRAINT,
        )


def test_blocking_shared_issue_prevents_policy_invocation():
    """A stale shared snapshot blocks before any policy could run."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from flooreplay.domain.types import SnapshotKind

    IST = ZoneInfo("Asia/Kolkata")
    old_plan = next(s for s in CTX.snapshots if s.kind.value == "PLAN")
    stale_plan = old_plan.model_copy(
        update={
            "plan": old_plan.plan.model_copy(
                update={"verified_at": datetime(2026, 9, 20, 6, 0, tzinfo=IST)}
            )
        }
    )
    ctx = CTX.model_copy(
        update={
            "snapshots": tuple(
                stale_plan if s.kind is SnapshotKind.PLAN else s for s in CTX.snapshots
            )
        }
    )
    for policy in ("baseline-v1", "improved-v1"):
        run = run_replay(ctx, DEFAULT_FRESHNESS, policy).outcome
        assert run.outcome is DomainOutcome.NEEDS_CONTEXT
        assert run.proposal is None and run.abstention is None


def test_irrelevant_catalog_metadata_leaves_result_unchanged():
    """Adding a catalog field that no rule reads must not change the result.

    The context digest legitimately tracks the pinned catalog identity, so
    the digest moves; the deterministic decision content must not."""
    base = run_replay(CTX, DEFAULT_FRESHNESS, "improved-v1").outcome
    decorated_catalog = CTX.catalog.model_copy(
        update={"factory_name": CTX.catalog.factory_name + " (rebranded)"}
    )
    ctx2 = CTX.model_copy(update={"catalog": decorated_catalog})
    rerun = run_replay(ctx2, DEFAULT_FRESHNESS, "improved-v1").outcome
    assert base.outcome == rerun.outcome
    assert base.proposal is not None and rerun.proposal is not None
    assert base.proposal.operator_id == rerun.proposal.operator_id
    assert base.proposal.context_digest != rerun.proposal.context_digest
