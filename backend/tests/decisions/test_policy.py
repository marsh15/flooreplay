"""Policy documents: digest identity, parameter diff, predicate registry, defaults."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from decisions.worlds import inbound_fact, lot_fact, qc_fact
from flooreplay.decisions.policy import (
    DEFAULT_POLICY_V1,
    ENGINE_VERSION,
    PREDICATES,
    PolicyDocument,
    cut_date,
    parameter_diff,
    policy_digest,
    sewing_days,
)
from flooreplay.decisions.types import ConstraintId, FactKind


def doc(**overrides: Any) -> PolicyDocument:
    """DEFAULT_POLICY_V1 with the given top-level fields replaced (via a JSON round trip)."""
    data = DEFAULT_POLICY_V1.model_dump(mode="json")
    data.update(overrides)
    return PolicyDocument.model_validate(data)


def with_capacity(**changes: Any) -> PolicyDocument:
    capacity = DEFAULT_POLICY_V1.model_dump(mode="json")["capacity"]
    return doc(capacity={**capacity, **changes})


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------


def test_default_policy_matches_the_discovery_draft() -> None:
    p = DEFAULT_POLICY_V1
    assert p.label == "Tiruppur default v1"
    assert p.engine_version == ENGINE_VERSION == "decision-v1"
    assert p.freshness_hours.model_dump() == {
        "erp_fabric_stock": 24,
        "sheet_trims_status": 48,
        "shift_capacity": 24,
        "supplier_updates": 72,
        "notes": 24,
        "order_requests": 168,
    }
    assert (p.fabric.wastage_pct, p.fabric.inbound_buffer_days, p.fabric.safety_floor_pct) == (
        Decimal("0.05"),
        2,
        Decimal("0.05"),
    )
    assert (p.trims.wastage_pct, p.trims.buffer_days) == (Decimal("0.03"), 2)
    cap = p.capacity
    assert cap.eligible_lines == ("L1", "L2", "L3", "L4")
    assert cap.default_efficiency_pct == Decimal("0.55")
    assert (cap.cut_to_ship_days, cap.finishing_days, cap.ot_cap_hours_per_line_day) == (21, 4, 2)
    assert [d.value for d in cap.non_working_weekdays] == ["SUN"]
    assert cap.holidays == ()
    assert (p.approval.max_value_inr, p.approval.max_qty_pcs) == (Decimal("5000000"), 20000)
    assert {r.id for r in p.conflict_rules} == {"qc_claims_against_lot", "inbound_eta_disagrees"}
    assert set(p.enabled_constraints) == set(ConstraintId)


def test_default_conflict_rules_shape() -> None:
    rules = {r.id: r for r in DEFAULT_POLICY_V1.conflict_rules}
    qc = rules["qc_claims_against_lot"]
    assert (qc.left_kind, qc.right_kind) == (FactKind.FABRIC_LOT, FactKind.FABRIC_QC)
    assert (qc.join, qc.valid_time, qc.predicate) == ("entity_key", "overlap", qc.id)
    eta = rules["inbound_eta_disagrees"]
    assert (eta.left_kind, eta.right_kind) == (FactKind.FABRIC_INBOUND, FactKind.FABRIC_INBOUND)


def test_policy_is_frozen() -> None:
    with pytest.raises(ValidationError):
        DEFAULT_POLICY_V1.label = "other"  # type: ignore[misc]


def test_json_round_trip_keeps_the_digest() -> None:
    text = json.dumps(DEFAULT_POLICY_V1.model_dump(mode="json"))
    again = PolicyDocument.model_validate_json(text)
    assert again == DEFAULT_POLICY_V1
    assert policy_digest(again) == policy_digest(DEFAULT_POLICY_V1)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(unexpected=1),
        lambda d: d["fabric"].update(wastage_pct=0.05),  # floats are rejected
        lambda d: d["fabric"].update(inbound_buffer_days=-1),
        lambda d: d["capacity"].update(non_working_weekdays=["FUNDAY"]),
        lambda d: d["capacity"].update(eligible_lines=["L1", "L1"]),
        lambda d: d["capacity"].update(holidays=["2026-03-10", "2026-03-10"]),
        lambda d: d["capacity"].update(default_efficiency_pct="0"),
        lambda d: d.update(enabled_constraints=["FABRIC", "FABRIC"]),
        lambda d: d.update(conflict_rules=[*d["conflict_rules"], d["conflict_rules"][0]]),
        lambda d: d["conflict_rules"][0].update(join="payload"),
        lambda d: d["conflict_rules"][0].update(valid_time="exact"),
        lambda d: d.update(engine_version="decision-v0"),
        # bounds and relations (reviewer-found holes)
        lambda d: d["capacity"].update(eligible_lines=[]),
        lambda d: d.update(enabled_constraints=[]),
        lambda d: d["capacity"].update(finishing_days=21),  # not before cut_to_ship_days
        lambda d: d["capacity"].update(finishing_days=40),
        lambda d: d["capacity"].update(cut_to_ship_days=366),
        lambda d: d["capacity"].update(default_efficiency_pct="1.01"),
        lambda d: d["capacity"].update(default_efficiency_pct="55"),
        lambda d: d["capacity"].update(ot_cap_hours_per_line_day=25),
        lambda d: d["capacity"].update(eligible_lines=["L:1"]),
        lambda d: d["fabric"].update(wastage_pct="-0.1"),
        lambda d: d["fabric"].update(wastage_pct="1"),
        lambda d: d["fabric"].update(safety_floor_pct="-1"),
        lambda d: d["fabric"].update(inbound_buffer_days=366),
        lambda d: d["trims"].update(wastage_pct="-0.5"),
        lambda d: d["trims"].update(buffer_days=10**9),
        lambda d: d["approval"].update(max_value_inr="-1"),
        lambda d: d["freshness_hours"].update(notes=10**12),
        lambda d: d["freshness_hours"].update(notes=24 * 30 + 1),
        lambda d: d["freshness_hours"].update(notes=-1),
        lambda d: d["conflict_rules"][0].update(id="a].left_kind"),
        lambda d: d["conflict_rules"][0].update(id=""),
        lambda d: d["conflict_rules"][0].update(id="has space"),
        # a predicate only makes sense for the kinds it was written for
        lambda d: d["conflict_rules"][0].update(left_kind="trim_status", right_kind="bom"),
        lambda d: d["conflict_rules"][1].update(left_kind="fabric_allocation"),
    ],
)
def test_malformed_documents_are_rejected(mutate: Callable[[dict[str, Any]], None]) -> None:
    data = DEFAULT_POLICY_V1.model_dump(mode="json")
    mutate(data)
    with pytest.raises(ValidationError):
        PolicyDocument.model_validate(data)


# ---------------------------------------------------------------------------
# Predicate registry
# ---------------------------------------------------------------------------


def test_unknown_predicate_is_rejected_at_construction() -> None:
    rules = [r.model_dump(mode="json") for r in DEFAULT_POLICY_V1.conflict_rules]
    rules.append(
        {
            "id": "made_up",
            "left_kind": "fabric_lot",
            "right_kind": "fabric_qc",
            "join": "entity_key",
            "valid_time": "overlap",
            "predicate": "does_not_exist",
        }
    )
    with pytest.raises(ValidationError, match="does_not_exist"):
        doc(conflict_rules=rules)


def test_registry_is_closed_and_covers_the_default_rules() -> None:
    assert set(PREDICATES) == {"qc_claims_against_lot", "inbound_eta_disagrees"}
    assert {r.predicate for r in DEFAULT_POLICY_V1.conflict_rules} <= set(PREDICATES)


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ("checks_passed", True),
        ("confirmed", True),
        ("needs_review", True),
        ("corrected", False),
        ("rejected", False),
    ],
)
def test_qc_claims_against_lot_by_review_state(state: str, expected: bool) -> None:
    lot = lot_fact("lot", "X1", "NAVY", "500")
    qc = qc_fact("qc", "X1", "50", review_state=state)
    assert PREDICATES["qc_claims_against_lot"](lot, qc) is expected


def test_qc_claims_against_lot_needs_the_same_entity_and_a_positive_claim() -> None:
    predicate = PREDICATES["qc_claims_against_lot"]
    lot = lot_fact("lot", "X1", "NAVY", "500")
    assert not predicate(lot, qc_fact("qc", "X2", "50"))
    assert not predicate(lot, qc_fact("qc", "X1", "0"))
    # Wrong kinds on either side never match.
    assert not predicate(qc_fact("qc", "X1", "50"), lot)


def test_inbound_eta_disagrees_only_on_different_etas_for_one_entity() -> None:
    predicate = PREDICATES["inbound_eta_disagrees"]
    a = inbound_fact("a", "I1", eta=date(2026, 3, 6))
    assert predicate(a, inbound_fact("b", "I1", eta=date(2026, 3, 9)))
    assert not predicate(a, inbound_fact("b", "I1", eta=date(2026, 3, 6)))
    assert not predicate(a, inbound_fact("b", "I2", eta=date(2026, 3, 9)))
    assert not predicate(a, lot_fact("c", "I1", "NAVY"))


# ---------------------------------------------------------------------------
# Digest
# ---------------------------------------------------------------------------


def test_digest_is_stable_and_prefixed() -> None:
    assert policy_digest(DEFAULT_POLICY_V1) == policy_digest(DEFAULT_POLICY_V1)
    assert policy_digest(DEFAULT_POLICY_V1).startswith("sha256:")


@settings(deadline=None)
@given(st.randoms(use_true_random=False))
def test_digest_is_stable_under_reordering_set_like_lists(rnd: Any) -> None:
    data = DEFAULT_POLICY_V1.model_dump(mode="json")
    data["capacity"]["holidays"] = ["2026-03-12", "2026-03-10", "2026-03-11"]
    data["capacity"]["non_working_weekdays"] = ["SAT", "SUN"]
    baseline = PolicyDocument.model_validate(data)

    shuffled = json.loads(json.dumps(data))
    for path in (
        ("capacity", "eligible_lines"),
        ("capacity", "holidays"),
        ("capacity", "non_working_weekdays"),
    ):
        rnd.shuffle(shuffled[path[0]][path[1]])
    rnd.shuffle(shuffled["enabled_constraints"])
    rnd.shuffle(shuffled["conflict_rules"])

    other = PolicyDocument.model_validate(shuffled)
    assert policy_digest(other) == policy_digest(baseline)
    assert other == baseline
    assert parameter_diff(baseline, other) == []


def test_digest_changes_when_any_parameter_changes() -> None:
    base = policy_digest(DEFAULT_POLICY_V1)
    assert policy_digest(doc(label="another label")) != base
    assert policy_digest(with_capacity(cut_to_ship_days=22)) != base
    assert policy_digest(with_capacity(holidays=["2026-03-10"])) != base
    assert policy_digest(with_capacity(eligible_lines=["L1", "L2"])) != base


def test_decimal_spelling_does_not_change_the_digest() -> None:
    fabric = DEFAULT_POLICY_V1.model_dump(mode="json")["fabric"]
    same = doc(fabric={**fabric, "wastage_pct": "0.0500"})
    assert policy_digest(same) == policy_digest(DEFAULT_POLICY_V1)


# ---------------------------------------------------------------------------
# Parameter diff
# ---------------------------------------------------------------------------


def test_diff_of_equal_policies_is_empty() -> None:
    assert parameter_diff(DEFAULT_POLICY_V1, DEFAULT_POLICY_V1) == []


def test_diff_lists_only_changed_leaf_paths() -> None:
    fabric = DEFAULT_POLICY_V1.model_dump(mode="json")["fabric"]
    after = with_capacity(finishing_days=5)
    after = PolicyDocument.model_validate(
        {
            **after.model_dump(mode="json"),
            "fabric": {**fabric, "wastage_pct": "0.07"},
            "label": "candidate",
        }
    )
    diff = parameter_diff(DEFAULT_POLICY_V1, after)
    assert diff == [
        {"path": "capacity.finishing_days", "before": 4, "after": 5},
        {"path": "fabric.wastage_pct", "before": "0.05", "after": "0.07"},
        {"path": "label", "before": "Tiruppur default v1", "after": "candidate"},
    ]


def test_diff_compares_set_like_lists_as_wholes() -> None:
    after = with_capacity(eligible_lines=["L1", "L2"], holidays=["2026-03-10"])
    assert parameter_diff(DEFAULT_POLICY_V1, after) == [
        {
            "path": "capacity.eligible_lines",
            "before": ["L1", "L2", "L3", "L4"],
            "after": ["L1", "L2"],
        },
        {"path": "capacity.holidays", "before": [], "after": ["2026-03-10"]},
    ]


def test_diff_of_enabled_constraints() -> None:
    after = doc(enabled_constraints=["FABRIC", "SAFETY", "TRIMS", "CAPACITY", "APPROVAL"])
    assert parameter_diff(DEFAULT_POLICY_V1, after) == [
        {
            "path": "enabled_constraints",
            "before": ["APPROVAL", "CAPACITY", "FABRIC", "OVERTIME", "SAFETY", "TRIMS"],
            "after": ["APPROVAL", "CAPACITY", "FABRIC", "SAFETY", "TRIMS"],
        }
    ]


def test_diff_of_conflict_rules_is_by_id() -> None:
    rules = [r.model_dump(mode="json") for r in DEFAULT_POLICY_V1.conflict_rules]
    # Change one field of one rule, reorder, and the diff names just that leaf.
    changed = [dict(r) for r in rules]
    for rule in changed:
        if rule["id"] == "inbound_eta_disagrees":
            rule.update(
                left_kind="fabric_lot", right_kind="fabric_qc", predicate="qc_claims_against_lot"
            )
    changed.reverse()
    assert parameter_diff(DEFAULT_POLICY_V1, doc(conflict_rules=changed)) == [
        {
            "path": "conflict_rules[inbound_eta_disagrees].left_kind",
            "before": "fabric_inbound",
            "after": "fabric_lot",
        },
        {
            "path": "conflict_rules[inbound_eta_disagrees].predicate",
            "before": "inbound_eta_disagrees",
            "after": "qc_claims_against_lot",
        },
        {
            "path": "conflict_rules[inbound_eta_disagrees].right_kind",
            "before": "fabric_inbound",
            "after": "fabric_qc",
        },
    ]


def test_diff_of_added_and_removed_conflict_rules() -> None:
    rules = [r.model_dump(mode="json") for r in DEFAULT_POLICY_V1.conflict_rules]
    removed = doc(conflict_rules=[r for r in rules if r["id"] != "qc_claims_against_lot"])
    [entry] = parameter_diff(DEFAULT_POLICY_V1, removed)
    assert entry["path"] == "conflict_rules[qc_claims_against_lot]"
    assert entry["after"] is None
    assert entry["before"]["predicate"] == "qc_claims_against_lot"
    [back] = parameter_diff(removed, DEFAULT_POLICY_V1)
    assert (back["path"], back["before"]) == ("conflict_rules[qc_claims_against_lot]", None)


@settings(deadline=None)
@given(st.integers(5, 365), st.integers(5, 365))
def test_diff_is_empty_iff_digests_match(a: int, b: int) -> None:
    left, right = with_capacity(cut_to_ship_days=a), with_capacity(cut_to_ship_days=b)
    assert (parameter_diff(left, right) == []) == (policy_digest(left) == policy_digest(right))


def test_boundary_values_are_accepted() -> None:
    capacity = DEFAULT_POLICY_V1.model_dump(mode="json")["capacity"]
    edge = doc(
        capacity={
            **capacity,
            "default_efficiency_pct": "1",
            "cut_to_ship_days": 365,
            "finishing_days": 364,
            "ot_cap_hours_per_line_day": 24,
        },
        freshness_hours={**DEFAULT_POLICY_V1.model_dump(mode="json")["freshness_hours"], "notes": 720},
        fabric={**DEFAULT_POLICY_V1.model_dump(mode="json")["fabric"], "wastage_pct": "0"},
    )
    assert edge.capacity.cut_to_ship_days == 365


def test_sewing_days_follow_the_window_and_calendar() -> None:
    days = sewing_days(DEFAULT_POLICY_V1.capacity, date(2026, 3, 30))
    assert days[0] == date(2026, 3, 10) and days[-1] == date(2026, 3, 26)
    assert date(2026, 3, 15) not in days  # a Sunday
    assert cut_date(DEFAULT_POLICY_V1.capacity, date(2026, 3, 30)) == date(2026, 3, 9)
