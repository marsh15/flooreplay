"""Constraints: FABRIC, SAFETY, TRIMS, CAPACITY, OVERTIME, APPROVAL.

Every worked example below carries its hand arithmetic in a comment. The shared world is
`worlds.ready_world()`: order O1 = NAVY 600 + WHITE 400 pcs (1000 pcs), BOM 0.35 kg/pc and
SAM 12.5 min, NAVY lot 500 kg, WHITE lot 300 kg, 100000 pcs of each trim, 3000 minutes on
every line-day. Defaults: fabric wastage 0.05, inbound buffer 2 d, safety floor 0.05, trims
wastage 0.03 / buffer 2 d, efficiency 0.55, cut-to-ship 21 d, finishing 4 d, OT cap 2 h.

    cut_date          = 2026-03-30 - 21 d = 2026-03-09
    inbound cut-off   = 2026-03-09 -  2 d = 2026-03-07  (fabric and trims)
    sewing window     = 2026-03-10 .. 2026-03-26, Sundays (03-15, 03-22) off = 15 days
"""

from __future__ import annotations

import ast
import random
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from decisions.worlds import (
    AS_OF,
    CUTOFF,
    SHIP_DATE,
    World,
    allocation_fact,
    bom_fact,
    capacity_fact,
    commitment_fact,
    cover,
    inbound_fact,
    kg,
    lot_fact,
    order_fact,
    qc_fact,
    ready_world,
    resolution_fact,
    trim_fact,
    working_days,
)
from flooreplay.decisions import constraints as constraints_module
from flooreplay.decisions.constraints import (
    ConstraintResult,
    Step,
    evaluate_constraints,
)
from flooreplay.decisions.gate import GateResult
from flooreplay.decisions.policy import DEFAULT_POLICY_V1, PolicyDocument
from flooreplay.decisions.types import (
    ConstraintId,
    ConstraintStatus,
    Fact,
    FactKind,
    GateState,
    Quantity,
    SourceProfile,
    Unit,
)

PASS = ConstraintStatus.PASS
FAIL = ConstraintStatus.FAIL
NE = ConstraintStatus.NOT_EVALUATED

FABRIC = ConstraintId.FABRIC
SAFETY = ConstraintId.SAFETY
TRIMS = ConstraintId.TRIMS
CAPACITY = ConstraintId.CAPACITY
OVERTIME = ConstraintId.OVERTIME
APPROVAL = ConstraintId.APPROVAL

DAY1 = date(2026, 3, 10)
DAY2 = date(2026, 3, 11)
DAY3 = date(2026, 3, 12)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def run(world: World) -> tuple[ConstraintResult, ...]:
    return evaluate_constraints(world.snapshot(), world.order_id, world.policy, world.gate())


def one(
    results: Iterable[ConstraintResult], constraint: ConstraintId, subject: str
) -> ConstraintResult:
    [found] = [r for r in results if r.constraint == constraint and r.subject == subject]
    return found


def steps_of(result: ConstraintResult) -> dict[str, Step]:
    labels = [s.label for s in result.steps]
    assert len(labels) == len(set(labels)), labels
    return {s.label: s for s in result.steps}


def values(result: ConstraintResult) -> dict[str, str]:
    return {s.label: s.value for s in result.steps}


def qty(value: str, unit: Unit) -> Quantity:
    return Quantity(value=Decimal(value), unit=unit)


def policy_with(**capacity: Any) -> PolicyDocument:
    data = DEFAULT_POLICY_V1.model_dump(mode="json")
    data["capacity"].update(capacity)
    return PolicyDocument.model_validate(data)


def policy_enabling(*constraints: ConstraintId) -> PolicyDocument:
    data = DEFAULT_POLICY_V1.model_dump(mode="json")
    data["enabled_constraints"] = [c.value for c in constraints]
    return PolicyDocument.model_validate(data)


def capacity_world(
    minutes: str = "100",
    *,
    efficiency: Callable[[str], str | None] | None = None,
    base: World | None = None,
) -> World:
    """ready_world with every line-day set to `minutes` (and efficiency per line, if given)."""
    world = (base or ready_world()).without(kind=FactKind.LINE_CAPACITY)
    facts = [
        capacity_fact(
            f"cap-{line}-{day.isoformat()}",
            line,
            day,
            minutes,
            efficiency=efficiency(line) if efficiency else None,
        )
        for line in world.policy.capacity.eligible_lines
        for day in working_days(world.policy, SHIP_DATE)
    ]
    return world.with_facts(*facts)


def metre_world(navy_kg: str = "100", gsm: str = "180", width: str = "1.8") -> World:
    """BOM in metres (1.5 m/pc); both lots in kg with GSM and width."""
    return (
        ready_world()
        .without(kind=FactKind.BOM)
        .without(kind=FactKind.FABRIC_LOT)
        .with_facts(
            bom_fact(unit="m", consumption="1.5"),
            lot_fact("lot-n", "LOT-N1", "NAVY", navy_kg, gsm=gsm, width_m=width),
            lot_fact("lot-w", "LOT-W1", "WHITE", "300", gsm=gsm, width_m=width),
        )
    )


# ---------------------------------------------------------------------------
# The READY baseline and result shape
# ---------------------------------------------------------------------------


def test_the_ready_world_passes_everything_and_omits_overtime() -> None:
    results = run(ready_world())
    assert [(r.constraint, r.subject, r.status) for r in results] == [
        (FABRIC, "NAVY", PASS),
        (FABRIC, "WHITE", PASS),
        (SAFETY, "NAVY", PASS),
        (SAFETY, "WHITE", PASS),
        (TRIMS, "LABEL", PASS),
        (TRIMS, "ZIP", PASS),
        (CAPACITY, "order", PASS),
        (APPROVAL, "order", PASS),
    ]
    assert not [r for r in results if r.constraint == OVERTIME]


def test_results_are_frozen_models_with_sorted_fact_ids() -> None:
    for result in run(ready_world()):
        assert list(result.fact_ids) == sorted(result.fact_ids)
        assert isinstance(result.steps, tuple)
        with pytest.raises(Exception):  # noqa: B017 - pydantic frozen error
            result.status = FAIL  # type: ignore[misc]


def test_only_enabled_constraints_are_returned() -> None:
    results = run(ready_world().with_policy(policy_enabling(APPROVAL, TRIMS)))
    assert [(r.constraint, r.subject) for r in results] == [
        (TRIMS, "LABEL"),
        (TRIMS, "ZIP"),
        (APPROVAL, "order"),
    ]


# ---------------------------------------------------------------------------
# FABRIC
# ---------------------------------------------------------------------------


def navy_example() -> World:
    # NAVY lot 500, a QC claim of 50, 200 inbound on time, 120 held for another order.
    return ready_world().with_facts(
        qc_fact("qc-1", "LOT-N1", "50"),
        inbound_fact("ib-1", "IB1", "NAVY", "200", eta=date(2026, 3, 6)),
        allocation_fact("al-o2", "O2", "NAVY", "120"),
    )


