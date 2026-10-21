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
    cover,
    inbound_fact,
    kg,
    lot_fact,
    make_fact,
    order_fact,
    qc_fact,
    ready_world,
    resolution_fact,
    trim_fact,
    working_days,
)
from flooreplay.decisions import gate as gate_module
from flooreplay.decisions import policy as policy_module
from flooreplay.decisions.gate import (
    CoverageDecl,
    GateFinding,
    GateResult,
    evaluate_gate,
    native_source,
)
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


def test_freshness_follows_the_kind_not_the_source_the_fact_claims() -> None:
    # A reviewer's correction of a stale lot is still a stale lot.
    old = CUTOFF - 500 * HOUR
    stale = lot_fact("w-lot-navy", "LOT-N1", "NAVY", "500", valid_from=old)
    world = base().without(fact_id="w-lot-navy").with_facts(stale)
    assert world.gate().state is STALE
    fix = lot_fact(
        "fix",
        "LOT-N1",
        "NAVY",
        "900",
        valid_from=old,
        known_at=CUTOFF - HOUR,
        supersedes_id="w-lot-navy",
        source=SourceProfile.REVIEW_QUEUE,
    )
    corrected = world.with_facts(fix)
    result = corrected.gate()
    assert result.state is STALE
    assert finding(result, "stale_evidence").fact_ids == ("fix",)


@pytest.mark.parametrize("source", list(SourceProfile))
def test_a_claimed_source_never_changes_the_limit(source: SourceProfile) -> None:
    """Whatever source a lot claims, its 24h erp_fabric_stock limit applies."""
    at_limit = base().replace_fact("w-lot-navy", source=source, valid_from=CUTOFF - 24 * HOUR)
    assert at_limit.gate().state is READY
    over = base().replace_fact(
        "w-lot-navy", source=source, valid_from=CUTOFF - 24 * HOUR - MINUTE
    )
    assert over.gate().state is STALE


def test_native_source_by_kind() -> None:
    expected = {
        "w-order": SourceProfile.ORDER_REQUESTS,
        "w-bom": SourceProfile.ORDER_REQUESTS,
        "w-lot-navy": SourceProfile.ERP_FABRIC_STOCK,
        "w-trim-ZIP": SourceProfile.SHEET_TRIMS_STATUS,
        "w-cap-L1-2026-03-10": SourceProfile.SHIFT_CAPACITY,
    }
    for fact_id, source in expected.items():
        assert native_source(base().get(fact_id)) is source
    assert native_source(inbound_fact("i", "I1")) is SourceProfile.SUPPLIER_UPDATES
    allocation = make_fact(
        "a", FactKind.FABRIC_ALLOCATION, f"alloc:O2:{QUALITY}:NAVY", {"qty": kg("1")}
    )
    assert native_source(allocation) is SourceProfile.ERP_FABRIC_STOCK
    commitment = make_fact(
        "c",
        FactKind.LINE_COMMITMENT,
        "commit:O2:L1:2026-03-10",
        {"committed_minutes": {"value": "1", "unit": "minutes"}},
    )
    assert native_source(commitment) is SourceProfile.SHIFT_CAPACITY
    assert native_source(qc_fact("q", "LOT-N1")) is SourceProfile.NOTES
    supplier_qc = make_fact(
        "q2",
        FactKind.FABRIC_QC,
        "lot:LOT-N1",
        {
            "issue": "defect",
            "qty": kg("1"),
            "review_state": "confirmed",
            "origin": "supplier_updates",
        },
    )
    assert native_source(supplier_qc) is SourceProfile.SUPPLIER_UPDATES
    resolution = resolution_fact(
        "r", "lot:LOT-N1", rule_id="x", left_fact_id="a", right_fact_id="b"
    )
    assert native_source(resolution) is None, "a resolution is a decision, not an observation"


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
    # cut 5 / finishing 4 leaves a single sewing day, 2026-03-26; make it a holiday.
    policy = policy_with(cut_to_ship_days=5, finishing_days=4, holidays=["2026-03-26"])
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
    assert world.coverage[ERP_ARTIFACT].qualities == frozenset({QUALITY})
    result = world.gate()
    assert result.state is READY
    assert "fabric_stock_uncovered" not in codes(result)


