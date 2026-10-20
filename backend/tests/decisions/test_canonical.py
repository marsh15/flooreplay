"""v2 types, units and canonical digest, plus the pin that v1 digests did not move."""

from __future__ import annotations

import json
import unicodedata
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal, Inexact, localcontext

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
    assert Quantity(value=Decimal("1.2340"), unit=Unit.M).value == Decimal("1.234")


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
    st.dictionaries(
        st.text(max_size=6).filter(lambda k: unicodedata.is_normalized("NFC", k)),
        st.integers(),
        min_size=1,
        max_size=8,
    ),
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


# --- Review fixes: context-free canonical text -----------------------------


@pytest.mark.parametrize(
    ("raw", "text"),
    [
        ("1.00000000000000000000000000001", "1.00000000000000000000000000001"),
        ("10000000000000000000000000000000000000001", "10000000000000000000000000000000000000001"),
        ("-1.50", "-1.5"),
        ("1E+2", "100"),
        ("1E-30", "0." + "0" * 29 + "1"),
        ("123456.789", "123456.789"),
        ("-0.00", "0"),
    ],
)
def test_decimal_text_ignores_the_ambient_context(raw, text):
    assert canonical(Decimal(raw)) == text
    with localcontext() as ctx:
        ctx.prec = 5
        assert canonical(Decimal(raw)) == text
    with localcontext() as ctx:
        ctx.traps[Inexact] = True
        assert canonical(Decimal(raw)) == text


# --- Review fixes: one JSON-stable rule ------------------------------------


def test_fact_payload_is_canonicalised_at_construction():
    fact = _fact(
        payload={
            "qty": Decimal("1.50"),
            "when": T0,
            "note": unicodedata.normalize("NFD", "கொ"),
            "rows": [{"v": Decimal("2.000")}, 3],
        }
    )
    assert fact.payload["qty"] == "1.5"
    assert fact.payload["when"] == "2026-03-01T10:00:00Z"
    assert fact.payload["note"] == unicodedata.normalize("NFC", "கொ")
    assert fact.payload["rows"] == ({"v": "2"}, 3)


def test_fact_payload_rejects_floats_and_unknown_types():
    with pytest.raises(ValidationError):
        _fact(payload={"x": 1.5})
    with pytest.raises(ValidationError):
        _fact(payload={"x": {1, 2}})


def test_fact_survives_json_round_trip_with_identical_digest():
    fact = _fact(payload={"qty": Decimal("1.50"), "n": 1000, "rows": [Decimal("5.000"), "x"]})
    reloaded = Fact.model_validate_json(fact.model_dump_json())
    assert reloaded == fact
    assert decision_digest(reloaded) == decision_digest(fact)
    assert Fact.model_validate(fact.model_dump(mode="json")) == fact


def test_ints_and_decimals_are_different_values():
    # Decimals canonicalise to text, ints stay JSON numbers; builders must pick one per field.
    assert decision_digest({"n": 1000}) != decision_digest({"n": Decimal(1000)})
    assert canonical({"n": 1000}) == {"n": 1000}
    assert canonical({"n": Decimal(1000)}) == {"n": "1000"}


def test_quantity_json_form_is_canonical_text():
    q = Quantity(value="5", unit=Unit.KG)
    assert q.value == Decimal("5.000")
    assert q.model_dump(mode="json") == {"value": "5", "unit": "kg"}
    assert q.model_dump(mode="json") == canonical(q)
    assert Quantity.model_validate(q.model_dump(mode="json")) == q


def test_canonical_rejects_colliding_keys():
    with pytest.raises(ValueError):
        canonical({1: "a", "1": "b"})
    nfc, nfd = "\u00e9", "e\u0301"
    with pytest.raises(ValueError):
        canonical({nfc: 1, nfd: 2})


# --- Review fixes: strict Quantity input -----------------------------------


@pytest.mark.parametrize(
    "bad",
    ["1.2345", Decimal("1.0001"), " 1 ", "1_0", "\u0661", "1.", ".5", "+1", "1e3", "--1", ""],
)
def test_quantity_rejects_excess_precision_and_loose_strings(bad):
    with pytest.raises(ValidationError):
        Quantity(value=bad, unit=Unit.KG)