def test_fabric_worked_example() -> None:
    result = one(run(navy_example()), FABRIC, "NAVY")
    # req         = 600 x 0.35 x (1 + 0.05) = 210 x 1.05 = 220.5 kg
    # usable lot  = 500 - 50                = 450 kg
    # inbound     = 200 (eta 03-06 <= 03-07)
    # committed   = 120 (O2)
    # free        = 450 + 200 - 120         = 530 kg
    # margin      = 530 - 220.5             = 309.5 kg  => PASS
    assert result.status is PASS
    assert [s.label for s in result.steps] == [
        "required",
        "usable:lot:LOT-N1",
        "usable_onhand",
        "inbound",
        "committed",
        "free",
        "margin",
    ]
    by = steps_of(result)
    assert (by["required"].expression, by["required"].value) == (
        "600 pcs × 0.35 kg/pc × (1 + 0.05)",
        "220.5 kg",
    )
    assert (by["usable:lot:LOT-N1"].expression, by["usable:lot:LOT-N1"].value) == (
        "500 − 50",
        "450 kg",
    )
    assert by["usable_onhand"].value == "450 kg"
    assert by["inbound"].value == "200 kg"
    assert by["committed"].value == "120 kg"
    assert (by["free"].expression, by["free"].value) == ("450 + 200 − 120", "530 kg")
    assert (by["margin"].expression, by["margin"].value) == ("530 − 220.5", "309.5 kg")
    assert result.fact_ids == tuple(
        sorted(["w-order", "w-bom", "w-lot-navy", "qc-1", "ib-1", "al-o2"])
    )
    assert result.required == qty("220.5", Unit.KG)
    assert result.available == qty("530", Unit.KG)
    assert result.pending_review_fact_ids == ()
    assert result.consumed_by == ()


def test_fabric_fails_when_free_is_below_required_and_pass_is_inclusive() -> None:
    # Exactly the requirement passes: lot 220.5 = req 220.5.
    exact = ready_world().without(entity_key="lot:LOT-N1").with_facts(
        lot_fact("lot-n", "LOT-N1", "NAVY", "220.5")
    )
    assert one(run(exact), FABRIC, "NAVY").status is PASS
    short = ready_world().without(entity_key="lot:LOT-N1").with_facts(
        lot_fact("lot-n", "LOT-N1", "NAVY", "220.499")
    )
    failing = one(run(short), FABRIC, "NAVY")
    assert failing.status is FAIL
    assert values(failing)["margin"] == "-0.001 kg"


def test_the_requirement_rounds_up_to_a_thousandth() -> None:
    # 1 pc x 0.333 x 1.05 = 0.34965 -> CEILING 0.350
    world = (
        ready_world()
        .without(kind=FactKind.ORDER_REQUEST)
        .without(kind=FactKind.BOM)
        .with_facts(
            order_fact(colours=(("NAVY", 1), ("WHITE", 1))),
            bom_fact(consumption="0.333"),
        )
    )
    assert values(one(run(world), FABRIC, "NAVY"))["required"] == "0.35 kg"


def test_fabric_adds_every_lot_of_the_colour_and_ignores_other_qualities_and_colours() -> None:
    world = ready_world().with_facts(
        lot_fact("lot-n2", "LOT-N2", "NAVY", "100"),
        lot_fact("lot-x", "LOT-X", "NAVY", "9999", quality="OTHER"),
        lot_fact("lot-w2", "LOT-W2", "WHITE", "7777"),
    )
    result = one(run(world), FABRIC, "NAVY")
    assert values(result)["usable_onhand"] == "600 kg"
    assert "lot-x" not in result.fact_ids and "lot-w2" not in result.fact_ids
    assert steps_of(result)["usable_onhand"].expression == "500 + 100"


def test_inbound_boundary_is_inclusive_on_cut_date_minus_the_buffer() -> None:
    # cut_date 2026-03-09 - 2 d = 2026-03-07: ETA on the day counts, a day later does not.
    world = ready_world().with_facts(
        inbound_fact("ib-in", "IB1", "NAVY", "10", eta=date(2026, 3, 7)),
        inbound_fact("ib-out", "IB2", "NAVY", "1000", eta=date(2026, 3, 8)),
    )
    result = one(run(world), FABRIC, "NAVY")
    assert values(result)["inbound"] == "10 kg"
    assert values(result)["free"] == "510 kg"
    assert "inbound:IB2" in steps_of(result)["inbound"].expression
    assert {"ib-in", "ib-out"} <= set(result.fact_ids)


def test_inbound_for_another_colour_or_quality_is_not_counted() -> None:
    world = ready_world().with_facts(
        inbound_fact("ib-w", "IB1", "WHITE", "50"),
        make_inbound_other_quality(),
    )
    assert values(one(run(world), FABRIC, "NAVY"))["inbound"] == "0 kg"
    assert values(one(run(world), FABRIC, "WHITE"))["inbound"] == "50 kg"


def make_inbound_other_quality() -> Fact:
    return inbound_fact("ib-q", "IB2", "NAVY", "50").model_copy(
        update={"payload": {**inbound_fact("x", "IB2").payload, "fabric_quality": "OTHER"}}
    )


def test_allocations_for_this_order_are_excluded_and_other_orders_are_subtracted() -> None:
    world = ready_world().with_facts(
        allocation_fact("al-own", "O1", "NAVY", "300"),
        allocation_fact("al-o2", "O2", "NAVY", "120"),
        allocation_fact("al-o3", "O3", "NAVY", "30"),
        allocation_fact("al-o2-white", "O2", "WHITE", "99"),
        allocation_fact("al-o2-q", "O2", "NAVY", "55", quality="OTHER"),
    )
    result = one(run(world), FABRIC, "NAVY")
    assert values(result)["committed"] == "150 kg"  # 120 + 30
    assert values(result)["free"] == "350 kg"  # 500 + 0 - 150
    assert {"al-o2", "al-o3"} <= set(result.fact_ids)
    assert not {"al-own", "al-o2-white", "al-o2-q"} & set(result.fact_ids)


def test_a_qc_claim_is_subtracted_only_in_trusted_review_states() -> None:
    def usable(state: str) -> tuple[str, tuple[str, ...]]:
        world = ready_world().with_facts(qc_fact("qc-1", "LOT-N1", "50", review_state=state))
        result = one(run(world), FABRIC, "NAVY")
        return values(result)["usable_onhand"], result.pending_review_fact_ids

    assert usable("checks_passed") == ("450 kg", ())
    assert usable("confirmed") == ("450 kg", ())
    # needs_review cannot be trusted: not subtracted, but surfaced for T9.
    assert usable("needs_review") == ("500 kg", ("qc-1",))
    # corrected and rejected are human outcomes outside the formula's two states.
    assert usable("corrected") == ("500 kg", ())
    assert usable("rejected") == ("500 kg", ())


def test_a_needs_review_claim_is_surfaced_on_fabric_and_safety_of_its_colour_only() -> None:
    world = ready_world().with_facts(qc_fact("qc-1", "LOT-N1", "50", review_state="needs_review"))
    results = run(world)
    assert one(results, FABRIC, "NAVY").pending_review_fact_ids == ("qc-1",)
    assert one(results, SAFETY, "NAVY").pending_review_fact_ids == ("qc-1",)
    assert one(results, FABRIC, "WHITE").pending_review_fact_ids == ()
    assert "qc-1" in one(results, FABRIC, "NAVY").fact_ids