def test_coverage_of_another_quality_does_not_cover_this_one() -> None:
    world = base().without(entity_key="lot:LOT-W1").with_coverage(cover("X"))
    assert world.gate().state is INCOMPLETE


def test_only_the_newest_stock_export_decides_coverage() -> None:
    no_white = base().without(entity_key="lot:LOT-W1")
    old = cover(QUALITY, artifact_id="a-old", as_of=AS_OF - 5 * HOUR)
    new = cover("X", artifact_id="a-new", as_of=AS_OF)
    # The older export covers the quality, the newer one does not: not covered.
    result = no_white.with_coverage({**old, **new}).gate()
    assert result.state is INCOMPLETE
    assert result.coverage_used is not None and result.coverage_used.artifact_id == "a-new"
    # Reverse the dates and the quality is covered.
    flipped = {
        **cover(QUALITY, artifact_id="a-old", as_of=AS_OF),
        **cover("X", artifact_id="a-new", as_of=AS_OF - 5 * HOUR),
    }
    assert no_white.with_coverage(flipped).gate().state is READY


def test_equal_as_of_breaks_ties_by_the_greatest_artifact_id() -> None:
    no_white = base().without(entity_key="lot:LOT-W1")
    both = {**cover(QUALITY, artifact_id="a-1"), **cover("X", artifact_id="a-2")}
    result = no_white.with_coverage(both).gate()
    assert result.state is INCOMPLETE and result.coverage_used is not None
    assert result.coverage_used.artifact_id == "a-2"


def test_only_stock_exports_known_by_the_cutoff_count_for_coverage() -> None:
    no_white = base().without(entity_key="lot:LOT-W1")
    other_profile = cover(QUALITY, profile=SourceProfile.SUPPLIER_UPDATES)
    assert no_white.with_coverage(other_profile).gate().state is INCOMPLETE
    future = cover(QUALITY, as_of=CUTOFF + HOUR)
    assert no_white.with_coverage(future).gate().state is INCOMPLETE


def test_coverage_used_is_echoed_for_the_decision_digest() -> None:
    result = base().gate()
    assert result.coverage_used is not None
    assert (result.coverage_used.artifact_id, result.coverage_used.as_of) == (ERP_ARTIFACT, AS_OF)
    assert result.coverage_used.qualities == (QUALITY,)
    assert base().with_coverage({}).gate().coverage_used is None


def test_a_known_zero_is_aged_by_the_coverage_artifacts_as_of() -> None:
    no_white = base().without(entity_key="lot:LOT-W1")
    at_limit = no_white.with_coverage(cover(QUALITY, as_of=CUTOFF - 24 * HOUR))
    assert at_limit.gate().state is READY
    over = no_white.with_coverage(cover(QUALITY, as_of=CUTOFF - 24 * HOUR - MINUTE)).gate()
    assert over.state is STALE
    assert finding(over, "stale_evidence").entity_key == f"coverage:{ERP_ARTIFACT}"
    # The artifact's age matters only when a known zero relies on it.
    all_lots = base().with_coverage(cover(QUALITY, as_of=CUTOFF - 500 * HOUR))
    assert all_lots.gate().state is READY


def test_a_bare_string_is_not_a_set_of_qualities() -> None:
    with pytest.raises(ValueError, match="not one string"):
        CoverageDecl(
            profile=SourceProfile.ERP_FABRIC_STOCK,
            as_of=AS_OF,
            qualities=QUALITY,  # type: ignore[arg-type]
        )


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


# --- every consumed kind: an excluded fact is missing evidence ----------------


def junk(fact_id: str, kind: FactKind, key: str) -> Fact:
    """A fact whose payload cannot parse, so the snapshot excludes it."""
    return make_fact(fact_id, kind, key, {"junk": "x"})


