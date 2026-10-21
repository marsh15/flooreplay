"""ContextGate: required facts, per-entity freshness, conflicts, precedence, purity."""

from __future__ import annotations

import ast
import random
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from decisions.strategies import facts as fact_strategy
from decisions.worlds import (
    AS_OF,
    BOM_KEY,
    CUTOFF,
    ERP_ARTIFACT,
    ORDER_KEY,
    QUALITY,
    SHIP_DATE,
    World,
    bom_fact,
    capacity_fact,
    inbound_fact,
    lot_fact,
    qc_fact,
    ready_world,
    resolution_fact,
    trim_fact,
    working_days,
)
from flooreplay.decisions import gate as gate_module
from flooreplay.decisions import policy as policy_module
from flooreplay.decisions.gate import GateFinding, GateResult, evaluate_gate
from flooreplay.decisions.policy import DEFAULT_POLICY_V1, PolicyDocument
from flooreplay.decisions.snapshot import snapshot_at
from flooreplay.decisions.types import (
    Fact,
    FactKind,
    GateState,
    SourceProfile,
    combine_gate_states,
)

READY = GateState.READY
STALE = GateState.STALE
INCOMPLETE = GateState.INCOMPLETE
CONFLICTING = GateState.CONFLICTING

HOUR = timedelta(hours=1)
MINUTE = timedelta(minutes=1)


def base() -> World:
    return ready_world()


def codes(result: GateResult, state: GateState | None = None) -> set[str]:
    return {f.code for f in result.findings if state is None or f.state == state}


def finding(result: GateResult, code: str) -> GateFinding:
    [found] = [f for f in result.findings if f.code == code]
    return found


def policy_with(**capacity: Any) -> PolicyDocument:
    data = DEFAULT_POLICY_V1.model_dump(mode="json")
    data["capacity"].update(capacity)
    return PolicyDocument.model_validate(data)


def policy_with_freshness(**hours: int) -> PolicyDocument:
    data = DEFAULT_POLICY_V1.model_dump(mode="json")
    data["freshness_hours"].update(hours)
    return PolicyDocument.model_validate(data)


# ---------------------------------------------------------------------------
# The READY world
# ---------------------------------------------------------------------------


def test_the_ready_world_is_ready_with_nothing_to_report() -> None:
    result = base().gate()
    assert result.state is READY
    assert [f for f in result.findings if f.state is not READY] == []


def test_the_world_covers_exactly_the_sewing_window() -> None:
    # 2026-03-30 ship, 21 days cut-to-ship, 4 finishing: sewing 03-10 .. 03-26, Sundays off.
    days = working_days(DEFAULT_POLICY_V1, SHIP_DATE)
    assert days[0] == date(2026, 3, 10) and days[-1] == date(2026, 3, 26)
    assert all(d.weekday() != 6 for d in days) and len(days) == 15


def test_a_known_zero_lot_is_not_a_finding() -> None:
    world = base().replace_fact(
        "w-lot-white",
        payload={
            "fabric_quality": QUALITY,
            "colour": "WHITE",
            "qty": {"value": "0", "unit": "kg"},
        },
    )
    assert world.gate().state is READY


def test_gate_is_deterministic_and_input_order_independent() -> None:
    world = base().without(kind=FactKind.BOM).with_facts(lot_fact("x", "LOT-X", "NAVY", "1"))
    shuffled = list(world.facts)
    random.Random(7).shuffle(shuffled)
    again = World(facts=tuple(shuffled))
    assert world.gate() == world.gate() == again.gate()


# ---------------------------------------------------------------------------
# Freshness: per required entity, inclusive boundary, clock = cutoff
# ---------------------------------------------------------------------------

FRESHNESS_CASES = [
    # (fact id, entity_key, limit in hours)
    ("w-lot-navy", "lot:LOT-N1", 24),
    ("w-trim-ZIP", "trim:S1:ZIP", 48),
    ("w-cap-L2-2026-03-12", "line:L2:2026-03-12", 24),
    ("w-order", ORDER_KEY, 168),
    ("w-bom", BOM_KEY, 168),
]


@pytest.mark.parametrize(("fact_id", "entity_key", "limit"), FRESHNESS_CASES)
def test_freshness_boundary_is_inclusive(fact_id: str, entity_key: str, limit: int) -> None:
    at_limit = base().replace_fact(fact_id, valid_from=CUTOFF - limit * HOUR)
    assert at_limit.gate().state is READY, "age == limit is fresh"

    over = base().replace_fact(fact_id, valid_from=CUTOFF - limit * HOUR - MINUTE)
    result = over.gate()
    assert result.state is STALE
    stale = finding(result, "stale_evidence")
    assert stale.state is STALE
    assert stale.entity_key == entity_key
    assert stale.fact_ids == (fact_id,)
    assert str(limit) in stale.detail