def test_several_qc_claims_on_a_lot_all_count() -> None:
    world = ready_world().with_facts(
        qc_fact("qc-1", "LOT-N1", "50"), qc_fact("qc-2", "LOT-N1", "20", issue="defect")
    )
    result = one(run(world), FABRIC, "NAVY")
    assert steps_of(result)["usable:lot:LOT-N1"].expression == "500 − 50 − 20"
    assert values(result)["usable_onhand"] == "430 kg"


def reviewed_world(**resolution: Any) -> World:
    # Lot 500 with a 200 kg QC claim => 300 by the formula; a reviewer says 480 are usable.
    return ready_world().with_facts(
        qc_fact("qc-1", "LOT-N1", "200"),
        resolution_fact(
            "res-1",
            "lot:LOT-N1",
            rule_id="qc_claims_against_lot",
            left_fact_id="w-lot-navy",
            right_fact_id="qc-1",
            usable_qty=kg("480"),
            **resolution,
        ),
    )


def test_a_resolution_usable_qty_replaces_the_lots_usable_amount() -> None:
    result = one(run(reviewed_world()), FABRIC, "NAVY")
    assert values(result)["usable:lot:LOT-N1"] == "480 kg"
    assert values(result)["usable_onhand"] == "480 kg"
    assert "res-1" in result.fact_ids


def test_a_resolution_counts_only_from_its_own_known_at() -> None:
    later = reviewed_world(known_at=CUTOFF.replace(hour=11))
    assert values(one(run(later), FABRIC, "NAVY"))["usable_onhand"] == "300 kg"


def test_only_a_review_queue_resolution_replaces_a_lot() -> None:
    other = reviewed_world(source=SourceProfile.NOTES)
    assert values(one(run(other), FABRIC, "NAVY"))["usable_onhand"] == "300 kg"


def test_the_newest_resolution_for_a_lot_wins() -> None:
    world = reviewed_world().with_facts(
        resolution_fact(
            "res-2",
            "lot:LOT-N1",
            rule_id="qc_claims_against_lot",
            left_fact_id="w-lot-navy",
            right_fact_id="qc-1",
            usable_qty=kg("410"),
            valid_from=AS_OF.replace(minute=30),
            known_at=AS_OF.replace(minute=40),
        )
    )
    assert values(one(run(world), FABRIC, "NAVY"))["usable_onhand"] == "410 kg"


def test_a_resolution_clears_the_pending_review_of_the_claim_it_names_only() -> None:
    def pending(right_fact_id: str) -> tuple[str, ...]:
        world = ready_world().with_facts(
            qc_fact("qc-1", "LOT-N1", "200", review_state="needs_review"),
            resolution_fact(
                "res-1",
                "lot:LOT-N1",
                rule_id="qc_claims_against_lot",
                left_fact_id="w-lot-navy",
                right_fact_id=right_fact_id,
                usable_qty=kg("480"),
            ),
        )
        result = one(run(world), FABRIC, "NAVY")
        assert values(result)["usable_onhand"] == "480 kg"
        return result.pending_review_fact_ids

    assert pending("qc-1") == ()
    assert pending("qc-other") == ("qc-1",)


def test_an_unreadable_resolution_usable_qty_is_not_evaluated() -> None:
    good = reviewed_world()
    broken = good.replace_fact(
        "res-1",
        payload={
            "rule_id": "qc_claims_against_lot",
            "left_fact_id": "w-lot-navy",
            "right_fact_id": "qc-1",
            "resolved_payload": {"usable_qty": "lots"},
            "reviewer": "owner",
        },
    )
    assert one(run(broken), FABRIC, "NAVY").status is NE
    assert one(run(broken), FABRIC, "WHITE").status is PASS


# -- known zeros, unknowns -------------------------------------------------------------


def test_a_covered_quality_with_no_lot_is_a_known_zero_and_fails() -> None:
    world = ready_world().without(entity_key="lot:LOT-N1")
    result = one(run(world), FABRIC, "NAVY")
    # usable 0, free 0, req 220.5 => margin -220.5
    assert result.status is FAIL
    assert values(result)["usable_onhand"] == "0 kg"
    assert values(result)["margin"] == "-220.5 kg"
    assert "artifact-erp-1" in result.detail


def test_inbound_can_make_up_a_known_zero() -> None:
    world = ready_world().without(entity_key="lot:LOT-N1").with_facts(
        inbound_fact("ib-1", "IB1", "NAVY", "300")
    )
    assert one(run(world), FABRIC, "NAVY").status is PASS


def test_no_lot_and_no_coverage_is_not_evaluated_never_zero() -> None:
    uncovered = ready_world().without(entity_key="lot:LOT-N1").with_coverage({})
    assert one(run(uncovered), FABRIC, "NAVY").status is NE
    other_quality = ready_world().without(entity_key="lot:LOT-N1").with_coverage(cover("OTHER"))
    assert one(run(other_quality), FABRIC, "NAVY").status is NE


def test_the_coverage_the_gate_used_is_what_counts() -> None:
    world = ready_world().without(entity_key="lot:LOT-N1")
    no_coverage = GateResult(state=GateState.READY, findings=(), coverage_used=None)
    results = evaluate_constraints(world.snapshot(), "O1", world.policy, no_coverage)
    assert one(results, FABRIC, "NAVY").status is NE
    assert one(results, SAFETY, "NAVY").status is NE
    assert one(results, FABRIC, "WHITE").status is PASS


def test_a_tie_between_lot_observations_is_not_evaluated_for_that_colour() -> None:
    world = ready_world().with_facts(lot_fact("lot-dup", "LOT-N1", "NAVY", "400"))
    results = run(world)
    assert one(results, FABRIC, "NAVY").status is NE
    assert set(one(results, FABRIC, "NAVY").fact_ids) >= {"w-lot-navy", "lot-dup"}
    assert one(results, FABRIC, "WHITE").status is PASS


def test_a_missing_order_makes_every_constraint_not_evaluated() -> None:
    results = run(ready_world().without(kind=FactKind.ORDER_REQUEST))
    assert [(r.constraint, r.subject, r.status) for r in results] == [
        (FABRIC, "order", NE),
        (SAFETY, "order", NE),
        (TRIMS, "order", NE),
        (CAPACITY, "order", NE),
        (APPROVAL, "order", NE),
    ]


def test_a_missing_bom_leaves_approval_and_makes_the_rest_not_evaluated() -> None:
    results = run(ready_world().without(kind=FactKind.BOM))
    assert [(r.constraint, r.subject, r.status) for r in results] == [
        (FABRIC, "NAVY", NE),
        (FABRIC, "WHITE", NE),
        (SAFETY, "NAVY", NE),
        (SAFETY, "WHITE", NE),
        (TRIMS, "order", NE),
        (CAPACITY, "order", NE),
        (APPROVAL, "order", PASS),
    ]


# -- kg <-> m ---------------------------------------------------------------------------


def test_kg_lots_are_converted_to_the_metre_unit_of_the_bom() -> None:
    result = one(run(metre_world("100")), FABRIC, "NAVY")
    # req = 600 x 1.5 x 1.05 = 945 m
    # 100 kg -> 100 x 1000 / (180 x 1.8) = 100000 / 324 = 308.6419... -> FLOOR 308.641 m
    assert values(result)["required"] == "945 m"
    assert values(result)["usable:lot:LOT-N1"] == "308.641 m"
    assert "100 kg" in steps_of(result)["usable:lot:LOT-N1"].expression
    assert result.status is FAIL
    assert result.required == qty("945", Unit.M)
    # 600 kg -> 600000 / 324 = 1851.851... -> 1851.851 m >= 945
    assert one(run(metre_world("600")), FABRIC, "NAVY").status is PASS