INVALID_CASES = [
    # (kind, entity_key, does it make the gate INCOMPLETE?)
    (FactKind.FABRIC_ALLOCATION, f"alloc:O2:{QUALITY}:NAVY", True),
    (FactKind.FABRIC_ALLOCATION, "alloc:O2:OTHERQ:NAVY", False),
    (FactKind.FABRIC_ALLOCATION, f"alloc:O2:{QUALITY}:RED", False),
    (FactKind.FABRIC_ALLOCATION, "alloc:weird", True),  # bad entity_key: cannot be placed
    (FactKind.LINE_COMMITMENT, "commit:O2:L1:2026-03-12", True),
    (FactKind.LINE_COMMITMENT, "commit:O2:L9:2026-03-12", False),
    (FactKind.LINE_COMMITMENT, "commit:O2:L1:2026-04-30", False),
    (FactKind.FABRIC_INBOUND, "inbound:R1", True),
    (FactKind.FABRIC_QC, "lot:LOT-N1", True),
    (FactKind.FABRIC_QC, "lot:LOT-R9", False),
    (FactKind.TRIM_STATUS, "trim:S1:ZIP", True),
    (FactKind.TRIM_STATUS, "trim:S9:ZIP", False),
    (FactKind.TRIM_STATUS, "trim:S1:BUTTON", False),
    (FactKind.LINE_CAPACITY, "line:L2:2026-03-12", True),
    (FactKind.LINE_CAPACITY, "line:L9:2026-03-12", False),
    (FactKind.LINE_CAPACITY, "line:L2:2026-04-30", False),
    (FactKind.BOM, "bom:S1", True),
    (FactKind.BOM, "bom:S9", False),
    (FactKind.ORDER_REQUEST, "order:O1", True),
    (FactKind.ORDER_REQUEST, "order:O9", False),
    (FactKind.FABRIC_LOT, "lot:ANY", True),
    (FactKind.RESOLUTION, "lot:LOT-N1", False),  # a bad resolution simply clears nothing
]


@pytest.mark.parametrize(("kind", "key", "blocks"), INVALID_CASES)
def test_an_excluded_fact_blocks_only_when_this_order_could_use_it(
    kind: FactKind, key: str, blocks: bool
) -> None:
    world = base().with_facts(junk("bad", kind, key))
    assert [f.code for f in world.snapshot().findings] == ["invalid_payload"]
    result = world.gate()
    assert (result.state is INCOMPLETE) is blocks
    if blocks:
        assert finding(result, "invalid_payload").fact_ids == ("bad",)


def test_negative_or_malformed_values_are_excluded_not_summed() -> None:
    negative = make_fact(
        "neg", FactKind.FABRIC_ALLOCATION, f"alloc:O2:{QUALITY}:NAVY", {"qty": kg("-5")}
    )
    commit = make_fact(
        "commit-bad",
        FactKind.LINE_COMMITMENT,
        "commit:O2:L1:2026-03-12",
        {"committed_minutes": {"value": "abc", "unit": "minutes"}},
    )
    incomplete_inbound = make_fact(
        "in-bad", FactKind.FABRIC_INBOUND, "inbound:R1", {"fabric_quality": QUALITY}
    )
    for bad in (negative, commit, incomplete_inbound):
        result = base().with_facts(bad).gate()
        assert result.state is INCOMPLETE, bad.id


def test_a_valid_allocation_corrected_by_an_invalid_one_is_incomplete() -> None:
    good = make_fact("alloc-ok", FactKind.FABRIC_ALLOCATION, f"alloc:O2:{QUALITY}:NAVY", {"qty": kg("400")})
    fix = make_fact(
        "alloc-fix",
        FactKind.FABRIC_ALLOCATION,
        f"alloc:O2:{QUALITY}:NAVY",
        {"qty": {"value": "x", "unit": "kg"}},
        supersedes_id="alloc-ok",
        known_at=AS_OF + 30 * MINUTE,
    )
    assert base().with_facts(good).gate().state is READY
    assert base().with_facts(good, fix).gate().state is INCOMPLETE


# --- units on everything the FABRIC arithmetic reads ---------------------------


def metres(kind: FactKind, key: str, fact_id: str, **payload: Any) -> Fact:
    return make_fact(fact_id, kind, key, {"qty": {"value": "100", "unit": "m"}, **payload})


def inbound_in_metres() -> Fact:
    return metres(
        FactKind.FABRIC_INBOUND,
        "inbound:R2",
        "in-m",
        fabric_quality=QUALITY,
        colour="NAVY",
        eta=date(2026, 3, 6),
        supplier="S",
    )


def qc_in_metres() -> Fact:
    return metres(
        FactKind.FABRIC_QC, "lot:LOT-N1", "qc-m", issue="defect", review_state="rejected", origin="notes"
    )