def test_freshness_uses_the_policy_limit_for_the_facts_source() -> None:
    tight = policy_with_freshness(erp_fabric_stock=0)
    world = ready_world(tight)
    for lot in ("w-lot-navy", "w-lot-white"):
        world = world.replace_fact(lot, valid_from=CUTOFF, known_at=CUTOFF)
    assert world.gate().state is READY  # age 0 <= 0
    assert world.replace_fact("w-lot-navy", valid_from=CUTOFF - MINUTE).gate().state is STALE


def test_each_stale_entity_gets_its_own_finding() -> None:
    old = CUTOFF - 200 * HOUR
    world = base().replace_fact("w-lot-navy", valid_from=old).replace_fact(
        "w-trim-ZIP", valid_from=old
    )
    result = world.gate()
    keys = {f.entity_key for f in result.findings if f.code == "stale_evidence"}
    assert keys == {"lot:LOT-N1", "trim:S1:ZIP"}
    assert result.state is STALE


def test_review_queue_facts_are_exempt_from_freshness() -> None:
    world = base().replace_fact(
        "w-lot-navy", source=SourceProfile.REVIEW_QUEUE, valid_from=CUTOFF - 500 * HOUR
    )
    assert world.gate().state is READY


def test_an_older_observation_does_not_make_the_entity_stale() -> None:
    # Latest valid_from wins; the ancient first observation is history, not the current value.
    ancient = lot_fact(
        "w-lot-navy-old", "LOT-N1", "NAVY", "480", valid_from=CUTOFF - 900 * HOUR
    )
    assert base().with_facts(ancient).gate().state is READY


def test_the_clock_is_the_cutoff_not_the_wall_clock() -> None:
    world = base()
    assert world.gate(CUTOFF).state is READY
    # Same facts, 30 hours later: lots and capacity (24h limits) are stale; trims (48h) are not.
    later = world.gate(CUTOFF + 30 * HOUR)
    assert later.state is STALE
    stale_keys = {f.entity_key for f in later.findings if f.code == "stale_evidence"}
    assert "lot:LOT-N1" in stale_keys and "trim:S1:ZIP" not in stale_keys
    # And at exactly the limit for the oldest 24h-limit export (as_of is 1h before the cutoff).
    assert world.gate(CUTOFF + 23 * HOUR).state is READY
    assert world.gate(CUTOFF + 23 * HOUR + MINUTE).state is STALE


def test_a_cutoff_before_the_facts_were_known_sees_nothing() -> None:
    result = base().gate(CUTOFF - 20 * HOUR)
    assert result.state is INCOMPLETE
    assert "order_request_missing" in codes(result)


@pytest.mark.parametrize("path", ["gate.py", "policy.py"])
def test_pure_modules_have_no_clock_randomness_or_io(path: str) -> None:
    source = Path((gate_module if path == "gate.py" else policy_module).__file__ or "")
    assert source.name == path
    tree = ast.parse(source.read_text())
    forbidden_modules = {"time", "random", "secrets", "uuid", "sqlalchemy", "os", "pathlib"}
    forbidden_prefixes = ("flooreplay.db", "flooreplay.decisions.extraction", "flooreplay.config")
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
            assert node.attr not in clock_names, f"{path} uses .{node.attr}"
        elif isinstance(node, ast.Name):
            assert node.id not in {"now", "utcnow"}, f"{path} uses {node.id}"


# ---------------------------------------------------------------------------
# Required facts: missing => INCOMPLETE (unknown is never zero)
# ---------------------------------------------------------------------------


def test_missing_order_request() -> None:
    result = base().without(kind=FactKind.ORDER_REQUEST).gate()
    assert result.state is INCOMPLETE
    missing = finding(result, "order_request_missing")
    assert (missing.entity_key, missing.state, missing.fact_ids) == (ORDER_KEY, INCOMPLETE, ())


def test_an_order_for_another_id_is_missing_not_borrowed() -> None:
    world = base()
    other = evaluate_gate(world.snapshot(), "O-OTHER", world.policy, world.coverage)
    assert other.state is INCOMPLETE
    assert finding(other, "order_request_missing").entity_key == "order:O-OTHER"


def test_missing_bom_for_the_orders_style() -> None:
    result = base().without(kind=FactKind.BOM).gate()
    assert result.state is INCOMPLETE
    assert finding(result, "bom_missing").entity_key == BOM_KEY


def test_a_bom_for_another_style_does_not_count() -> None:
    world = base().without(kind=FactKind.BOM).with_facts(bom_fact("other-bom", style_id="S9"))
    assert finding(world.gate(), "bom_missing").entity_key == BOM_KEY


def test_missing_trim_status_for_each_bom_trim() -> None:
    for trim in ("ZIP", "LABEL"):
        result = base().without(entity_key=f"trim:S1:{trim}").gate()
        assert result.state is INCOMPLETE
        assert finding(result, "trim_status_missing").entity_key == f"trim:S1:{trim}"


def test_a_trim_status_for_another_style_does_not_count() -> None:
    world = base().without(entity_key="trim:S1:ZIP").with_facts(
        trim_fact("t9", "ZIP", style_id="S9")
    )
    assert finding(world.gate(), "trim_status_missing").entity_key == "trim:S1:ZIP"