def test_metre_inbound_is_converted_to_kg_with_gsm_and_width_of_the_colours_lot() -> None:
    lot = lot_fact("lot-n", "LOT-N1", "NAVY", "500", gsm="185", width_m="1.83")
    world = (
        ready_world()
        .without(entity_key="lot:LOT-N1")
        .with_facts(lot, inbound_fact("ib-m", "IBM", "NAVY", "1000.1", unit="m"))
    )
    result = one(run(world), FABRIC, "NAVY")
    # 1000.1 m x 185 x 1.83 / 1000 = 1000.1 x 338.55 / 1000 = 338.583855 -> FLOOR 338.583 kg
    assert values(result)["inbound"] == "338.583 kg"
    assert "lot-n" in result.fact_ids


def test_deductions_round_up_and_supply_rounds_down() -> None:
    lot = lot_fact("lot-n", "LOT-N1", "NAVY", "500", gsm="185", width_m="1.83")
    world = (
        ready_world()
        .without(entity_key="lot:LOT-N1")
        .with_facts(lot, qc_fact("qc-m", "LOT-N1", "10.1", unit="m"))
    )
    # 10.1 m x 338.55 / 1000 = 3.419355 kg -> CEILING 3.420 kg (a deduction is conservative)
    # usable = 500 - 3.42 = 496.58
    assert values(one(run(world), FABRIC, "NAVY"))["usable:lot:LOT-N1"] == "496.58 kg"


def test_a_unit_mismatch_without_gsm_and_width_is_not_evaluated() -> None:
    world = metre_world().without(entity_key="lot:LOT-N1").with_facts(
        lot_fact("lot-n", "LOT-N1", "NAVY", "100")  # kg, but no gsm / width anywhere for NAVY
    )
    results = run(world)
    assert one(results, FABRIC, "NAVY").status is NE
    assert one(results, SAFETY, "NAVY").status is NE
    # WHITE: 300 kg -> 300000 / 324 = 925.925 m >= 400 x 1.5 x 1.05 = 630 m
    assert one(results, FABRIC, "WHITE").status is PASS


def test_gsm_without_width_is_not_enough() -> None:
    world = metre_world().without(entity_key="lot:LOT-N1").with_facts(
        lot_fact("lot-n", "LOT-N1", "NAVY", "100", gsm="180")
    )
    assert one(run(world), FABRIC, "NAVY").status is NE


def test_a_unit_mismatch_in_inbound_needs_factors_from_a_lot_of_the_colour() -> None:
    world = ready_world().with_facts(inbound_fact("ib-m", "IBM", "NAVY", "100", unit="m"))
    assert one(run(world), FABRIC, "NAVY").status is NE
    assert one(run(world), FABRIC, "WHITE").status is PASS


def test_a_unit_mismatch_in_a_qc_claim_or_allocation_needs_factors_too() -> None:
    qc = ready_world().with_facts(qc_fact("qc-m", "LOT-N1", "10", unit="m"))
    assert one(run(qc), FABRIC, "NAVY").status is NE
    alloc = ready_world().with_facts(allocation_fact("al-m", "O2", "NAVY", "10", unit="m"))
    assert one(run(alloc), FABRIC, "NAVY").status is NE


# ---------------------------------------------------------------------------
# SAFETY
# ---------------------------------------------------------------------------


def test_safety_worked_example_pass() -> None:
    result = one(run(navy_example()), SAFETY, "NAVY")
    # free 530, req 220.5 => margin 309.5
    # base  = usable_onhand + inbound = 450 + 200 = 650
    # floor = 0.05 x 650 = 32.5
    # headroom = 309.5 - 32.5 = 277 >= 0  => PASS
    assert result.status is PASS
    assert [s.label for s in result.steps] == ["free", "margin", "base", "floor", "headroom"]
    by = steps_of(result)
    assert (by["free"].expression, by["free"].value) == ("450 + 200 − 120", "530 kg")
    assert (by["margin"].expression, by["margin"].value) == ("530 − 220.5", "309.5 kg")
    assert (by["base"].expression, by["base"].value) == ("450 + 200", "650 kg")
    assert (by["floor"].expression, by["floor"].value) == ("0.05 × 650", "32.5 kg")
    assert (by["headroom"].expression, by["headroom"].value) == ("309.5 − 32.5", "277 kg")
    assert result.consumed_by == ()


def test_safety_fails_below_the_floor_and_names_the_allocations_that_consumed_stock() -> None:
    world = ready_world().with_facts(
        allocation_fact("al-o2", "O2", "NAVY", "200"),
        allocation_fact("al-o3", "O3", "NAVY", "60"),
        allocation_fact("al-o4", "O4", "WHITE", "10"),
    )
    results = run(world)
    # NAVY: free = 500 - 260 = 240; req 220.5 => FABRIC PASS (margin 19.5)
    # floor = 0.05 x 500 = 25; headroom = 19.5 - 25 = -5.5 => SAFETY FAIL
    assert one(results, FABRIC, "NAVY").status is PASS
    safety = one(results, SAFETY, "NAVY")
    assert safety.status is FAIL
    assert values(safety)["headroom"] == "-5.5 kg"
    assert safety.consumed_by == ("al-o2", "al-o3")
    # WHITE is untouched by NAVY's allocations; its own allocation shows only on WHITE.
    assert one(results, SAFETY, "WHITE").consumed_by == ()


def test_safety_floor_boundary_is_inclusive() -> None:
    # free - req == floor exactly: lot 500, alloc 254.5 => free 245.5, margin 25 = 0.05 x 500
    world = ready_world().with_facts(allocation_fact("al-o2", "O2", "NAVY", "254.5"))
    assert one(run(world), SAFETY, "NAVY").status is PASS
    world = ready_world().with_facts(allocation_fact("al-o2", "O2", "NAVY", "254.501"))
    assert one(run(world), SAFETY, "NAVY").status is FAIL


def test_safety_fails_when_fabric_fails_and_lists_the_consumers() -> None:
    world = ready_world().with_facts(allocation_fact("al-o2", "O2", "NAVY", "400"))
    results = run(world)
    assert one(results, FABRIC, "NAVY").status is FAIL
    safety = one(results, SAFETY, "NAVY")
    assert safety.status is FAIL
    assert safety.consumed_by == ("al-o2",)


def test_safety_can_be_enabled_without_fabric_and_is_not_evaluated_when_inputs_are_missing() -> None:
    world = ready_world().with_policy(policy_enabling(SAFETY))
    assert [(r.constraint, r.subject) for r in run(world)] == [(SAFETY, "NAVY"), (SAFETY, "WHITE")]
    bare = ready_world().without(entity_key="lot:LOT-N1").with_coverage({})
    results = run(bare.with_policy(policy_enabling(SAFETY)))
    assert one(results, SAFETY, "NAVY").status is NE


# ---------------------------------------------------------------------------
# TRIMS
# ---------------------------------------------------------------------------


def trims_world(label_on_hand: str, **kwargs: Any) -> World:
    return (
        ready_world()
        .without(entity_key="trim:S1:LABEL")
        .with_facts(trim_fact("t-label", "LABEL", label_on_hand, **kwargs))
    )