def allocation_in_metres() -> Fact:
    return metres(FactKind.FABRIC_ALLOCATION, f"alloc:O2:{QUALITY}:NAVY", "al-m")


@pytest.mark.parametrize("build", [inbound_in_metres, qc_in_metres, allocation_in_metres])
def test_other_quantities_in_another_unit_need_gsm_and_width_too(build: Any) -> None:
    fact: Fact = build()
    result = base().with_facts(fact).gate()
    assert result.state is INCOMPLETE
    assert finding(result, "gsm_width_missing").fact_ids == (fact.id,)
    # GSM and width on a current lot of the same quality and colour settle it.
    navy = base().get("w-lot-navy")
    with_factors = base().replace_fact(
        "w-lot-navy", payload={**navy.payload, "gsm": "180", "width_m": "1.5"}
    )
    assert with_factors.with_facts(fact).gate().state is READY
    # ...but only for that colour.
    white = base().get("w-lot-white")
    wrong_colour = base().replace_fact(
        "w-lot-white", payload={**white.payload, "gsm": "180", "width_m": "1.5"}
    )
    assert wrong_colour.with_facts(fact).gate().state is INCOMPLETE


def test_a_matching_unit_needs_no_factors_and_other_colours_are_ignored() -> None:
    same_unit = inbound_fact("in-kg", "R3")
    red = metres(
        FactKind.FABRIC_INBOUND,
        "inbound:R4",
        "in-red",
        fabric_quality=QUALITY,
        colour="RED",
        eta=date(2026, 3, 6),
        supplier="S",
    )
    assert base().with_facts(same_unit, red).gate().state is READY


# --- reviewed resolutions only ------------------------------------------------


def test_a_resolution_must_come_from_the_review_queue_and_name_a_reviewer() -> None:
    world = qc_world()
    from_notes = resolution_fact(
        "res-n",
        "lot:LOT-N1",
        rule_id="qc_claims_against_lot",
        left_fact_id="w-lot-navy",
        right_fact_id="qc-1",
        source=SourceProfile.NOTES,
        known_at=CUTOFF - MINUTE,
        valid_from=CUTOFF - MINUTE,
    )
    assert world.with_facts(from_notes).gate().state is CONFLICTING
    blank = from_notes.model_copy(
        update={
            "id": "res-b",
            "source": SourceProfile.REVIEW_QUEUE,
            "payload": {**from_notes.payload, "reviewer": "   "},
        }
    )
    assert world.with_facts(blank).gate().state is CONFLICTING
    empty = blank.model_copy(update={"id": "res-e", "payload": {**blank.payload, "reviewer": ""}})
    assert world.with_facts(empty).snapshot().findings, "an empty reviewer is not a valid payload"
    assert world.with_facts(empty).gate().state is CONFLICTING
    reviewed = blank.model_copy(
        update={"id": "res-ok", "payload": {**blank.payload, "reviewer": "owner"}}
    )
    assert world.with_facts(reviewed).gate().state is READY


# --- dates the calendar cannot hold --------------------------------------------


@pytest.mark.parametrize("ship_date", [date(1, 1, 5), date(1, 1, 1), date(9999, 12, 31)])
def test_dates_outside_the_calendar_are_a_finding_not_an_exception(ship_date: date) -> None:
    order = order_fact(ship_date=ship_date, valid_from=CUTOFF - 12 * HOUR)
    world = base().replace_fact("w-order", payload=order.payload)
    result = world.gate()
    assert result.state is INCOMPLETE
    if ship_date.year == 1:
        assert finding(result, "bad_dates").entity_key == ORDER_KEY


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


def tied_inbound(second_eta: date = date(2026, 3, 9)) -> World:
    """Two inbound facts for one delivery that start together and name different ETAs."""
    first = inbound_fact("ib-1", "I1", eta=date(2026, 3, 6))
    second = inbound_fact("ib-2", "I1", eta=second_eta)
    return base().with_facts(first, second)


def inbound_resolution(left: str, right: str) -> Fact:
    return resolution_fact(
        "res-ib",
        "inbound:I1",
        rule_id="inbound_eta_disagrees",
        left_fact_id=left,
        right_fact_id=right,
        known_at=CUTOFF - MINUTE,
        valid_from=CUTOFF - MINUTE,
    )