@pytest.mark.parametrize("line", ["L1", "L2", "L3", "L4"])
def test_missing_capacity_for_any_eligible_line_on_any_working_day(line: str) -> None:
    days = working_days(DEFAULT_POLICY_V1, SHIP_DATE)
    for day in (days[0], days[len(days) // 2], days[-1]):  # first, middle, last day of the window
        key = f"line:{line}:{day.isoformat()}"
        result = base().without(entity_key=key).gate()
        assert result.state is INCOMPLETE, key
        assert finding(result, "line_capacity_missing").entity_key == key


def test_every_missing_capacity_day_is_reported_separately() -> None:
    result = base().without(where=lambda f: f.entity_key.startswith("line:L3:")).gate()
    keys = {f.entity_key for f in result.findings if f.code == "line_capacity_missing"}
    assert keys == {
        f"line:L3:{d.isoformat()}" for d in working_days(DEFAULT_POLICY_V1, SHIP_DATE)
    }


def test_capacity_outside_the_window_is_not_required() -> None:
    # Drop the days just outside the window if they were present; READY must hold either way.
    world = base().with_facts(
        capacity_fact("early", "L1", date(2026, 3, 9)),
        capacity_fact("late", "L1", date(2026, 3, 27)),
    )
    assert world.without(entity_key="line:L1:2026-03-09").gate().state is READY
    assert world.gate().state is READY


def test_the_window_ends_finishing_days_before_ship_and_starts_after_the_cut_date() -> None:
    last = SHIP_DATE - timedelta(days=4)  # 2026-03-26, still a sewing day
    cut = SHIP_DATE - timedelta(days=21)  # 2026-03-09, the cut itself is not a sewing day
    assert base().without(entity_key=f"line:L1:{last.isoformat()}").gate().state is INCOMPLETE
    first = cut + timedelta(days=1)
    assert base().without(entity_key=f"line:L1:{first.isoformat()}").gate().state is INCOMPLETE
    assert base().without(entity_key=f"line:L1:{cut.isoformat()}").gate().state is READY


def test_non_working_weekdays_and_holidays_define_the_working_days() -> None:
    saturday_off = policy_with(non_working_weekdays=["SAT", "SUN"])
    assert ready_world(saturday_off).gate().state is READY
    # A world built for Sundays-only lacks Saturdays, which a Sat+Sun-off policy does not need
    # but a Sunday-only policy does.
    sunday_only_world = ready_world()
    assert sunday_only_world.with_policy(saturday_off).gate().state is READY
    saturday_world = ready_world(saturday_off)
    assert saturday_world.with_policy(DEFAULT_POLICY_V1).gate().state is INCOMPLETE

    holiday = date(2026, 3, 18)  # a Wednesday inside the window
    with_holiday = policy_with(holidays=[holiday.isoformat()])
    no_cap_that_day = base().without(entity_key=f"line:L2:{holiday.isoformat()}")
    assert no_cap_that_day.gate().state is INCOMPLETE
    assert no_cap_that_day.with_policy(with_holiday).gate().state is READY


def test_only_eligible_lines_are_required() -> None:
    fewer = policy_with(eligible_lines=["L1", "L2"])
    world = base().without(where=lambda f: f.entity_key.startswith(("line:L3:", "line:L4:")))
    assert world.gate().state is INCOMPLETE
    assert world.with_policy(fewer).gate().state is READY
    more = policy_with(eligible_lines=["L1", "L2", "L3", "L4", "L5"])
    result = base().with_policy(more).gate()
    assert result.state is INCOMPLETE
    assert {f.entity_key.split(":")[1] for f in result.findings if f.state is INCOMPLETE} == {"L5"}


def test_a_window_with_no_working_days_requires_no_capacity() -> None:
    policy = policy_with(cut_to_ship_days=4, finishing_days=4)
    world = base().without(kind=FactKind.LINE_CAPACITY).with_policy(policy)
    assert world.gate().state is READY


# --- artifact coverage -----------------------------------------------------


def test_uncovered_quality_with_no_lot_for_a_colour_is_incomplete() -> None:
    world = base().without(entity_key="lot:LOT-W1").with_coverage({})
    result = world.gate()
    assert result.state is INCOMPLETE
    missing = finding(result, "fabric_stock_uncovered")
    assert missing.state is INCOMPLETE
    assert QUALITY in missing.entity_key and "WHITE" in missing.entity_key


def test_covered_quality_with_no_lot_for_a_colour_is_a_known_zero() -> None:
    world = base().without(entity_key="lot:LOT-W1")
    assert world.coverage[ERP_ARTIFACT] == frozenset({QUALITY})
    result = world.gate()
    assert result.state is READY
    assert "fabric_stock_uncovered" not in codes(result)


def test_coverage_of_another_quality_does_not_cover_this_one() -> None:
    world = base().without(entity_key="lot:LOT-W1").with_coverage({ERP_ARTIFACT: frozenset({"X"})})
    assert world.gate().state is INCOMPLETE


def test_any_declared_artifact_may_cover_the_quality() -> None:
    world = base().without(entity_key="lot:LOT-W1").with_coverage(
        {"a": frozenset({"X"}), "b": frozenset({QUALITY, "Y"})}
    )
    assert world.gate().state is READY


def test_lots_present_need_no_coverage_declaration() -> None:
    assert base().with_coverage({}).gate().state is READY


def test_every_ordered_colour_is_checked_for_coverage() -> None:
    world = base().without(entity_key="lot:LOT-N1", kind=FactKind.FABRIC_LOT).without(
        entity_key="lot:LOT-W1"
    )
    uncovered = world.with_coverage({})
    result = uncovered.gate()
    assert len([f for f in result.findings if f.code == "fabric_stock_uncovered"]) == 2
    assert world.gate().state is READY


def test_lots_of_another_quality_or_colour_do_not_satisfy_the_order() -> None:
    world = (
        base()
        .without(entity_key="lot:LOT-W1")
        .with_coverage({})
        .with_facts(
            lot_fact("o1", "LOT-O1", "WHITE", quality="OTHERQ"),
            lot_fact("o2", "LOT-O2", "RED"),
        )
    )
    assert world.gate().state is INCOMPLETE


# --- units ----------------------------------------------------------------


def test_unit_mismatch_without_gsm_and_width_is_incomplete() -> None:
    world = base().replace_fact("w-bom", payload=bom_fact(unit="m", consumption="1.6").payload)
    result = world.gate()
    assert result.state is INCOMPLETE
    unit_findings = [f for f in result.findings if f.code == "gsm_width_missing"]
    assert {f.entity_key for f in unit_findings} == {"lot:LOT-N1", "lot:LOT-W1"}
    assert all(f.state is INCOMPLETE and f.fact_ids for f in unit_findings)


def test_unit_mismatch_needs_both_gsm_and_width() -> None:
    metres = bom_fact(unit="m", consumption="1.6").payload
    for extra in ({"gsm": "180"}, {"width_m": "1.5"}):
        world = (
            base()
            .replace_fact("w-bom", payload=metres)
            .replace_fact(
                "w-lot-navy", payload={**base().get("w-lot-navy").payload, **extra}
            )
        )
        keys = {f.entity_key for f in world.gate().findings if f.code == "gsm_width_missing"}
        assert "lot:LOT-N1" in keys


def test_unit_mismatch_with_gsm_and_width_is_fine() -> None:
    metres = bom_fact(unit="m", consumption="1.6").payload
    with_factors = {"gsm": "180", "width_m": "1.5"}
    world = base().replace_fact("w-bom", payload=metres)
    for fact_id in ("w-lot-navy", "w-lot-white"):
        world = world.replace_fact(
            fact_id, payload={**world.get(fact_id).payload, **with_factors}
        )
    assert world.gate().state is READY


def test_matching_units_do_not_need_gsm_or_width() -> None:
    assert base().gate().state is READY


def test_a_lot_in_metres_against_a_kg_bom_also_needs_gsm_and_width() -> None:
    payload = {**base().get("w-lot-navy").payload, "qty": {"value": "900", "unit": "m"}}
    result = base().replace_fact("w-lot-navy", payload=payload).gate()
    assert result.state is INCOMPLETE
    assert finding(result, "gsm_width_missing").entity_key == "lot:LOT-N1"


# ---------------------------------------------------------------------------
# Conflicts
# ---------------------------------------------------------------------------


def tied_lot(qty: str, fact_id: str) -> Fact:
    return lot_fact(fact_id, "LOT-N1", "NAVY", qty, valid_from=AS_OF)


def test_payload_tie_on_a_required_entity_is_conflicting() -> None:
    world = base().with_facts(tied_lot("111", "tie-b"))
    result = world.gate()
    assert result.state is CONFLICTING
    tie = finding(result, "tie_conflict")
    assert tie.state is CONFLICTING
    assert tie.entity_key == "lot:LOT-N1"
    assert set(tie.fact_ids) == {"w-lot-navy", "tie-b"}


def test_a_tie_with_identical_semantic_payload_is_not_a_conflict() -> None:
    same = lot_fact("tie-b", "LOT-N1", "NAVY", "500", valid_from=AS_OF, source=SourceProfile.NOTES)
    row_numbers = same.model_copy(update={"payload": {**same.payload, "row_number": 9}})
    assert base().with_facts(row_numbers).gate().state is READY


@pytest.mark.parametrize(
    "entity_key",
    [ORDER_KEY, BOM_KEY, "trim:S1:ZIP", "line:L1:2026-03-10"],
)
def test_tie_conflict_on_each_kind_of_required_entity(entity_key: str) -> None:
    original = next(f for f in base().facts if f.entity_key == entity_key)
    # A same-valid_from twin whose semantic payload differs.
    payloads = {
        ORDER_KEY: {**original.payload, "order_value_inr": "1"},
        BOM_KEY: {**original.payload, "sam_minutes": "99"},
        "trim:S1:ZIP": {**original.payload, "supplier": "SUP-X"},
        "line:L1:2026-03-10": {
            **original.payload,
            "available_minutes": {"value": "1", "unit": "minutes"},
        },
    }
    twin = original.model_copy(update={"id": "twin", "payload": payloads[entity_key]})
    result = base().with_facts(twin).gate()
    assert result.state is CONFLICTING
    assert finding(result, "tie_conflict").entity_key == entity_key


def test_a_newer_observation_wins_without_conflict() -> None:
    newer = lot_fact("newer", "LOT-N1", "NAVY", "111", valid_from=AS_OF + 10 * MINUTE)
    world = base().with_facts(newer)
    assert world.gate().state is READY


def test_tie_conflict_on_an_irrelevant_lot_is_ignored() -> None:
    red_a = lot_fact("red-a", "LOT-R1", "RED", "10", valid_from=AS_OF)
    red_b = lot_fact("red-b", "LOT-R1", "RED", "20", valid_from=AS_OF)
    assert base().with_facts(red_a, red_b).gate().state is READY


def test_competing_replacements_are_conflicting_even_with_identical_payloads() -> None:
    original = base().get("w-lot-navy")
    copies = [
        lot_fact(
            f"fix-{i}",
            "LOT-N1",
            "NAVY",
            "500",
            valid_from=AS_OF,
            known_at=original.known_at + (1 + i) * MINUTE,
            supersedes_id="w-lot-navy",
        )
        for i in range(2)
    ]
    world = base().with_facts(*copies)
    assert [f.code for f in world.snapshot().findings] == ["competing_replacement"]
    result = world.gate()
    assert result.state is CONFLICTING
    assert codes(result, CONFLICTING) == {"competing_replacement"}
    competing = finding(result, "competing_replacement")
    assert competing.entity_key == "lot:LOT-N1"
    assert set(competing.fact_ids) == {"fix-0", "fix-1"}


def test_competing_replacements_of_an_unrelated_entity_are_ignored() -> None:
    red = lot_fact("red", "LOT-R1", "RED", "10")
    fixes = [
        lot_fact(
            f"red-fix-{i}",
            "LOT-R1",
            "RED",
            "10",
            known_at=red.known_at + (1 + i) * MINUTE,
            supersedes_id="red",
        )
        for i in range(2)
    ]
    world = base().with_facts(red, *fixes)
    assert world.snapshot().findings, "the snapshot itself still reports the competition"
    assert world.gate().state is READY


def test_competing_replacements_not_yet_known_are_not_visible() -> None:
    original = base().get("w-lot-navy")
    late = [
        lot_fact(
            f"fix-{i}",
            "LOT-N1",
            "NAVY",
            "500",
            known_at=CUTOFF + (1 + i) * MINUTE,
            supersedes_id="w-lot-navy",
        )
        for i in range(2)
    ]
    world = base().with_facts(*late)
    assert original.id in {f.id for f in world.snapshot().facts}
    assert world.gate().state is READY
    assert world.gate(CUTOFF + HOUR).state is CONFLICTING


def test_competing_replacements_report_the_branch_tips() -> None:
    original = base().get("w-lot-navy")
    first = lot_fact(
        "fix-a", "LOT-N1", "NAVY", "500", known_at=original.known_at + MINUTE, supersedes_id="w-lot-navy"
    )
    second = lot_fact(
        "fix-b", "LOT-N1", "NAVY", "500", known_at=original.known_at + 2 * MINUTE, supersedes_id="w-lot-navy"
    )
    later = lot_fact(
        "fix-a2", "LOT-N1", "NAVY", "500", known_at=original.known_at + 3 * MINUTE, supersedes_id="fix-a"
    )
    result = base().with_facts(first, second, later).gate()
    assert result.state is CONFLICTING
    assert set(finding(result, "competing_replacement").fact_ids) == {"fix-a2", "fix-b"}


def test_competing_replacements_of_a_required_trim_are_one_conflict() -> None:
    original = base().get("w-trim-ZIP")
    fixes = [
        trim_fact(f"zip-{i}", "ZIP", known_at=original.known_at + (1 + i) * MINUTE, supersedes_id="w-trim-ZIP")
        for i in range(2)
    ]
    result = base().with_facts(*fixes).gate()
    assert result.state is CONFLICTING
    assert [f.code for f in result.findings] == ["competing_replacement"]


# --- facts the snapshot excluded --------------------------------------------


def test_an_invalid_required_fact_is_incomplete_not_zero() -> None:
    world = base().replace_fact("w-trim-ZIP", payload={"supplier": "SUP-2"})  # no on_hand
    assert [f.code for f in world.snapshot().findings] == ["invalid_payload"]
    result = world.gate()
    assert result.state is INCOMPLETE
    assert {"invalid_payload", "trim_status_missing"} <= codes(result, INCOMPLETE)
    invalid = finding(result, "invalid_payload")
    assert (invalid.entity_key, invalid.fact_ids) == ("trim:S1:ZIP", ("w-trim-ZIP",))


def test_an_invalid_lot_is_incomplete_even_when_the_quality_is_covered() -> None:
    # Covered quality would make "no NAVY lot" a known zero; an excluded lot must not look like that.
    world = base().replace_fact("w-lot-navy", payload={"colour": "NAVY"})
    result = world.gate()
    assert result.state is INCOMPLETE
    assert finding(result, "invalid_payload").entity_key == "lot:LOT-N1"


def test_an_invalid_fact_for_an_entity_the_order_does_not_use_is_ignored() -> None:
    bad = trim_fact("bad-trim", "ZIP", style_id="S9").model_copy(update={"payload": {"supplier": "x"}})
    world = base().with_facts(bad)
    assert world.snapshot().findings
    assert world.gate().state is READY


# --- declarative conflict rules ---------------------------------------------


def qc_world(**qc_kwargs: Any) -> World:
    """READY world plus a QC claim against NAVY lot LOT-N1."""
    qc_kwargs.setdefault("valid_from", AS_OF - HOUR)
    return base().with_facts(qc_fact("qc-1", "LOT-N1", "50", **qc_kwargs))


def resolve(
    world: World,
    *,
    known_at: datetime,
    rule_id: str = "qc_claims_against_lot",
    left: str = "w-lot-navy",
    right: str = "qc-1",
) -> World:
    return world.with_facts(
        resolution_fact(
            "res-1",
            "lot:LOT-N1",
            rule_id=rule_id,
            left_fact_id=left,
            right_fact_id=right,
            valid_from=known_at,
            known_at=known_at,
        )
    )


def test_qc_claim_against_a_lot_is_conflicting() -> None:
    result = qc_world().gate()
    assert result.state is CONFLICTING
    conflict = finding(result, "conflict_rule")
    assert conflict.state is CONFLICTING
    assert conflict.rule_id == "qc_claims_against_lot"
    assert conflict.entity_key == "lot:LOT-N1"
    assert set(conflict.fact_ids) == {"w-lot-navy", "qc-1"}


@pytest.mark.parametrize("state", ["checks_passed", "confirmed", "needs_review"])
def test_qc_states_that_still_claim_stock_conflict(state: str) -> None:
    assert qc_world(review_state=state).gate().state is CONFLICTING


@pytest.mark.parametrize("state", ["corrected", "rejected"])
def test_qc_states_that_no_longer_claim_stock_do_not_conflict(state: str) -> None:
    assert qc_world(review_state=state).gate().state is READY


def test_qc_claim_on_a_lot_the_order_does_not_use_is_ignored() -> None:
    red = lot_fact("red", "LOT-R1", "RED", "10")
    world = base().with_facts(red, qc_fact("qc-red", "LOT-R1", "5", valid_from=AS_OF - HOUR))
    assert world.gate().state is READY


def test_conflict_needs_overlapping_valid_time() -> None:
    # The QC claim ended before the lot observation began: half-open, no overlap.
    ended = qc_world(valid_from=AS_OF - 3 * HOUR, valid_to=AS_OF - HOUR)
    assert ended.gate().state is READY
    # Touching endpoints do not overlap either.
    touching = qc_world(valid_from=AS_OF - 3 * HOUR, valid_to=AS_OF)
    assert touching.gate().state is READY
    # One instant of overlap is enough.
    overlapping = qc_world(valid_from=AS_OF - 3 * HOUR, valid_to=AS_OF + MINUTE)
    assert overlapping.gate().state is CONFLICTING


def test_a_resolution_known_after_the_cutoff_does_not_clear_the_conflict() -> None:
    world = resolve(qc_world(), known_at=CUTOFF + 10 * MINUTE)
    at_cutoff = world.gate(CUTOFF)
    assert at_cutoff.state is CONFLICTING
    assert "conflict_resolved" not in codes(at_cutoff)

    later = world.gate(CUTOFF + 30 * MINUTE)
    assert later.state is READY, "cleared only from the resolution's own known_at"
    resolved = finding(later, "conflict_resolved")
    assert resolved.state is READY
    assert resolved.rule_id == "qc_claims_against_lot"
    assert {"w-lot-navy", "qc-1", "res-1"} <= set(resolved.fact_ids)
    assert "conflict_rule" not in codes(later)


def test_a_resolution_known_exactly_at_the_cutoff_clears_it() -> None:
    assert resolve(qc_world(), known_at=CUTOFF).gate().state is READY


def test_a_resolution_for_a_different_pair_or_rule_does_not_clear_it() -> None:
    known = CUTOFF - 10 * MINUTE
    for kwargs in (
        {"right": "some-other-qc"},
        {"left": "some-other-lot"},
        {"rule_id": "inbound_eta_disagrees"},
        {"left": "qc-1", "right": "w-lot-navy"},  # swapped: different kinds, so not the pair
    ):
        result = resolve(qc_world(), known_at=known, **kwargs).gate()
        assert result.state is CONFLICTING, kwargs
        assert "conflict_resolved" not in codes(result)


def test_a_resolution_clears_only_its_own_conflict() -> None:
    # Two QC claims on the lot give two conflicts; resolving one leaves the other.
    other_qc = qc_fact("qc-2", "LOT-N1", "5", valid_from=AS_OF - 2 * HOUR, issue="defect")
    world = qc_world().with_facts(other_qc)
    assert len([f for f in world.gate().findings if f.code == "conflict_rule"]) == 2
    result = resolve(world, known_at=CUTOFF - MINUTE).gate()
    assert result.state is CONFLICTING
    remaining = finding(result, "conflict_rule")
    assert "qc-2" in remaining.fact_ids
    assert finding(result, "conflict_resolved").rule_id == "qc_claims_against_lot"


def test_a_superseded_resolution_no_longer_clears() -> None:
    world = resolve(qc_world(), known_at=CUTOFF - 10 * MINUTE)
    retract = resolution_fact(
        "res-2",
        "lot:LOT-N1",
        rule_id="qc_claims_against_lot",
        left_fact_id="nope",
        right_fact_id="nope",
        valid_from=CUTOFF - 10 * MINUTE,  # a correction keeps its target's valid time
        known_at=CUTOFF - MINUTE,
        supersedes_id="res-1",
    )
    assert world.with_facts(retract).gate().state is CONFLICTING


# --- inbound ETA disagreements ---------------------------------------------


def inbound_pair(
    *,
    first_to: datetime | None = None,
    second_from: datetime = AS_OF,
    second_eta: date = date(2026, 3, 9),
) -> World:
    first = inbound_fact("ib-1", "I1", eta=date(2026, 3, 6), valid_from=AS_OF - 5 * HOUR, valid_to=first_to)
    second = inbound_fact("ib-2", "I1", eta=second_eta, valid_from=second_from)
    return base().with_facts(first, second)


def test_a_newer_observation_ends_the_older_one_so_it_is_not_a_disagreement() -> None:
    # Two exports, ETA moved from 6 Mar to 9 Mar: the second replaces the first.
    assert inbound_pair().gate().state is READY


def test_inbound_etas_disagreeing_over_overlapping_valid_time_conflict() -> None:
    world = inbound_pair(first_to=AS_OF + 2 * HOUR)  # the first promise outlives the second's start
    result = world.gate()
    assert result.state is CONFLICTING
    conflict = finding(result, "conflict_rule")
    assert conflict.rule_id == "inbound_eta_disagrees"
    assert conflict.entity_key == "inbound:I1"
    assert set(conflict.fact_ids) == {"ib-1", "ib-2"}


def test_inbound_etas_that_agree_do_not_conflict() -> None:
    world = inbound_pair(first_to=AS_OF + 2 * HOUR, second_eta=date(2026, 3, 6))
    assert world.gate().state is READY


def test_inbound_conflict_is_cleared_by_a_resolution_for_that_pair() -> None:
    world = inbound_pair(first_to=AS_OF + 2 * HOUR)
    cleared = world.with_facts(
        resolution_fact(
            "res-ib",
            "inbound:I1",
            rule_id="inbound_eta_disagrees",
            left_fact_id="ib-1",
            right_fact_id="ib-2",
            known_at=CUTOFF - MINUTE,
            valid_from=CUTOFF - MINUTE,
        )
    )
    assert cleared.gate().state is READY
    # The resolution names the pair either way round: the rule is symmetric.
    swapped = world.with_facts(
        resolution_fact(
            "res-ib",
            "inbound:I1",
            rule_id="inbound_eta_disagrees",
            left_fact_id="ib-2",
            right_fact_id="ib-1",
            known_at=CUTOFF - MINUTE,
            valid_from=CUTOFF - MINUTE,
        )
    )
    assert swapped.gate().state is READY


def test_same_start_inbound_disagreement_is_a_rule_conflict_a_resolution_can_clear() -> None:
    first = inbound_fact("ib-1", "I1", eta=date(2026, 3, 6))
    second = inbound_fact("ib-2", "I1", eta=date(2026, 3, 9))
    world = base().with_facts(first, second)
    result = world.gate()
    assert result.state is CONFLICTING and "conflict_rule" in codes(result)
    assert "tie_conflict" not in codes(result), "inbound is not a required entity"


def test_inbound_for_another_colour_or_quality_is_not_this_orders_business() -> None:
    first = inbound_fact("ib-1", "I1", "RED", eta=date(2026, 3, 6), valid_to=AS_OF + HOUR)
    second = inbound_fact("ib-2", "I1", "RED", eta=date(2026, 3, 9))
    assert base().with_facts(first, second).gate().state is READY


def test_a_policy_without_rules_has_no_rule_conflicts() -> None:
    data = DEFAULT_POLICY_V1.model_dump(mode="json")
    data["conflict_rules"] = []
    policy = PolicyDocument.model_validate(data)
    assert qc_world().with_policy(policy).gate().state is READY


# ---------------------------------------------------------------------------
# Precedence, all findings kept
# ---------------------------------------------------------------------------


def test_precedence_conflicting_over_incomplete_over_stale() -> None:
    stale = base().replace_fact("w-lot-navy", valid_from=CUTOFF - 30 * HOUR)
    assert stale.gate().state is STALE

    incomplete = stale.without(entity_key="trim:S1:ZIP")
    assert incomplete.gate().state is INCOMPLETE

    conflicting = incomplete.with_facts(qc_fact("qc-1", "LOT-N1", "5", valid_from=AS_OF - HOUR))
    assert conflicting.gate().state is CONFLICTING


def test_all_findings_are_kept_when_several_problems_coexist() -> None:
    world = (
        base()
        .replace_fact("w-trim-LABEL", valid_from=CUTOFF - 60 * HOUR)  # stale
        .without(entity_key="trim:S1:ZIP")  # incomplete
        .without(entity_key="line:L4:2026-03-20")  # incomplete
        .with_facts(
            qc_fact("qc-1", "LOT-N1", "5", valid_from=AS_OF - HOUR),  # rule conflict
            tied_lot("111", "tie-b"),  # tie conflict
        )
    )
    result = world.gate()
    assert result.state is CONFLICTING
    assert codes(result, STALE) == {"stale_evidence"}
    assert codes(result, INCOMPLETE) == {"trim_status_missing", "line_capacity_missing"}
    assert codes(result, CONFLICTING) == {"conflict_rule", "tie_conflict"}
    assert result.state == combine_gate_states(f.state for f in result.findings)
    assert {f.entity_key for f in result.findings if f.state is INCOMPLETE} == {
        "trim:S1:ZIP",
        "line:L4:2026-03-20",
    }


def test_conflicts_are_reported_even_when_the_order_is_missing() -> None:
    world = qc_world().without(kind=FactKind.ORDER_REQUEST)
    result = world.gate()
    assert result.state is INCOMPLETE  # nothing relevant to the QC lot can be known without the order
    assert "order_request_missing" in codes(result)


def test_findings_are_in_a_deterministic_order() -> None:
    world = base().without(kind=FactKind.LINE_CAPACITY)
    first = world.gate().findings
    assert first == world.gate().findings
    shuffled = list(world.facts)
    random.Random(3).shuffle(shuffled)
    assert first == World(facts=tuple(shuffled)).gate().findings
    assert [f.entity_key for f in first] == sorted(f.entity_key for f in first)


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------

BASE_WORLD = ready_world()


@st.composite
def perturbed_snapshots(draw: st.DrawFn) -> tuple[World, datetime]:
    """The READY world with facts dropped, moved in time, added from the generic strategy."""
    base_facts = list(BASE_WORLD.facts)
    dropped = set(
        draw(st.lists(st.integers(0, len(base_facts) - 1), unique=True, max_size=8))
    )
    kept = [f for i, f in enumerate(base_facts) if i not in dropped]
    aged = draw(st.lists(st.integers(0, max(len(kept) - 1, 0)), unique=True, max_size=6))
    for index in aged:
        if kept:
            hours = draw(st.integers(1, 400))  # valid_from may not be after known_at
            kept[index] = kept[index].model_copy(update={"valid_from": CUTOFF - hours * HOUR})
    extras = draw(st.lists(fact_strategy(), max_size=6))
    extras = [f.model_copy(update={"id": f"extra-{i}"}) for i, f in enumerate(extras)]
    cutoff = CUTOFF + draw(st.integers(-3, 60)) * HOUR
    return World(facts=tuple([*kept, *extras])), cutoff


@settings(max_examples=150, deadline=None)
@given(perturbed_snapshots())
def test_never_ready_while_any_finding_is_not_ready(drawn: tuple[World, datetime]) -> None:
    world, cutoff = drawn
    result = world.gate(cutoff)
    if result.state is READY:
        assert all(f.state is READY for f in result.findings)
    assert result.state == combine_gate_states(f.state for f in result.findings)
    for item in result.findings:
        if item.state is not READY:
            assert item.entity_key


@settings(max_examples=60, deadline=None)
@given(perturbed_snapshots(), st.randoms(use_true_random=False))
def test_gate_ignores_fact_input_order(drawn: tuple[World, datetime], rnd: random.Random) -> None:
    world, cutoff = drawn
    shuffled = list(world.facts)
    rnd.shuffle(shuffled)
    assert World(facts=tuple(shuffled)).gate(cutoff) == world.gate(cutoff)


@settings(max_examples=60, deadline=None)
@given(st.lists(st.integers(0, len(BASE_WORLD.facts) - 1), unique=True, min_size=1, max_size=5))
def test_removing_a_required_fact_never_leaves_it_ready(indexes: list[int]) -> None:
    required_kinds = {
        FactKind.ORDER_REQUEST,
        FactKind.BOM,
        FactKind.TRIM_STATUS,
        FactKind.LINE_CAPACITY,
    }
    victims = {BASE_WORLD.facts[i].id for i in indexes}
    # Lots are excluded: with the quality covered, a missing lot is a known zero, by design.
    removes_required = any(
        f.id in victims and f.kind in required_kinds for f in BASE_WORLD.facts
    )
    world = World(facts=tuple(f for f in BASE_WORLD.facts if f.id not in victims))
    if removes_required:
        assert world.gate().state is not READY


def test_snapshot_digest_independent_of_gate() -> None:
    world = base()
    before = snapshot_at(world.facts, CUTOFF)
    world.gate()
    assert snapshot_at(world.facts, CUTOFF) == before
