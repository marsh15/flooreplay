"""v2 types, units and canonical digest, plus the pin that v1 digests did not move."""

from __future__ import annotations

import unicodedata
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from decisions.strategies import fact_histories, facts, quantities
from flooreplay.decisions.types import (
    Classification,
    ConstraintId,
    ConstraintStatus,
    Fact,
    FactKind,
    GateState,
    Quantity,
    Recommendation,
    ReviewState,
    SourceProfile,
    Unit,
    UnitMismatch,
    Verdict,
    canonical,
    combine_gate_states,
    decision_digest,
    kg_to_m,
    quantize_available,
    quantize_required,
)
from flooreplay.domain import hashing
from flooreplay.domain.hashing import digest, incident_digest

T0 = datetime(2026, 3, 1, 10, 0, tzinfo=UTC)


# --- Decimal normalisation -------------------------------------------------


def test_decimal_trailing_zeros_do_not_change_digest():
    assert decision_digest({"q": Decimal("1.500")}) == decision_digest({"q": Decimal("1.5")})
    assert canonical(Decimal("100")) == "100"
    assert canonical(Decimal("1E+2")) == "100"
    assert canonical(Decimal("0.0010")) == "0.001"


def test_negative_zero_equals_zero():
    assert canonical(Decimal("-0")) == "0"
    assert canonical(Decimal("-0.000")) == "0"
    assert decision_digest(Decimal("-0")) == decision_digest(Decimal("0.000"))


def test_distinct_decimals_digest_differently():
    assert decision_digest(Decimal("1.5")) != decision_digest(Decimal("1.501"))