def test_a_newer_observation_replaces_the_older_so_it_is_not_a_disagreement() -> None:
    # Two exports, ETA moved from 6 Mar to 9 Mar: the second replaces the first.
    first = inbound_fact("ib-1", "I1", eta=date(2026, 3, 6), valid_from=AS_OF - 5 * HOUR)
    second = inbound_fact("ib-2", "I1", eta=date(2026, 3, 9))
    assert base().with_facts(first, second).gate().state is READY


def test_valid_to_on_an_older_observation_is_ignored() -> None:
    first = inbound_fact(
        "ib-1", "I1", eta=date(2026, 3, 6), valid_from=AS_OF - 5 * HOUR, valid_to=CUTOFF + 99 * HOUR
    )
    second = inbound_fact("ib-2", "I1", eta=date(2026, 3, 9))
    assert base().with_facts(first, second).gate().state is READY


def test_a_lots_valid_to_does_not_end_the_observation() -> None:
    # The lot export says valid_to is half an hour in; the observation is still the current one.
    lot = lot_fact("w-lot-navy", "LOT-N1", "NAVY", "500", valid_to=AS_OF + 30 * MINUTE)
    world = base().without(fact_id="w-lot-navy").with_facts(lot)
    late_claim = qc_fact(
        "qc-late", "LOT-N1", "50", valid_from=AS_OF + 45 * MINUTE, known_at=AS_OF + 55 * MINUTE
    )
    assert world.with_facts(late_claim).gate().state is CONFLICTING


def test_rules_pair_only_the_current_observation() -> None:
    # An old lot observation overlapped by a QC claim, but a newer observation has replaced it.
    old = lot_fact("lot-old", "LOT-N1", "NAVY", "500", valid_from=CUTOFF - 30 * HOUR)
    world = (
        base()
        .without(fact_id="w-lot-navy")
        .with_facts(
            old,
            lot_fact("lot-new", "LOT-N1", "NAVY", "500", valid_from=CUTOFF - 2 * HOUR),
            qc_fact("qc-1", "LOT-N1", "50", valid_from=CUTOFF - 20 * HOUR),
        )
    )
    result = world.gate()
    assert finding(result, "conflict_rule").fact_ids == ("lot-new", "qc-1")
    # Resolving the pair with the superseded observation does not clear the real one.
    stale_pair = resolution_fact(
        "res-old",
        "lot:LOT-N1",
        rule_id="qc_claims_against_lot",
        left_fact_id="lot-old",
        right_fact_id="qc-1",
        known_at=CUTOFF - MINUTE,
        valid_from=CUTOFF - MINUTE,
    )
    assert world.with_facts(stale_pair).gate().state is CONFLICTING


def test_inbound_etas_disagreeing_with_the_same_start_conflict() -> None:
    result = tied_inbound().gate()
    assert result.state is CONFLICTING
    conflict = finding(result, "conflict_rule")
    assert conflict.rule_id == "inbound_eta_disagrees"
    assert conflict.entity_key == "inbound:I1"
    assert set(conflict.fact_ids) == {"ib-1", "ib-2"}
    assert "tie_conflict" not in codes(result), "the rule owns this disagreement"


def test_inbound_etas_that_agree_do_not_conflict() -> None:
    assert tied_inbound(second_eta=date(2026, 3, 6)).gate().state is READY


def test_inbound_facts_that_tie_for_another_reason_are_a_tie_conflict() -> None:
    first = inbound_fact("ib-1", "I1", qty="200")
    second = inbound_fact("ib-2", "I1", qty="300")
    result = base().with_facts(first, second).gate()
    assert result.state is CONFLICTING
    assert codes(result, CONFLICTING) == {"tie_conflict"}


def test_inbound_conflict_is_cleared_by_a_resolution_for_that_pair() -> None:
    world = tied_inbound()
    assert world.with_facts(inbound_resolution("ib-1", "ib-2")).gate().state is READY
    # The rule is symmetric, so the resolution may name the pair either way round.
    assert world.with_facts(inbound_resolution("ib-2", "ib-1")).gate().state is READY