@pytest.mark.parametrize("ok", ["-1", "0", "1.234", 7, -7, Decimal("1.2340"), Decimal("1E+2")])
def test_quantity_accepts_exact_values(ok):
    assert Quantity(value=ok, unit=Unit.KG).value == Decimal(str(ok)).quantize(Decimal("0.001"))


def test_quantity_negative_zero_is_zero():
    for raw in ("-0", "-0.000", Decimal("-0")):
        q = Quantity(value=raw, unit=Unit.KG)
        assert str(q.value) == "0.000"
        assert q.model_dump(mode="json")["value"] == "0"


def test_quantity_is_exact_for_huge_values_under_any_context():
    big = "1" + "0" * 40 + ".001"
    with localcontext() as ctx:
        ctx.prec = 5
        q = Quantity(value=big, unit=Unit.KG)
        assert str((q + q).value) == "2" + "0" * 40 + ".002"


# --- Review fixes: unit helpers are context-free and finite-only -----------


@pytest.mark.parametrize("bad", [Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")])
def test_unit_helpers_reject_non_finite(bad):
    for fn in (quantize_required, quantize_available):
        with pytest.raises(ValueError):
            fn(bad)
    one = Decimal(1)
    with pytest.raises(ValueError):
        kg_to_m(bad, one, one)
    with pytest.raises(ValueError):
        kg_to_m(one, bad, one)
    with pytest.raises(ValueError):
        kg_to_m(one, one, bad)


def test_unit_helpers_ignore_the_ambient_context():
    big = Decimal("1" + "0" * 40 + ".0005")
    expected = Decimal(100_000) / Decimal(270)
    with localcontext() as ctx:
        ctx.prec = 5
        assert quantize_required(big) == Decimal("1" + "0" * 40 + ".001")
        assert quantize_available(big) == Decimal("1" + "0" * 40 + ".000")
        assert kg_to_m(Decimal("100"), Decimal("180"), Decimal("1.5")) == expected
        ctx.traps[Inexact] = True
        assert kg_to_m(Decimal("100"), Decimal("180"), Decimal("1.5")) == expected
    assert quantize_available(Decimal(10**40)) == Decimal(10**40)


# --- Review fixes: immutable, hashable facts -------------------------------


def test_fact_payload_is_deeply_immutable():
    fact = _fact(payload={"a": {"b": [1, 2]}, "c": 1})
    before = decision_digest(fact)
    with pytest.raises(TypeError):
        fact.payload["c"] = 2
    with pytest.raises(TypeError):
        fact.payload["a"]["b"] = 1
    with pytest.raises(TypeError):
        fact.payload.update({"z": 1})
    with pytest.raises(TypeError):
        del fact.payload["c"]
    assert isinstance(fact.payload["a"]["b"], tuple)
    assert decision_digest(fact) == before


def test_fact_is_hashable_and_equal_facts_hash_equal():
    a = _fact(payload={"a": [1, {"b": "c"}]})
    b = _fact(payload={"a": [1, {"b": "c"}]})
    assert a == b
    assert hash(a) == hash(b)
    assert len({a, b}) == 1


# --- Review fixes: golden vector -------------------------------------------


def test_decision_digest_golden_vector():
    value = {
        "qty": Decimal("1.500"),
        "when": datetime(2026, 3, 1, 15, 30, tzinfo=timezone(timedelta(hours=5, minutes=30))),
        "note": unicodedata.normalize("NFD", "கொடு"),
        "slots": ["b", "a", [Decimal("-0"), 2]],
    }
    expected_json = (
        '{"note":"கொடு","qty":"1.5","slots":["b","a",["0",2]],"when":"2026-03-01T10:00:00Z"}'
    )
    assert canonical(value) == json.loads(expected_json)
    # sha256 over the canonical JSON *string literal* passed through hashing.digest.
    assert decision_digest(value) == digest(expected_json)
    assert (
        decision_digest(value)
        == "sha256:ca866e332cd896d349f1e530cecb181f64a8a19f89aace95f4152743c375d73d"
    )