def test_trims_worked_example() -> None:
    result = one(run(ready_world()), TRIMS, "LABEL")
    # need = 1000 x 1 x (1 + 0.03) = 1030 pcs; on hand 100000
    assert result.status is PASS
    assert [s.label for s in result.steps] == ["need", "on_hand", "inbound", "available", "margin"]
    by = steps_of(result)
    assert (by["need"].expression, by["need"].value) == (
        "1000 pcs × 1 pcs/pc × (1 + 0.03)",
        "1030 pcs",
    )
    assert by["on_hand"].value == "100000 pcs"
    assert by["inbound"].value == "0 pcs"
    assert (by["available"].expression, by["available"].value) == (
        "100000 + 0",
        "100000 pcs",
    )
    assert by["margin"].value == "98970 pcs"
    assert result.fact_ids == ("w-bom", "w-order", "w-trim-LABEL")
    assert result.required == qty("1030", Unit.PCS)
    assert result.available == qty("100000", Unit.PCS)


def test_trims_boundary_and_failure() -> None:
    assert one(run(trims_world("1030")), TRIMS, "LABEL").status is PASS
    failing = one(run(trims_world("1029")), TRIMS, "LABEL")
    assert failing.status is FAIL
    assert values(failing)["margin"] == "-1 pcs"
    assert one(run(trims_world("1029")), TRIMS, "ZIP").status is PASS


def test_trims_inbound_in_time_makes_up_the_gap() -> None:
    # on hand 900 < need 1030; inbound 200 arriving 2026-03-07 (= cut 03-09 - 2 d) counts
    in_time = trims_world("900", inbound_qty="200", eta=date(2026, 3, 7))
    result = one(run(in_time), TRIMS, "LABEL")
    assert result.status is PASS
    assert values(result)["inbound"] == "200 pcs"
    assert values(result)["available"] == "1100 pcs"
    assert values(result)["margin"] == "70 pcs"


def test_trims_inbound_after_the_buffer_does_not_count() -> None:
    late = trims_world("900", inbound_qty="200", eta=date(2026, 3, 8))
    result = one(run(late), TRIMS, "LABEL")
    assert result.status is FAIL
    assert values(result)["inbound"] == "0 pcs"
    assert "2026-03-08" in steps_of(result)["inbound"].expression


def test_trims_inbound_without_an_eta_does_not_count() -> None:
    no_eta = trims_world("900", inbound_qty="200")
    assert one(run(no_eta), TRIMS, "LABEL").status is FAIL


def test_trims_buffer_comes_from_the_policy() -> None:
    data = DEFAULT_POLICY_V1.model_dump(mode="json")
    data["trims"]["buffer_days"] = 0  # cut-off becomes 2026-03-09
    policy = PolicyDocument.model_validate(data)
    world = trims_world("900", inbound_qty="200", eta=date(2026, 3, 8)).with_policy(policy)
    assert one(run(world), TRIMS, "LABEL").status is PASS


def test_a_missing_trim_status_is_not_evaluated_for_that_trim_only() -> None:
    results = run(ready_world().without(entity_key="trim:S1:ZIP"))
    assert one(results, TRIMS, "ZIP").status is NE
    assert one(results, TRIMS, "LABEL").status is PASS


# ---------------------------------------------------------------------------
# CAPACITY
# ---------------------------------------------------------------------------


def test_capacity_worked_example_pass() -> None:
    result = one(run(ready_world()), CAPACITY, "order")
    # total SAM = 1000 x 12.5 = 12500 min; efficiency (default) 0.55
    # required  = 12500 / 0.55 = 22727.2727... -> CEILING 22727.273
    # available = 4 lines x 15 days x 3000 = 180000
    # margin    = 180000 - 22727.273 = 157272.727
    assert result.status is PASS
    assert [s.label for s in result.steps] == [
        "sam_total",
        "efficiency",
        "required",
        "window",
        "available:L1",
        "available:L2",
        "available:L3",
        "available:L4",
        "available",
        "margin",
    ]
    by = steps_of(result)
    assert (by["sam_total"].expression, by["sam_total"].value) == (
        "1000 pcs × 12.5 min",
        "12500 minutes",
    )
    assert by["efficiency"].value == "0.55"
    assert (by["required"].expression, by["required"].value) == (
        "12500 / 0.55",
        "22727.273 minutes",
    )
    assert by["window"].value == "15 days"
    assert by["available:L1"].value == "45000 minutes"
    assert by["available"].value == "180000 minutes"
    assert by["margin"].value == "157272.727 minutes"
    assert result.required == qty("22727.273", Unit.MINUTES)
    assert result.available == qty("180000", Unit.MINUTES)
    assert result.overtime is None


def test_capacity_fact_ids_cover_the_order_bom_and_every_line_day() -> None:
    result = one(run(ready_world()), CAPACITY, "order")
    assert len(result.fact_ids) == 2 + 4 * 15
    assert {"w-order", "w-bom", "w-cap-L1-2026-03-10"} <= set(result.fact_ids)


def test_capacity_boundary_available_equals_required_passes() -> None:
    # Efficiency 0.5 and SAM 10: required = 1000 x 10 / 0.5 = 20000 minutes exactly.
    # 60 line-days (4 lines x 15 days) at 333.334 give 20000.04 >= 20000; at 333.333 19999.98.
    data = DEFAULT_POLICY_V1.model_dump(mode="json")
    data["capacity"]["default_efficiency_pct"] = "0.5"
    policy = PolicyDocument.model_validate(data)
    base = ready_world(policy=policy).without(kind=FactKind.BOM).with_facts(bom_fact(sam_minutes="10"))
    passing = one(run(capacity_world("333.334", base=base)), CAPACITY, "order")
    assert passing.status is PASS
    assert values(passing)["required"] == "20000 minutes"
    assert one(run(capacity_world("333.333", base=base)), CAPACITY, "order").status is FAIL


def test_capacity_window_excludes_sundays_holidays_and_extra_weekdays() -> None:
    sunday = capacity_fact("cap-sun", "L1", date(2026, 3, 15), "99999")
    assert values(one(run(ready_world().with_facts(sunday)), CAPACITY, "order"))["window"] == (
        "15 days"
    )
    assert values(one(run(ready_world().with_facts(sunday)), CAPACITY, "order"))["available"] == (
        "180000 minutes"
    )
    # A holiday on Wednesday 03-11 leaves 14 days.
    holiday = ready_world(policy=policy_with(holidays=["2026-03-11"]))
    result = one(run(holiday), CAPACITY, "order")
    assert values(result)["window"] == "14 days"
    assert values(result)["available"] == "168000 minutes"  # 4 x 14 x 3000
    # Saturdays off as well: 03-14 and 03-21 go too.
    weekend = ready_world(policy=policy_with(non_working_weekdays=["SAT", "SUN"]))
    assert values(one(run(weekend), CAPACITY, "order"))["window"] == "13 days"