def test_inbound_for_another_colour_or_quality_is_not_this_orders_business() -> None:
    first = inbound_fact("ib-1", "I1", "RED", eta=date(2026, 3, 6))
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


# ---------------------------------------------------------------------------
# One defect at a time: never READY, and the state is the right one
# ---------------------------------------------------------------------------

WORKING = working_days(DEFAULT_POLICY_V1, SHIP_DATE)
REQUIRED_FACT_IDS = (
    ["w-order", "w-bom", "w-lot-navy", "w-lot-white", "w-trim-LABEL", "w-trim-ZIP"]
    + [f"w-cap-{ln}-{d.isoformat()}" for ln in ("L1", "L2", "L3", "L4") for d in WORKING]
)
LIMIT_HOURS = {"w-order": 168, "w-bom": 168, "w-lot-navy": 24, "w-lot-white": 24}
LIMIT_HOURS |= {"w-trim-LABEL": 48, "w-trim-ZIP": 48}


def limit_for(fact_id: str) -> int:
    return LIMIT_HOURS.get(fact_id, 24)


def twin_of(fact: Fact) -> Fact:
    """Same valid_from, different semantic payload."""
    changes: dict[FactKind, dict[str, Any]] = {
        FactKind.ORDER_REQUEST: {"order_value_inr": "1"},
        FactKind.BOM: {"sam_minutes": "99"},
        FactKind.FABRIC_LOT: {"qty": kg("1")},
        FactKind.TRIM_STATUS: {"supplier": "SUP-X"},
        FactKind.LINE_CAPACITY: {"available_minutes": {"value": "1", "unit": "minutes"}},
    }
    return fact.model_copy(
        update={"id": f"twin-{fact.id}", "payload": {**fact.payload, **changes[fact.kind]}}
    )


def replacement(fact: Fact, suffix: str, minutes: int) -> Fact:
    """A correction: same kind, entity and valid time, known later."""
    return fact.model_copy(
        update={
            "id": f"{fact.id}-{suffix}",
            "supersedes_id": fact.id,
            "known_at": fact.known_at + minutes * MINUTE,
        }
    )


def only(world: World, fact_id: str) -> Fact:
    return world.get(fact_id)


Defect = tuple[World, GateState]


@st.composite
def one_defect(draw: st.DrawFn) -> tuple[str, Defect]:
    world = BASE_WORLD
    name = draw(
        st.sampled_from(
            [
                "missing_required",
                "stale",
                "tie",
                "competing",
                "invalid_required",
                "invalid_other_kind",
                "qc_claim",
                "inbound_disagreement",
                "unit_mismatch",
                "uncovered",
                "old_coverage",
                "older_artifact_covers",
            ]
        )
    )
    fact_id = draw(st.sampled_from(REQUIRED_FACT_IDS))
    target = world.get(fact_id)
    match name:
        case "missing_required":
            required = [i for i in REQUIRED_FACT_IDS if not i.startswith("w-lot")]
            gone = draw(st.sampled_from(required))
            return name, (world.without(fact_id=gone), INCOMPLETE)
        case "stale":
            extra = draw(st.integers(1, 5000))
            old = CUTOFF - limit_for(fact_id) * HOUR - extra * MINUTE
            return name, (world.replace_fact(fact_id, valid_from=old), STALE)
        case "tie":
            return name, (world.with_facts(twin_of(target)), CONFLICTING)
        case "competing":
            both = [replacement(target, "a", 1), replacement(target, "b", 2)]
            return name, (world.with_facts(*both), CONFLICTING)
        case "invalid_required":
            return name, (world.replace_fact(fact_id, payload={"junk": "x"}), INCOMPLETE)
        case "invalid_other_kind":
            kind, key, _ = draw(
                st.sampled_from([c for c in INVALID_CASES if c[2] and c[0] != FactKind.FABRIC_LOT])
            )
            return name, (world.with_facts(junk("bad", kind, key)), INCOMPLETE)
        case "qc_claim":
            state = draw(st.sampled_from(["checks_passed", "confirmed", "needs_review"]))
            lot_id = draw(st.sampled_from(["LOT-N1", "LOT-W1"]))
            claim = qc_fact("qc-x", lot_id, "5", review_state=state, valid_from=AS_OF - HOUR)
            return name, (world.with_facts(claim), CONFLICTING)
        case "inbound_disagreement":
            colour = draw(st.sampled_from(["NAVY", "WHITE"]))
            pair = (
                inbound_fact("ib-1", "I1", colour, eta=date(2026, 3, 6)),
                inbound_fact("ib-2", "I1", colour, eta=date(2026, 3, 7)),
            )
            return name, (world.with_facts(*pair), CONFLICTING)
        case "unit_mismatch":
            return name, (world.replace_fact("w-bom", payload=bom_fact(unit="m").payload), INCOMPLETE)
        case "uncovered":
            lot = draw(st.sampled_from(["LOT-N1", "LOT-W1"]))
            wrong = draw(st.sampled_from([{}, cover("X")]))
            return name, (world.without(entity_key=f"lot:{lot}").with_coverage(wrong), INCOMPLETE)
        case "old_coverage":
            lot = draw(st.sampled_from(["LOT-N1", "LOT-W1"]))
            age = draw(st.integers(24 * 60 + 1, 20_000))
            stale = cover(QUALITY, as_of=CUTOFF - age * MINUTE)
            return name, (world.without(entity_key=f"lot:{lot}").with_coverage(stale), STALE)
        case _:  # older_artifact_covers
            lot = draw(st.sampled_from(["LOT-N1", "LOT-W1"]))
            mixed = {
                **cover(QUALITY, artifact_id="a-old", as_of=AS_OF - 3 * HOUR),
                **cover("X", artifact_id="a-new", as_of=AS_OF),
            }
            return name, (world.without(entity_key=f"lot:{lot}").with_coverage(mixed), INCOMPLETE)