@pytest.mark.parametrize("bad", [Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")])
def test_non_finite_decimals_are_rejected(bad):
    with pytest.raises(ValueError):
        canonical(bad)


def test_floats_are_rejected_by_canonical():
    with pytest.raises(ValueError):
        canonical({"x": 1.5})


def test_datetimes_become_utc_z_strings():
    ist = timezone(timedelta(hours=5, minutes=30))
    assert canonical(datetime(2026, 3, 1, 15, 30, tzinfo=ist)) == "2026-03-01T10:00:00Z"
    with pytest.raises(ValueError):
        canonical(datetime(2026, 3, 1, 10, 0))


def test_lists_keep_their_order_and_keys_are_sorted():
    # `slots` is in v1's _SORTED_COLLECTION_HINTS; v2 must not rely on it.
    assert canonical({"slots": ["b", "a"], "a": 1}) == {"a": 1, "slots": ["b", "a"]}
    assert decision_digest({"slots": ["b", "a"]}) != decision_digest({"slots": ["a", "b"]})


def test_models_and_enums_canonicalise_to_plain_values():
    q = Quantity(value=Decimal("2.50"), unit=Unit.KG)
    assert canonical(q) == {"unit": "kg", "value": "2.5"}


def test_decision_digest_shape():
    assert decision_digest({"a": 1}).startswith("sha256:")
    assert len(decision_digest({"a": 1})) == len("sha256:") + 64


# --- Unicode ---------------------------------------------------------------


def test_tamil_nfd_and_nfc_digest_identically():
    nfc = "கொடு தமிழ்நாடு"
    nfd = unicodedata.normalize("NFD", nfc)
    assert nfd != nfc
    assert decision_digest({"note": nfc}) == decision_digest({"note": nfd})
    assert decision_digest({nfc: 1}) == decision_digest({nfd: 1})


# --- Quantity --------------------------------------------------------------


def test_quantity_normalises_to_three_places():
    assert Quantity(value="1.5", unit=Unit.KG).value == Decimal("1.500")
    assert str(Quantity(value=2, unit=Unit.PCS).value) == "2.000"
    assert Quantity(value=Decimal("1.2345"), unit=Unit.M).value == Decimal("1.234")


def test_quantity_rejects_float():
    with pytest.raises(ValidationError):
        Quantity(value=1.5, unit=Unit.KG)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", ["NaN", "inf", "-Infinity", "abc", True, None])
def test_quantity_rejects_non_finite_or_junk(bad):
    with pytest.raises(ValidationError):
        Quantity(value=bad, unit=Unit.KG)


def test_quantity_is_frozen_and_rejects_extras():
    q = Quantity(value="1", unit=Unit.KG)
    with pytest.raises(ValidationError):
        q.value = Decimal("2")  # type: ignore[misc]
    with pytest.raises(ValidationError):
        Quantity(value="1", unit=Unit.KG, extra=1)  # type: ignore[call-arg]


def test_unit_mismatch_is_typed():
    kg = Quantity(value="1", unit=Unit.KG)
    m = Quantity(value="1", unit=Unit.M)
    with pytest.raises(UnitMismatch):
        _ = kg + m
    with pytest.raises(UnitMismatch):
        _ = kg - m
    assert (kg + kg).value == Decimal("2.000")
    assert (kg - kg).value == Decimal("0.000")
    assert isinstance(UnitMismatch("x"), ValueError)


@given(quantities(Unit.KG))
def test_quantity_round_trips_through_json(q):
    assert Quantity.model_validate(q.model_dump(mode="json")) == q
    assert Quantity.model_validate_json(q.model_dump_json()) == q


# --- Rounding --------------------------------------------------------------


def test_required_rounds_up_and_available_rounds_down():
    assert quantize_required(Decimal("1.0001")) == Decimal("1.001")
    assert quantize_available(Decimal("1.0009")) == Decimal("1.000")
    # exact values are untouched
    assert quantize_required(Decimal("1.250")) == Decimal("1.250")
    assert quantize_available(Decimal("1.250")) == Decimal("1.250")


def test_rounding_direction_for_negatives():
    # CEILING moves toward +inf, FLOOR toward -inf.
    assert quantize_required(Decimal("-1.0009")) == Decimal("-1.000")
    assert quantize_available(Decimal("-1.0001")) == Decimal("-1.001")


@given(st.decimals(min_value=-10_000, max_value=10_000, places=6))
def test_required_never_below_and_available_never_above(d):
    assert quantize_required(d) >= d
    assert quantize_available(d) <= d
    assert quantize_required(d) - quantize_available(d) <= Decimal("0.001")


# --- kg -> metres ----------------------------------------------------------


def test_kg_to_m_worked_example():
    # 100 kg of 180 gsm, 1.5 m wide: 100 * 1000 / (180 * 1.5) = 370.370... m
    metres = kg_to_m(Decimal("100"), Decimal("180"), Decimal("1.5"))
    assert metres == Decimal(100_000) / Decimal(270)
    assert quantize_required(metres) == Decimal("370.371")
    assert quantize_available(metres) == Decimal("370.370")
    # exact case: 27 kg of 200 gsm, 1.5 m wide is exactly 90 m
    assert kg_to_m(Decimal("27"), Decimal("200"), Decimal("1.5")) == Decimal("90")


@pytest.mark.parametrize(("gsm", "width"), [("0", "1.5"), ("180", "0"), ("-1", "1.5")])
def test_kg_to_m_rejects_non_positive_gsm_or_width(gsm, width):
    with pytest.raises(ValueError):
        kg_to_m(Decimal("1"), Decimal(gsm), Decimal(width))


# --- Enums -----------------------------------------------------------------


def test_gate_state_precedence():
    assert combine_gate_states([]) is GateState.READY
    assert combine_gate_states([GateState.READY, GateState.STALE]) is GateState.STALE
    assert combine_gate_states([GateState.STALE, GateState.INCOMPLETE]) is GateState.INCOMPLETE
    assert (
        combine_gate_states([GateState.INCOMPLETE, GateState.CONFLICTING, GateState.STALE])
        is GateState.CONFLICTING
    )


def test_enum_vocabulary_matches_the_plan():
    assert {k.value for k in FactKind} == {
        "order_request", "bom", "fabric_lot", "fabric_qc", "fabric_inbound",
        "fabric_allocation", "trim_status", "line_capacity", "line_commitment", "resolution",
    }  # fmt: skip
    assert {u.value for u in Unit} == {"kg", "m", "pcs", "minutes"}
    assert {s.value for s in GateState} == {"READY", "STALE", "INCOMPLETE", "CONFLICTING"}
    assert [c.value for c in ConstraintId] == [
        "FABRIC", "SAFETY", "TRIMS", "CAPACITY", "OVERTIME", "APPROVAL",
    ]  # fmt: skip
    assert {s.value for s in ConstraintStatus} == {"PASS", "FAIL", "NOT_EVALUATED"}
    assert {r.value for r in Recommendation} == {
        "ACCEPT", "ACCEPT_WITH_CONDITIONS", "DECLINE", "NEEDS_REVIEW",
    }  # fmt: skip
    assert {r.value for r in ReviewState} == {
        "checks_passed", "needs_review", "confirmed", "corrected", "rejected",
    }  # fmt: skip
    assert {v.value for v in Verdict} == {"PASS", "FAIL"}
    assert {c.value for c in Classification} == {
        "UNCHANGED_PASS", "UNCHANGED_FAIL", "FIXED", "REGRESSION", "NOT_COMPARABLE",
    }  # fmt: skip
    assert {s.value for s in SourceProfile} == {
        "erp_fabric_stock", "sheet_trims_status", "shift_capacity", "supplier_updates",
        "notes", "order_requests", "review_queue",
    }  # fmt: skip


# --- Fact ------------------------------------------------------------------


def _fact(**overrides):
    base = {
        "id": "F1",
        "kind": FactKind.FABRIC_LOT,
        "entity_key": "lot:L1",
        "payload": {},
        "valid_from": T0,
        "valid_to": None,
        "known_at": T0,
        "supersedes_id": None,
        "source": SourceProfile.ERP_FABRIC_STOCK,
        "artifact_id": None,
    }
    return Fact(**{**base, **overrides})


def test_fact_valid_to_must_follow_valid_from():
    assert _fact(valid_to=T0 + timedelta(minutes=1)).valid_to is not None
    with pytest.raises(ValidationError):
        _fact(valid_to=T0)
    with pytest.raises(ValidationError):
        _fact(valid_to=T0 - timedelta(minutes=1))


def test_fact_rejects_naive_datetimes():
    with pytest.raises(ValidationError):
        _fact(valid_from=datetime(2026, 3, 1, 10, 0))
    with pytest.raises(ValidationError):
        _fact(known_at=datetime(2026, 3, 1, 10, 0))


def test_fact_digest_is_zone_independent():
    ist = timezone(timedelta(hours=5, minutes=30))
    same_instant = _fact(valid_from=T0.astimezone(ist), known_at=T0.astimezone(ist))
    assert decision_digest(same_instant) == decision_digest(_fact())


@given(facts())
def test_generated_facts_are_valid(fact):
    assert fact.valid_to is None or fact.valid_to > fact.valid_from
    assert fact.source is not None


# --- Digest properties -----------------------------------------------------


@given(
    st.dictionaries(st.text(max_size=6), st.integers(), min_size=1, max_size=8),
    st.randoms(use_true_random=False),
)
def test_decision_digest_is_stable_under_key_reordering(mapping, rnd):
    items = list(mapping.items())
    rnd.shuffle(items)
    assert decision_digest(dict(items)) == decision_digest(mapping)


# --- Strategy sanity -------------------------------------------------------


@given(fact_histories())
def test_histories_only_supersede_earlier_facts_of_the_same_entity(history):
    by_id = {f.id: f for f in history}
    assert len(by_id) == len(history)
    for fact in history:
        if fact.supersedes_id is None:
            continue
        target = by_id[fact.supersedes_id]
        assert target.known_at < fact.known_at
        assert (target.kind, target.entity_key) == (fact.kind, fact.entity_key)


# --- v1 digests are pinned unchanged ---------------------------------------


def test_v1_sorted_collection_hints_are_frozen():
    frozen_v1_hints = {
        "aliases",
        "operation_ids",
        "compatible_operation_ids",
        "snapshots",
        "attendance",
        "assignments",
        "skills",
        "machine_state",
        "slots",
        "evidence",
        "gate_issues",
        "constraints",
        "ranking_factors",
        "candidate_exclusions",
        "issue_codes",
        "excluded_operators",
        "required_issue_codes",
        "required_failed_constraints",
        "required_passed_constraints",
        "forbidden_operators",
        "allowed_operators",
    }
    assert frozen_v1_hints == hashing._SORTED_COLLECTION_HINTS


def test_v1_digest_is_pinned():
    sample = {
        "b": ["z", "a"],
        "aliases": ["y", "x"],
        "t": datetime(2026, 3, 1, 10, 0, tzinfo=timezone(timedelta(hours=5, minutes=30))),
        "n": 3,
        "slots": [{"id": "S2"}, {"id": "S1"}],
    }
    assert (
        digest(sample) == "sha256:189ffe08f524dfbc246fb1ed455233a94c48d3cc149c3b93a42169f56784ee56"
    )


def test_v1_incident_digest_is_pinned():
    sample = {
        "cutoff": "2026-03-01T10:00:00+05:30",
        "items": [
            {"available_at": "2026-03-01T04:30:00Z", "k": "b"},
            {"available_at": "2026-03-01T04:00:00Z", "k": "a"},
        ],
        "evidence": ["q", "p"],
    }
    assert (
        incident_digest(sample)
        == "sha256:c5ca8d313b4b3487432fda0ed777572c142f4df9851247c986e7742d68febfec"
    )