def test_capacity_subtracts_commitments_of_other_orders_floored_at_zero_per_line_day() -> None:
    world = capacity_world("100").with_facts(
        commitment_fact("c1", "O2", "L1", DAY1, "500"),  # 100 - 500 -> floored: free 0 (-100)
        commitment_fact("c2", "O3", "L2", DAY2, "40"),  # free 60 (-40)
        commitment_fact("c3a", "O2", "L4", DAY3, "30"),  # two orders on one line-day:
        commitment_fact("c3b", "O3", "L4", DAY3, "30"),  # free 40 (-60)
        commitment_fact("c-own", "O1", "L3", DAY1, "50"),  # this order's own: ignored
    )
    result = one(run(world), CAPACITY, "order")
    # available = 4 x 15 x 100 - 100 - 40 - 60 = 5800
    assert values(result)["available"] == "5800 minutes"
    assert values(result)["available:L1"] == "1400 minutes"
    assert values(result)["available:L3"] == "1500 minutes"
    assert {"c1", "c2", "c3a", "c3b"} <= set(result.fact_ids)
    assert "c-own" not in result.fact_ids


def test_capacity_failure_and_the_default_efficiency() -> None:
    result = one(run(capacity_world("100")), CAPACITY, "order")
    # available = 4 x 15 x 100 = 6000 < required 22727.273
    assert result.status is FAIL
    assert values(result)["available"] == "6000 minutes"
    assert values(result)["margin"] == "-16727.273 minutes"


def test_efficiency_is_the_free_minute_weighted_average_when_every_line_day_gives_it() -> None:
    world = capacity_world("100", efficiency=lambda line: "0.8" if line in ("L1", "L2") else "0.4")
    result = one(run(world), CAPACITY, "order")
    # free minutes 15 x 100 per line = 1500; E = sum(free x eff) = 1500 x (0.8+0.8+0.4+0.4) = 3600
    # A = 6000; efficiency = E / A = 0.6
    # required = 12500 x A / E = 12500 x 6000 / 3600 = 20833.333... -> CEILING 20833.334
    by = steps_of(result)
    assert by["efficiency"].value == "0.6"
    assert by["efficiency"].expression == "3600 / 6000"
    assert (by["required"].expression, by["required"].value) == (
        "12500 / (3600 / 6000)",
        "20833.334 minutes",
    )
    assert values(result)["margin"] == "-14833.334 minutes"
    assert result.status is FAIL


def test_efficiency_weights_are_free_minutes_after_commitments() -> None:
    world = capacity_world(
        "100", efficiency=lambda line: "0.8" if line in ("L1", "L2") else "0.4"
    ).with_facts(
        commitment_fact("c1", "O2", "L1", DAY1, "100"),  # L1 day 1 is full: free 0
        commitment_fact("c2", "O3", "L3", DAY2, "50"),  # L3 day 2: free 50
    )
    result = one(run(world), CAPACITY, "order")
    # free: L1 1400, L2 1500, L3 1450, L4 1500 => A = 5850
    # E = 1400 x 0.8 + 1500 x 0.8 + 1450 x 0.4 + 1500 x 0.4 = 1120 + 1200 + 580 + 600 = 3500
    # required = 12500 x 5850 / 3500 = 20892.857142... -> CEILING 20892.858
    by = steps_of(result)
    assert by["efficiency"].expression == "3500 / 5850"
    assert by["required"].value == "20892.858 minutes"


def test_one_line_day_without_efficiency_falls_back_to_the_default_for_all() -> None:
    world = capacity_world("100", efficiency=lambda line: "0.8").without(
        entity_key="line:L1:2026-03-10"
    ).with_facts(capacity_fact("cap-no-eff", "L1", DAY1, "100"))
    by = steps_of(one(run(world), CAPACITY, "order"))
    assert by["efficiency"].value == "0.55"
    assert by["required"].value == "22727.273 minutes"


def test_an_efficiency_that_is_not_a_fraction_is_not_evaluated() -> None:
    world = capacity_world("100", efficiency=lambda line: "55")
    assert one(run(world), CAPACITY, "order").status is NE


def test_a_missing_line_day_makes_capacity_not_evaluated_and_omits_overtime() -> None:
    results = run(ready_world().without(entity_key="line:L2:2026-03-12"))
    assert one(results, CAPACITY, "order").status is NE
    assert not [r for r in results if r.constraint == OVERTIME]


def test_a_conflicting_commitment_makes_capacity_not_evaluated() -> None:
    world = capacity_world("100").with_facts(
        commitment_fact("c1", "O2", "L1", DAY1, "5"), commitment_fact("c2", "O2", "L1", DAY1, "6")
    )
    assert one(run(world), CAPACITY, "order").status is NE


def test_commitments_outside_the_window_or_the_eligible_lines_are_ignored() -> None:
    world = capacity_world("100").with_facts(
        commitment_fact("c-out", "O2", "L1", date(2026, 3, 9), "100"),
        commitment_fact("c-line", "O2", "L9", DAY1, "100"),
    )
    result = one(run(world), CAPACITY, "order")
    assert values(result)["available"] == "6000 minutes"
    assert not {"c-out", "c-line"} & set(result.fact_ids)


# ---------------------------------------------------------------------------
# OVERTIME
# ---------------------------------------------------------------------------


def test_overtime_worked_example_fail() -> None:
    results = run(capacity_world("100"))
    capacity = one(results, CAPACITY, "order")
    overtime = one(results, OVERTIME, "order")
    # shortfall = 22727.273 - 6000 = 16727.273
    # ot_available = 4 lines x 15 days x 2 h x 60 = 7200 < shortfall => FAIL
    # hours = ceil(16727.273 / (4 x 15 x 60)) = ceil(4.646) = 5
    assert capacity.status is FAIL
    assert overtime.status is FAIL
    assert [s.label for s in overtime.steps] == ["shortfall", "ot_available", "hours_per_line_per_day"]
    by = steps_of(overtime)
    assert (by["shortfall"].expression, by["shortfall"].value) == (
        "22727.273 − 6000",
        "16727.273 minutes",
    )
    assert (by["ot_available"].expression, by["ot_available"].value) == (
        "4 lines × 15 days × 2 h × 60",
        "7200 minutes",
    )
    assert (by["hours_per_line_per_day"].expression, by["hours_per_line_per_day"].value) == (
        "ceil(16727.273 / (4 × 15 × 60))",
        "5 hours",
    )
    assert overtime.overtime is not None
    assert (
        overtime.overtime.lines,
        overtime.overtime.days,
        overtime.overtime.cap_hours_per_line_day,
        overtime.overtime.hours_per_line_per_day,
    ) == (4, 15, 2, 5)
    assert set(overtime.fact_ids) == set(capacity.fact_ids)


def test_overtime_passes_when_the_shortfall_is_curable_and_states_the_hours() -> None:
    results = run(capacity_world("340"))
    # available = 4 x 15 x 340 = 20400; shortfall = 22727.273 - 20400 = 2327.273 <= 7200
    # hours = ceil(2327.273 / 3600) = ceil(0.646) = 1
    overtime = one(results, OVERTIME, "order")
    assert one(results, CAPACITY, "order").status is FAIL
    assert overtime.status is PASS
    assert values(overtime)["shortfall"] == "2327.273 minutes"
    assert values(overtime)["hours_per_line_per_day"] == "1 hours"
    assert overtime.overtime is not None
    assert (overtime.overtime.lines, overtime.overtime.days) == (4, 15)
    assert overtime.overtime.hours_per_line_per_day == 1