@settings(max_examples=250, deadline=None)
@given(one_defect())
def test_exactly_one_defect_is_never_ready(drawn: tuple[str, Defect]) -> None:
    name, (world, expected) = drawn
    result = world.gate()
    assert result.state is not READY, name
    assert result.state is expected, (name, [(f.code, f.state) for f in result.findings])


@st.composite
def ready_variants(draw: st.DrawFn) -> tuple[World, datetime]:
    """Policies, ship dates and extra irrelevant facts, with every required fact fresh."""
    cut = draw(st.integers(5, 40))
    data = DEFAULT_POLICY_V1.model_dump(mode="json")
    ship = date(2026, 4, 1) + timedelta(days=draw(st.integers(0, 120)))
    window = [ship - timedelta(days=n) for n in range(0, cut + 2)]
    data["capacity"].update(
        cut_to_ship_days=cut,
        finishing_days=draw(st.integers(0, cut - 1)),
        eligible_lines=draw(
            st.lists(st.sampled_from(["L1", "L2", "L3", "L4", "L5", "L6"]), min_size=1, unique=True)
        ),
        non_working_weekdays=draw(
            st.lists(
                st.sampled_from(["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]), unique=True
            )
        ),
        holidays=[d.isoformat() for d in draw(st.lists(st.sampled_from(window), unique=True, max_size=5))],
    )
    policy = PolicyDocument.model_validate(data)
    world = ready_world(policy, ship)
    extras: list[Fact] = []
    if draw(st.booleans()):
        extras.append(lot_fact("x-red", "LOT-R1", "RED", "10"))
    if draw(st.booleans()):
        extras.append(trim_fact("x-trim", "ZIP", style_id="S9"))
    if draw(st.booleans()):
        extras.append(capacity_fact("x-cap", "L1", ship + timedelta(days=3)))
    if draw(st.booleans()):
        extras.append(
            make_fact("x-alloc", FactKind.FABRIC_ALLOCATION, "alloc:O2:OTHERQ:NAVY", {"qty": kg("5")})
        )
    shift = draw(st.integers(0, 23 * 60))  # minutes later than CUTOFF; lots stay inside 24 h
    return world.with_facts(*extras), CUTOFF + shift * MINUTE


@settings(max_examples=120, deadline=None)
@given(ready_variants())
def test_worlds_with_every_required_fact_fresh_are_ready(drawn: tuple[World, datetime]) -> None:
    world, cutoff = drawn
    result = world.gate(cutoff)
    assert result.state is READY, [(f.code, f.entity_key) for f in result.findings]
    assert all(f.state is READY for f in result.findings)
