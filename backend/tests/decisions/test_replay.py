from decisions.worlds import qc_fact, ready_world
from flooreplay.decisions.replay import replay
from flooreplay.decisions.types import FactKind, Recommendation


def test_ready_world_replays_deterministically():
    world = ready_world()
    result = replay(world.snapshot(), world.order_id, world.policy, world.coverage)
    shuffled = world.without().with_facts(*reversed(world.facts))
    again = replay(shuffled.snapshot(), world.order_id, world.policy, world.coverage)
    assert result.recommendation.outcome == Recommendation.ACCEPT
    assert result.decision_digest == again.decision_digest


def test_missing_evidence_never_accepts():
    world = ready_world().without(kind=FactKind.BOM)
    result = replay(world.snapshot(), world.order_id, world.policy, world.coverage)
    assert result.recommendation.outcome == Recommendation.NEEDS_REVIEW


def test_unreviewed_signal_requires_review():
    world = ready_world().with_facts(qc_fact("pending", "LOT-N1", review_state="needs_review"))
    result = replay(world.snapshot(), world.order_id, world.policy, world.coverage)
    assert result.recommendation.outcome == Recommendation.NEEDS_REVIEW


def test_approval_failure_keeps_candidate():
    from decisions.worlds import order_fact

    world = ready_world().without(fact_id="w-order").with_facts(order_fact(order_value="999999999"))
    result = replay(world.snapshot(), world.order_id, world.policy, world.coverage)
    assert result.recommendation.outcome == Recommendation.NEEDS_REVIEW
    assert result.recommendation.candidate_outcome == Recommendation.ACCEPT


def test_material_shortfall_does_not_claim_split_feasibility():
    from decisions.worlds import lot_fact

    world = (
        ready_world()
        .without(fact_id="w-lot-navy")
        .with_facts(lot_fact("low", "LOT-N1", "NAVY", "1"))
    )
    result = replay(world.snapshot(), world.order_id, world.policy, world.coverage)
    assert result.recommendation.outcome == Recommendation.NEEDS_REVIEW
    assert not result.recommendation.conditions


def test_capacity_shortfall_can_be_covered_by_overtime():
    from flooreplay.decisions.constraints import ConstraintResult, OvertimeNeed
    from flooreplay.decisions.gate import GateResult
    from flooreplay.decisions.recommend import recommend
    from flooreplay.decisions.types import ConstraintId, ConstraintStatus, GateState

    capacity = ConstraintResult(
        constraint=ConstraintId.CAPACITY,
        subject="order",
        status=ConstraintStatus.FAIL,
        fact_ids=(),
        steps=(),
        detail="shortfall",
    )
    overtime = ConstraintResult(
        constraint=ConstraintId.OVERTIME,
        subject="order",
        status=ConstraintStatus.PASS,
        fact_ids=(),
        steps=(),
        detail="covered",
        overtime=OvertimeNeed(lines=2, days=3, cap_hours_per_line_day=2, hours_per_line_per_day=1),
    )
    result = recommend(GateResult(state=GateState.READY, findings=()), (capacity, overtime))
    assert result.outcome == Recommendation.ACCEPT_WITH_CONDITIONS
    assert result.conditions[0].hours_per_line_per_day == 1


def test_disabled_approval_cannot_auto_accept():
    from flooreplay.decisions.types import ConstraintId

    world = ready_world()
    policy = world.policy.model_copy(
        update={
            "enabled_constraints": tuple(
                c for c in world.policy.enabled_constraints if c != ConstraintId.APPROVAL
            )
        }
    )
    result = replay(world.snapshot(), world.order_id, policy, world.coverage)
    assert result.recommendation.outcome == Recommendation.NEEDS_REVIEW