def test_overtime_hours_are_a_ceiling_and_agree_with_the_cap() -> None:
    # shortfall exactly 7200 (cap 2 h): hours = 7200 / 3600 = 2 => PASS; 7200.001 => 3 hours, FAIL.
    base = ready_world().without(kind=FactKind.BOM).with_facts(bom_fact(sam_minutes="12.5"))
    # required is 22727.273; choose minutes so that available = 22727.273 - 7200 = 15527.273
    # which is not a multiple of 60 line-days, so use the threshold on either side instead.
    below = one(run(capacity_world("259", base=base)), OVERTIME, "order")
    # available 4 x 15 x 259 = 15540 => shortfall 7187.273 <= 7200 => PASS, hours ceil(1.996) = 2
    assert below.status is PASS and below.overtime is not None
    assert below.overtime.hours_per_line_per_day == 2
    above = one(run(capacity_world("258.7", base=base)), OVERTIME, "order")
    # available 4 x 15 x 258.7 = 15522 => shortfall 7205.273 > 7200 => FAIL, hours ceil(2.001) = 3
    assert above.status is FAIL and above.overtime is not None
    assert above.overtime.hours_per_line_per_day == 3


def test_overtime_is_omitted_when_capacity_passes() -> None:
    assert not [r for r in run(ready_world()) if r.constraint == OVERTIME]


def test_overtime_with_no_working_days_does_not_divide_by_zero() -> None:
    policy = policy_with(
        non_working_weekdays=["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
    )
    results = run(ready_world(policy=policy))
    capacity = one(results, CAPACITY, "order")
    assert (capacity.status, values(capacity)["window"]) == (FAIL, "0 days")
    overtime = one(results, OVERTIME, "order")
    assert overtime.status is FAIL
    assert overtime.overtime is not None
    assert overtime.overtime.hours_per_line_per_day is None


def test_overtime_cap_comes_from_the_policy() -> None:
    results = run(capacity_world("340", base=ready_world(policy=policy_with(ot_cap_hours_per_line_day=0))))
    assert one(results, OVERTIME, "order").status is FAIL
    assert values(one(results, OVERTIME, "order"))["ot_available"] == "0 minutes"


# ---------------------------------------------------------------------------
# APPROVAL
# ---------------------------------------------------------------------------


def approval_world(value: str, navy: int, white: int) -> World:
    return ready_world().without(kind=FactKind.ORDER_REQUEST).with_facts(
        order_fact(order_value=value, colours=(("NAVY", navy), ("WHITE", white)))
    )


def test_approval_worked_example() -> None:
    result = one(run(ready_world()), APPROVAL, "order")
    # 2500000 <= 5000000 and 1000 <= 20000
    assert result.status is PASS
    by = steps_of(result)
    assert (by["value"].expression, by["value"].value) == ("2500000 <= 5000000", "2500000 INR")
    assert (by["quantity"].expression, by["quantity"].value) == ("1000 <= 20000", "1000 pcs")
    assert result.fact_ids == ("w-order",)


def test_approval_both_limits_are_inclusive() -> None:
    assert one(run(approval_world("5000000", 12000, 8000)), APPROVAL, "order").status is PASS


def test_approval_fails_on_value_alone() -> None:
    result = one(run(approval_world("5000001", 100, 100)), APPROVAL, "order")
    assert result.status is FAIL
    assert "value" in result.detail and "quantity" not in result.detail


def test_approval_fails_on_quantity_alone() -> None:
    result = one(run(approval_world("1000", 12000, 8001)), APPROVAL, "order")
    assert result.status is FAIL
    assert "quantity" in result.detail and "value" not in result.detail


def test_approval_fails_on_both() -> None:
    result = one(run(approval_world("5000001", 12000, 8001)), APPROVAL, "order")
    assert result.status is FAIL
    assert "value" in result.detail and "quantity" in result.detail


# ---------------------------------------------------------------------------
# Determinism and purity
# ---------------------------------------------------------------------------


def busy_world() -> World:
    return ready_world().with_facts(
        qc_fact("qc-1", "LOT-N1", "50"),
        qc_fact("qc-2", "LOT-W1", "20", review_state="needs_review"),
        inbound_fact("ib-1", "IB1", "NAVY", "200"),
        inbound_fact("ib-2", "IB2", "WHITE", "80", eta=date(2026, 3, 20)),
        allocation_fact("al-o2", "O2", "NAVY", "120"),
        allocation_fact("al-own", "O1", "WHITE", "10"),
        commitment_fact("c1", "O2", "L1", DAY1, "500"),
        commitment_fact("c2", "O3", "L2", DAY2, "40"),
        resolution_fact(
            "res-1",
            "lot:LOT-W1",
            rule_id="qc_claims_against_lot",
            left_fact_id="w-lot-white",
            right_fact_id="qc-2",
            usable_qty=kg("250"),
        ),
    )


def dump(results: tuple[ConstraintResult, ...]) -> list[dict[str, Any]]:
    return [r.model_dump(mode="json") for r in results]


def test_shuffled_facts_give_identical_results() -> None:
    world = busy_world()
    expected = dump(run(world))
    facts = list(world.facts)
    for seed in range(8):
        random.Random(seed).shuffle(facts)
        shuffled = World(facts=tuple(facts))
        assert dump(run(shuffled)) == expected


BUSY_FACTS = list(busy_world().facts)
BUSY_EXPECTED = dump(run(busy_world()))


@given(st.permutations(BUSY_FACTS))
@settings(deadline=None, max_examples=25)
def test_any_permutation_of_the_facts_gives_identical_results(facts: list[Fact]) -> None:
    assert dump(run(World(facts=tuple(facts)))) == BUSY_EXPECTED


def test_the_result_order_is_constraint_enum_order_then_subject() -> None:
    results = run(busy_world())
    order = {c: i for i, c in enumerate(ConstraintId)}
    keys = [(order[r.constraint], r.subject) for r in results]
    assert keys == sorted(keys)


def test_constraints_module_is_pure() -> None:
    source = Path(constraints_module.__file__ or "")
    tree = ast.parse(source.read_text())
    forbidden_modules = {"time", "random", "secrets", "uuid", "sqlalchemy", "os", "pathlib"}
    forbidden_prefixes = (
        "flooreplay.db",
        "flooreplay.models",
        "flooreplay.decisions.extraction",
        "flooreplay.config",
    )
    clock_names = {"now", "utcnow", "today", "time", "monotonic", "perf_counter"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] not in forbidden_modules, alias.name
                assert not alias.name.startswith(forbidden_prefixes), alias.name
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            assert module.split(".")[0] not in forbidden_modules, module
            assert not module.startswith(forbidden_prefixes), module
        elif isinstance(node, ast.Attribute):
            assert node.attr not in clock_names, f"uses .{node.attr}"
        elif isinstance(node, ast.Name):
            assert node.id not in {"now", "utcnow"}, f"uses {node.id}"


# ---------------------------------------------------------------------------
# Hypothesis: monotonicity
# ---------------------------------------------------------------------------

PROPERTY_POLICY = policy_with(cut_to_ship_days=7)
READY_GATE = GateResult(state=GateState.READY, findings=(), coverage_used=None)
MONOTONIC = (FABRIC, SAFETY, TRIMS, CAPACITY)
LINE_IDS = ("L1", "L2", "L3", "L4")


def quantity_text(places: int = 3, max_value: int = 2000) -> st.SearchStrategy[Decimal]:
    return st.decimals(min_value=0, max_value=max_value, places=places)


@dataclass(frozen=True)
class Scenario:
    """Everything the monotonicity properties vary, in a form `build` turns into a world."""

    qty_navy: int
    qty_white: int
    lot_navy1: Decimal
    lot_navy2: Decimal
    lot_white: Decimal
    qc_navy: Decimal
    inbound_navy: Decimal
    inbound_in_metres: bool
    alloc_navy: Decimal
    trim_label: Decimal
    trim_zip: Decimal
    trim_zip_inbound: Decimal
    minutes: tuple[Decimal, Decimal, Decimal, Decimal]
    committed_l1: Decimal
    committed_l3: Decimal
    efficiency: tuple[Decimal, Decimal, Decimal, Decimal] | None


@st.composite
def scenarios(draw: st.DrawFn) -> Scenario:
    efficiency = draw(
        st.none()
        | st.tuples(*[st.decimals(min_value="0.1", max_value=1, places=2)] * 4)
    )
    return Scenario(
        qty_navy=draw(st.integers(1, 3000)),
        qty_white=draw(st.integers(1, 3000)),
        lot_navy1=draw(quantity_text()),
        lot_navy2=draw(quantity_text()),
        lot_white=draw(quantity_text()),
        qc_navy=draw(quantity_text(max_value=300)),
        inbound_navy=draw(quantity_text()),
        inbound_in_metres=draw(st.booleans()),
        alloc_navy=draw(quantity_text(max_value=600)),
        trim_label=draw(quantity_text(places=0, max_value=4000)),
        trim_zip=draw(quantity_text(places=0, max_value=4000)),
        trim_zip_inbound=draw(quantity_text(places=0, max_value=2000)),
        minutes=draw(st.tuples(*[st.decimals(min_value=0, max_value=800, places=3)] * 4)),  # type: ignore[arg-type]
        committed_l1=draw(st.decimals(min_value=0, max_value=800, places=3)),
        committed_l3=draw(st.decimals(min_value=0, max_value=800, places=3)),
        efficiency=efficiency,  # type: ignore[arg-type]
    )


def build(s: Scenario) -> World:
    """A world with every varied input set from `s`. GSM 185 / width 1.83 on every lot.

    A short window (cut-to-ship 7 days: three sewing days, 12 line-days) keeps each example
    cheap; the worked examples above use the full default window.
    """
    gsm, width = "185", "1.83"
    facts: list[Fact] = [
        order_fact(colours=(("NAVY", s.qty_navy), ("WHITE", s.qty_white))),
        bom_fact(),
        lot_fact("lot-n1", "LOT-N1", "NAVY", str(s.lot_navy1), gsm=gsm, width_m=width),
        lot_fact("lot-n2", "LOT-N2", "NAVY", str(s.lot_navy2), gsm=gsm, width_m=width),
        lot_fact("lot-w1", "LOT-W1", "WHITE", str(s.lot_white), gsm=gsm, width_m=width),
        qc_fact("qc-1", "LOT-N1", str(s.qc_navy)),
        inbound_fact(
            "ib-1",
            "IB1",
            "NAVY",
            str(s.inbound_navy),
            unit="m" if s.inbound_in_metres else "kg",
            eta=date(2026, 3, 7),
        ),
        inbound_fact("ib-late", "IB2", "NAVY", "5000", eta=date(2026, 3, 22)),
        allocation_fact("al-o2", "O2", "NAVY", str(s.alloc_navy)),
        trim_fact("t-label", "LABEL", str(s.trim_label)),
        trim_fact(
            "t-zip", "ZIP", str(s.trim_zip), inbound_qty=str(s.trim_zip_inbound), eta=date(2026, 3, 7)
        ),
    ]
    # cut_date 2026-03-23, inbound cut-off 03-21, sewing 03-24 .. 03-26
    days = working_days(PROPERTY_POLICY, SHIP_DATE)
    assert len(days) == 3
    for index, line in enumerate(LINE_IDS):
        eff = None if s.efficiency is None else str(s.efficiency[index])
        for day in days:
            facts.append(
                capacity_fact(
                    f"cap-{line}-{day.isoformat()}", line, day, str(s.minutes[index]), efficiency=eff
                )
            )
    facts.append(commitment_fact("c-l1", "O2", "L1", days[0], str(s.committed_l1)))
    facts.append(commitment_fact("c-l3", "O3", "L3", days[1], str(s.committed_l3)))
    return World(facts=tuple(facts), policy=PROPERTY_POLICY)


def statuses(world: World) -> dict[tuple[ConstraintId, str], ConstraintStatus]:
    results = evaluate_constraints(world.snapshot(), world.order_id, world.policy, READY_GATE)
    return {(r.constraint, r.subject): r.status for r in results if r.constraint in MONOTONIC}


# Each operation adds `delta` to one supply-side input.
SUPPLY_OPERATIONS = (
    "lot_navy1",
    "lot_navy2",
    "lot_white",
    "inbound_navy",
    "trim_label",
    "trim_zip",
    "trim_zip_inbound",
    "minutes_0",
    "minutes_1",
    "minutes_2",
    "minutes_3",
)


def more_supply(s: Scenario, operation: str, delta: Decimal) -> Scenario:
    from dataclasses import replace

    if operation.startswith("minutes_"):
        index = int(operation.split("_")[1])
        minutes = list(s.minutes)
        minutes[index] += delta
        return replace(s, minutes=(minutes[0], minutes[1], minutes[2], minutes[3]))
    return replace(s, **{operation: getattr(s, operation) + delta})


@given(
    scenarios(),
    st.sampled_from(SUPPLY_OPERATIONS),
    st.decimals(min_value="0.001", max_value=3000, places=3),
)
@settings(deadline=None, max_examples=150)
def test_more_stock_inbound_trims_or_minutes_never_turns_pass_into_fail(
    scenario: Scenario, operation: str, delta: Decimal
) -> None:
    before = statuses(build(scenario))
    after = statuses(build(more_supply(scenario, operation, delta)))
    assert before.keys() == after.keys()
    for key, status in before.items():
        if status is PASS:
            assert after[key] is PASS, (key, operation, delta)


@given(
    scenarios(),
    st.sampled_from(("qty_navy", "qty_white", "both")),
    st.integers(1, 3000),
)
@settings(deadline=None, max_examples=150)
def test_more_quantity_never_turns_fail_into_pass(
    scenario: Scenario, which: str, extra: int
) -> None:
    from dataclasses import replace

    changes: dict[str, int] = {}
    if which in ("qty_navy", "both"):
        changes["qty_navy"] = scenario.qty_navy + extra
    if which in ("qty_white", "both"):
        changes["qty_white"] = scenario.qty_white + extra
    before = statuses(build(scenario))
    after = statuses(build(replace(scenario, **changes)))
    assert before.keys() == after.keys()
    for key, status in before.items():
        if status is FAIL:
            assert after[key] is not PASS, (key, which, extra)


@given(scenarios())
@settings(deadline=None, max_examples=100)
def test_the_generated_scenarios_always_have_real_verdicts(scenario: Scenario) -> None:
    # The strategy is not degenerate: nothing is NOT_EVALUATED, so the properties above
    # compare PASS and FAIL, never unknowns.
    assert all(s is not NE for s in statuses(build(scenario)).values())
