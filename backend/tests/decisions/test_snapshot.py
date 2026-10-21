"""As-known snapshots: visibility, corrections, observation ties, purity of inputs."""

from __future__ import annotations

import contextlib
import random
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from decisions.strategies import (
    chain_histories,
    fact_histories,
    facts,
    instants,
    tied_lot_histories,
)
from flooreplay.decisions.facts import (
    EVENT_KINDS,
    NON_SEMANTIC_FIELDS,
    CorrectionError,
    CorrectionErrorCode,
    FactValidationError,
    semantic_digest,
    validate_corrections,
    validate_fact,
)
from flooreplay.decisions.snapshot import (
    COMPETING_REPLACEMENT,
    INVALID_PAYLOAD,
    CurrentStatus,
    NotAnObservation,
    current,
    events,
    snapshot_at,
    visible,
)
from flooreplay.decisions.types import Fact, FactKind, SourceProfile

T0 = datetime(2026, 3, 1, 8, 0, tzinfo=UTC)
CUTOFF = T0 + timedelta(days=5)


def lot_payload(kg: str = "100", **extra: Any) -> dict[str, Any]:
    return {
        "fabric_quality": "SJ180",
        "colour": "NAVY",
        "qty": {"value": kg, "unit": "kg"},
        **extra,
    }


def lot(
    fid: str,
    *,
    valid_from: datetime = T0,
    known_at: datetime | None = None,
    kg: str = "100",
    supersedes_id: str | None = None,
    key: str = "lot:L1",
    **extra: Any,
) -> Fact:
    return Fact(
        id=fid,
        kind=FactKind.FABRIC_LOT,
        entity_key=key,
        payload=lot_payload(kg, **extra),
        valid_from=valid_from,
        valid_to=None,
        known_at=known_at or valid_from + timedelta(hours=1),
        supersedes_id=supersedes_id,
        source=SourceProfile.ERP_FABRIC_STOCK,
        artifact_id=None,
    )


def ids(snapshot_facts: Any) -> list[str]:
    return [f.id for f in snapshot_facts]


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------


@settings(deadline=None)
@given(fact_histories(), instants())
def test_cutoff_no_fact_known_after_cutoff(history: list[Fact], cutoff: datetime) -> None:
    snap = snapshot_at(history, cutoff)
    assert all(f.known_at <= cutoff for f in snap.facts)
    assert snap.cutoff == cutoff


@settings(deadline=None)
@given(fact_histories(), instants(), st.randoms(use_true_random=False))
def test_shuffle_does_not_change_digest(
    history: list[Fact], cutoff: datetime, rnd: random.Random
) -> None:
    shuffled = list(history)
    rnd.shuffle(shuffled)
    a, b = snapshot_at(history, cutoff), snapshot_at(shuffled, cutoff)
    assert a.digest == b.digest
    assert a == b


@settings(deadline=None)
@given(fact_histories())
def test_generated_facts_are_schema_valid(history: list[Fact]) -> None:
    for fact in history:
        assert validate_fact(fact).payload  # parses and normalises
    validate_corrections(history)


@settings(deadline=None)
@given(st.one_of(fact_histories(), chain_histories()))
def test_corrections_never_overwrite(history: list[Fact]) -> None:
    before = [f.model_copy(deep=True) for f in history]
    by_id = {f.id: f for f in history}
    for correction in (f for f in history if f.supersedes_id):
        target = by_id[correction.supersedes_id or ""]
        cutoff = correction.known_at - timedelta(microseconds=1)
        snap = snapshot_at(history, cutoff)
        # The original is still on record and, just before the correction, visible,
        # unless an even earlier replacement already hid it.
        hidden = any(f.supersedes_id == target.id and f.known_at <= cutoff for f in history)
        assert (target.id in ids(snap.facts)) is not hidden
        assert correction.id not in ids(snap.facts)
        after = snapshot_at(history, correction.known_at)
        assert target.id not in ids(after.facts)
        # Nothing can supersede the correction at its own known_at (strictly later only).
        assert correction.id in ids(after.facts)
    assert history == before  # the input is never mutated


@settings(deadline=None)
@given(facts(FactKind.FABRIC_LOT), st.integers(2, 4))
def test_competing_replacements_yield_a_finding(original: Fact, n: int) -> None:
    original = original.model_copy(update={"id": "orig", "supersedes_id": None})
    replacements = [
        original.model_copy(
            update={
                "id": f"r{i}",
                "supersedes_id": "orig",
                "known_at": original.known_at + timedelta(hours=1 + i),
            }
        )
        for i in range(n)
    ]
    history = [original, *replacements]
    cutoff = replacements[-1].known_at
    snap = snapshot_at(history, cutoff)
    findings = [f for f in snap.findings if f.code == "competing_replacement"]
    assert len(findings) == 1
    assert findings[0].subject_id == "orig"
    assert (findings[0].kind, findings[0].entity_key) == (original.kind, original.entity_key)
    assert findings[0].fact_ids == tuple(sorted(f.id for f in replacements))
    assert "orig" not in ids(snap.facts)  # superseded, and neither replacement wins silently
    assert sorted(ids(snap.facts)) == sorted(f.id for f in replacements)

    # Before the second replacement arrives there is only one: no finding.
    early = snapshot_at(history, replacements[0].known_at)
    assert early.findings == ()


@settings(deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(fact_histories(), instants())
def test_invalid_later_fact_cannot_break_an_earlier_replay(
    history: list[Fact], cutoff: datetime
) -> None:
    baseline = snapshot_at(history, cutoff)
    bad = lot("bad", known_at=cutoff + timedelta(minutes=1), supersedes_id="does-not-exist")
    extended = [*history, bad]
    assert snapshot_at(extended, cutoff) == baseline
    assert snapshot_at(extended, cutoff).digest == baseline.digest
    with pytest.raises(CorrectionError) as err:
        validate_corrections(extended)
    assert err.value.code == CorrectionErrorCode.UNKNOWN_TARGET
    # ...but once the bad fact is visible, the replay does fail loudly.
    with pytest.raises(CorrectionError):
        snapshot_at(extended, bad.known_at)


# ---------------------------------------------------------------------------
# validate_corrections
# ---------------------------------------------------------------------------


def codes(history: list[Fact]) -> CorrectionErrorCode:
    with pytest.raises(CorrectionError) as err:
        validate_corrections(history)
    assert isinstance(err.value, ValueError)
    return err.value.code


def test_corrections_valid_chain_passes() -> None:
    a = lot("a")
    b = lot("b", known_at=a.known_at + timedelta(hours=1), supersedes_id="a")
    c = lot("c", known_at=b.known_at + timedelta(hours=1), supersedes_id="b")
    validate_corrections([c, a, b])


def test_duplicate_ids() -> None:
    assert codes([lot("a"), lot("a")]) == CorrectionErrorCode.DUPLICATE_ID


def test_unknown_target() -> None:
    assert codes([lot("a", supersedes_id="nope")]) == CorrectionErrorCode.UNKNOWN_TARGET


def test_cycle() -> None:
    a = lot("a", supersedes_id="b")
    b = lot("b", supersedes_id="a")
    assert codes([a, b]) == CorrectionErrorCode.CYCLE


def test_kind_must_match_target() -> None:
    target = lot("a")
    other = lot("b", known_at=target.known_at + timedelta(hours=1), supersedes_id="a").model_copy(
        update={"kind": FactKind.FABRIC_QC}
    )
    assert codes([target, other]) == CorrectionErrorCode.KIND_MISMATCH


def test_entity_key_must_match_target() -> None:
    target = lot("a")
    other = lot("b", known_at=target.known_at + timedelta(hours=1), supersedes_id="a", key="lot:L2")
    assert codes([target, other]) == CorrectionErrorCode.ENTITY_MISMATCH


def test_correction_must_be_known_strictly_after_target() -> None:
    target = lot("a")
    same = lot("b", known_at=target.known_at, supersedes_id="a")
    assert codes([target, same]) == CorrectionErrorCode.NOT_AFTER_TARGET
    earlier = lot("c", known_at=target.known_at - timedelta(minutes=1), supersedes_id="a")
    assert codes([target, earlier]) == CorrectionErrorCode.NOT_AFTER_TARGET


# ---------------------------------------------------------------------------
# validate_fact and semantic_digest
# ---------------------------------------------------------------------------


def test_validate_fact_normalises_and_is_idempotent() -> None:
    fact = lot("a", kg="100.0")
    checked = validate_fact(fact)
    assert checked.payload["qty"] == {"value": "100", "unit": "kg"}
    assert validate_fact(checked) == checked


@pytest.mark.parametrize(
    "key",
    ["lot:", "lots:L1", "L1", "lot:L1:extra", "order:O1", "lot: L1"],
)
def test_validate_fact_rejects_a_malformed_entity_key(key: str) -> None:
    with pytest.raises(FactValidationError) as err:
        validate_fact(lot("a", key=key))
    assert err.value.code == "bad_entity_key"


def test_validate_fact_rejects_a_bad_payload() -> None:
    for payload in (
        {},  # missing fields
        {**lot_payload(), "qty": {"value": "1", "unit": "pcs"}},  # wrong unit for fabric
        {**lot_payload(), "qty": {"value": 1.5, "unit": "kg"}},  # float
        {**lot_payload(), "surprise": 1},  # unknown field
    ):
        with pytest.raises(FactValidationError) as err:
            validate_fact(lot("a").model_copy(update={"payload": payload}))
        assert err.value.code == "bad_payload"


def test_every_kind_has_a_registry_entry() -> None:
    from flooreplay.decisions.facts import KIND_REGISTRY

    assert set(KIND_REGISTRY) == set(FactKind)


@settings(deadline=None)
@given(facts())
def test_generated_facts_have_a_stable_semantic_digest(fact: Fact) -> None:
    assert semantic_digest(fact) == semantic_digest(validate_fact(fact))


def test_semantic_digest_ignores_non_semantic_fields() -> None:
    assert frozenset({"row_number", "raw_text", "raw"}) == NON_SEMANTIC_FIELDS
    a = lot("a", row_number=3, raw_text="NAVY 100kg")
    b = lot("b", row_number=9, raw="row 9")
    c = lot("c", kg="100.000")
    assert semantic_digest(a) == semantic_digest(b) == semantic_digest(c)
    assert semantic_digest(a) != semantic_digest(lot("d", kg="101"))


# ---------------------------------------------------------------------------
# Observation semantics
# ---------------------------------------------------------------------------


def test_visible_hides_future_and_superseded_facts() -> None:
    a = lot("a")
    b = lot("b", known_at=a.known_at + timedelta(hours=2), supersedes_id="a")
    late = lot("late", known_at=CUTOFF + timedelta(hours=1))
    assert ids(visible([a, b, late], CUTOFF)) == ["b"]
    assert ids(visible([a, b, late], a.known_at)) == ["a"]
    assert visible([a, b, late], a.known_at - timedelta(seconds=1)) == []


def test_latest_valid_from_wins() -> None:
    old = lot("old", valid_from=T0, kg="100")
    new = lot("new", valid_from=T0 + timedelta(days=1), kg="40")
    snap = snapshot_at([new, old], CUTOFF)
    result = current(snap, FactKind.FABRIC_LOT, "lot:L1")
    assert result.status is CurrentStatus.FOUND
    assert result.fact is not None and result.fact.id == "new"


def test_same_valid_from_different_payload_is_a_tie_conflict() -> None:
    erp = lot("erp", kg="4000")
    other = lot("other", kg="1200")
    snap = snapshot_at([erp, other], CUTOFF)
    result = current(snap, FactKind.FABRIC_LOT, "lot:L1")
    assert result.status is CurrentStatus.TIE_CONFLICT
    assert result.fact is None
    assert sorted(ids(result.facts)) == ["erp", "other"]


def test_same_valid_from_row_number_only_difference_is_not_a_conflict() -> None:
    first = lot("first", row_number=2, raw_text="a")
    second = lot(
        "second", row_number=17, raw_text="b", known_at=first.known_at + timedelta(hours=1)
    )
    snap = snapshot_at([first, second], CUTOFF)
    result = current(snap, FactKind.FABRIC_LOT, "lot:L1")
    assert result.status is CurrentStatus.FOUND
    assert result.fact is not None and result.fact.id == "second"  # latest known_at, deterministic
    assert sorted(ids(result.facts)) == ["first", "second"]


def test_a_correction_resolves_a_tie_conflict() -> None:
    erp = lot("erp", kg="4000")
    other = lot("other", kg="1200")
    fix = lot("fix", kg="1200", known_at=other.known_at + timedelta(hours=1), supersedes_id="erp")
    before = snapshot_at([erp, other, fix], other.known_at)
    assert current(before, FactKind.FABRIC_LOT, "lot:L1").status is CurrentStatus.TIE_CONFLICT
    after = snapshot_at([erp, other, fix], fix.known_at)
    result = current(after, FactKind.FABRIC_LOT, "lot:L1")
    assert result.status is CurrentStatus.FOUND  # same payload as `other`


def test_missing_entity_is_unknown_never_zero() -> None:
    snap = snapshot_at([lot("a")], CUTOFF)
    for kind, key in ((FactKind.FABRIC_LOT, "lot:L9"), (FactKind.FABRIC_INBOUND, "inbound:I1")):
        result = current(snap, kind, key)
        assert result.status is CurrentStatus.UNKNOWN
        assert result.fact is None and result.facts == ()
    # Not yet known at an earlier cutoff is UNKNOWN too.
    early = snapshot_at([lot("a")], T0)
    assert current(early, FactKind.FABRIC_LOT, "lot:L1").status is CurrentStatus.UNKNOWN


def test_snapshot_facts_are_sorted_and_digest_tracks_content() -> None:
    a = lot("a", key="lot:L2")
    b = lot("b", key="lot:L1", valid_from=T0 + timedelta(days=1))
    c = lot("c", key="lot:L1")
    snap = snapshot_at([a, b, c], CUTOFF)
    assert ids(snap.facts) == ["c", "b", "a"]
    assert snapshot_at([a, b], CUTOFF).digest != snap.digest
    assert snapshot_at([a, b, c], CUTOFF + timedelta(days=1)).digest != snap.digest


def test_naive_cutoff_is_rejected() -> None:
    with pytest.raises((ValueError, TypeError)):
        snapshot_at([lot("a")], datetime(2026, 3, 1))  # noqa: DTZ001


@settings(deadline=None)
@given(facts())
def test_generated_facts_are_never_backdated(fact: Fact) -> None:
    assert fact.valid_from <= fact.known_at


@settings(deadline=None)
@given(facts(future_dated=True))
def test_future_dated_facts_are_available_for_negative_tests(fact: Fact) -> None:
    assert fact.known_at < fact.valid_from


@settings(deadline=None)
@given(fact_histories(), instants())
def test_forked_histories_with_known_at_ties_are_deterministic(
    history: list[Fact], cutoff: datetime
) -> None:
    # Force a known_at tie across the whole history; supersession (strictly later)
    # is dropped, so only ties and forks remain. Order must not matter.
    tied = [
        f.model_copy(
            update={
                "known_at": history[0].known_at,
                "valid_from": history[0].known_at - timedelta(minutes=1),
                "valid_to": None,
                "supersedes_id": None,
            }
        )
        for f in history
    ]
    forward = snapshot_at(tied, history[0].known_at)
    backward = snapshot_at(list(reversed(tied)), history[0].known_at)
    assert forward == backward
    for f in forward.facts:
        if f.kind in EVENT_KINDS:
            assert events(forward, f.kind, f.entity_key) == events(backward, f.kind, f.entity_key)
            continue
        r = current(forward, f.kind, f.entity_key)
        assert r == current(backward, f.kind, f.entity_key)


# ---------------------------------------------------------------------------
# Review fixes: competing replacements are surfaced by current()
# ---------------------------------------------------------------------------


def test_current_surfaces_competing_replacements() -> None:
    a = lot("A", valid_from=T0, kg="100")
    r1 = lot(
        "R1", valid_from=T0, kg="10", known_at=a.known_at + timedelta(hours=1), supersedes_id="A"
    )
    r2 = lot(
        "R2", valid_from=T0, kg="900", known_at=a.known_at + timedelta(hours=2), supersedes_id="A"
    )
    snap = snapshot_at([a, r1, r2], CUTOFF)
    result = current(snap, FactKind.FABRIC_LOT, "lot:L1")
    assert result.status is CurrentStatus.COMPETING
    assert result.fact is None
    assert sorted(ids(result.facts)) == ["R1", "R2"]


def test_competing_replacements_are_not_resolved_by_a_newer_observation() -> None:
    a = lot("A", valid_from=T0)
    r1 = lot(
        "R1", valid_from=T0, kg="10", known_at=a.known_at + timedelta(hours=1), supersedes_id="A"
    )
    r2 = lot(
        "R2", valid_from=T0, kg="900", known_at=a.known_at + timedelta(hours=2), supersedes_id="A"
    )
    newer = lot("N", valid_from=T0 + timedelta(days=1), kg="5")
    result = current(snapshot_at([a, r1, r2, newer], CUTOFF), FactKind.FABRIC_LOT, "lot:L1")
    assert result.status is CurrentStatus.COMPETING
    assert sorted(ids(result.facts)) == ["R1", "R2"]


def test_replacements_with_different_valid_from_are_not_even_a_valid_graph() -> None:
    # Competitors cannot differ in valid_from: a correction keeps its target's valid time.
    a = lot("A", valid_from=T0)
    r1 = lot(
        "R1",
        valid_from=T0 + timedelta(days=1),
        kg="10",
        known_at=a.known_at + timedelta(days=2),
        supersedes_id="A",
    )
    with pytest.raises(CorrectionError) as err:
        snapshot_at([a, r1], CUTOFF)
    assert err.value.code == CorrectionErrorCode.INTERVAL_MISMATCH


def test_competing_branches_report_their_tips() -> None:
    a = lot("A")
    b = lot("B", known_at=a.known_at + timedelta(hours=1), supersedes_id="A")
    c = lot("C", known_at=b.known_at + timedelta(hours=1), supersedes_id="B")
    x = lot("X", kg="7", known_at=a.known_at + timedelta(hours=1, minutes=30), supersedes_id="A")
    snap = snapshot_at([a, b, c, x], CUTOFF)
    (finding,) = snap.findings
    assert finding.code == COMPETING_REPLACEMENT and finding.subject_id == "A"
    assert finding.fact_ids == ("C", "X")  # the visible tips of the two branches
    assert current(snap, FactKind.FABRIC_LOT, "lot:L1").status is CurrentStatus.COMPETING


def test_chain_at_every_cutoff() -> None:
    a = lot("A", kg="100")
    b = lot("B", kg="200", known_at=a.known_at + timedelta(hours=1), supersedes_id="A")
    c = lot("C", kg="300", known_at=b.known_at + timedelta(hours=1), supersedes_id="B")
    history = [c, a, b]
    for cutoff, expected in ((a.known_at, "A"), (b.known_at, "B"), (c.known_at, "C")):
        snap = snapshot_at(history, cutoff)
        assert ids(snap.facts) == [expected] and snap.findings == ()
        result = current(snap, FactKind.FABRIC_LOT, "lot:L1")
        assert result.fact is not None and result.fact.id == expected


@settings(deadline=None)
@given(chain_histories(), instants())
def test_deep_chain_histories_are_stable_under_cutoff_and_shuffle(
    history: list[Fact], cutoff: datetime
) -> None:
    cutoff = max(history[0].known_at, cutoff)
    snap = snapshot_at(history, cutoff)
    assert snapshot_at(list(reversed(history)), cutoff) == snap
    # Every visible tip is unsuperseded; hidden ancestors never reappear.
    superseded = {f.supersedes_id for f in history if f.known_at <= cutoff}
    assert not (set(ids(snap.facts)) & superseded)
    result = current(snap, FactKind.FABRIC_LOT, "lot:L1")
    competing = {i for f in snap.findings for i in f.fact_ids}
    if set(ids(snap.facts)) & competing:
        assert result.status is CurrentStatus.COMPETING
    else:
        assert result.status is CurrentStatus.FOUND


@settings(deadline=None)
@given(tied_lot_histories(), st.randoms(use_true_random=False))
def test_current_matches_an_independent_oracle_on_tied_valid_from(
    history: list[Fact], rnd: random.Random
) -> None:
    for cutoff in sorted({f.known_at for f in history}):
        snap = snapshot_at(history, cutoff)
        shuffled = list(history)
        rnd.shuffle(shuffled)
        other = snapshot_at(shuffled, cutoff)
        assert other.digest == snap.digest
        competing = {i for f in snap.findings for i in f.fact_ids}
        for key in ("lot:L1", "lot:L2"):
            result = current(snap, FactKind.FABRIC_LOT, key)
            assert result == current(other, FactKind.FABRIC_LOT, key)
            mine = [f for f in snap.facts if f.entity_key == key]
            if not mine:
                assert result.status is CurrentStatus.UNKNOWN
            elif any(f.id in competing for f in mine):
                assert result.status is CurrentStatus.COMPETING
            else:
                newest = max(f.valid_from for f in mine)
                top = [f for f in mine if f.valid_from == newest]
                same = len({str(f.payload["qty"]) for f in top}) == 1
                assert (result.status is CurrentStatus.FOUND) == same
                assert (result.status is CurrentStatus.TIE_CONFLICT) == (not same)
                assert {f.id for f in result.facts} == {f.id for f in top}


# ---------------------------------------------------------------------------
# Review fixes: digest covers all fact fields
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", "renamed"),
        ("kind", FactKind.FABRIC_ALLOCATION),
        ("entity_key", "lot:L2"),
        ("valid_from", T0 - timedelta(hours=1)),
        ("valid_to", T0 + timedelta(days=3)),
        ("known_at", T0 + timedelta(hours=2)),
        ("supersedes_id", "base"),
        ("source", SourceProfile.NOTES),
        ("artifact_id", "A9"),
    ],
)
def test_snapshot_digest_changes_with_every_fact_field(field: str, value: Any) -> None:
    base = lot("base", valid_from=T0, known_at=T0 + timedelta(minutes=30))
    fact = lot("f")
    changed = fact.model_copy(update={field: value})
    assert changed != fact
    original = snapshot_at([base, fact], CUTOFF)
    assert snapshot_at([base, changed], CUTOFF).digest != original.digest


def test_snapshot_digest_changes_with_the_payload() -> None:
    base = lot("f", kg="100")
    assert snapshot_at([base], CUTOFF).digest != snapshot_at([lot("f", kg="101")], CUTOFF).digest


# ---------------------------------------------------------------------------
# Review fixes: corrections keep the target's valid time
# ---------------------------------------------------------------------------


def test_correction_must_keep_the_targets_valid_time() -> None:
    target = lot("a", valid_from=T0)
    later = lot(
        "b", valid_from=T0 + timedelta(hours=1), known_at=T0 + timedelta(hours=5), supersedes_id="a"
    )
    assert codes([target, later]) == CorrectionErrorCode.INTERVAL_MISMATCH
    ended = lot("c", valid_from=T0, known_at=T0 + timedelta(hours=5), supersedes_id="a").model_copy(
        update={"valid_to": T0 + timedelta(days=1)}
    )
    assert codes([target, ended]) == CorrectionErrorCode.INTERVAL_MISMATCH


# ---------------------------------------------------------------------------
# Review fixes: events versus observations
# ---------------------------------------------------------------------------


def qc(fid: str, kg: str, known_at: datetime, key: str = "lot:L1") -> Fact:
    return Fact(
        id=fid,
        kind=FactKind.FABRIC_QC,
        entity_key=key,
        payload={
            "issue": "shade_fail",
            "qty": {"value": kg, "unit": "kg"},
            "review_state": "checks_passed",
            "origin": "notes",
        },
        valid_from=T0,
        valid_to=None,
        known_at=known_at,
        supersedes_id=None,
        source=SourceProfile.NOTES,
        artifact_id=None,
    )


def test_event_kinds_are_fabric_qc_and_resolution() -> None:
    assert frozenset({FactKind.FABRIC_QC, FactKind.RESOLUTION}) == EVENT_KINDS


def test_current_refuses_event_kinds_and_events_returns_all() -> None:
    q1 = qc("q1", "5", T0 + timedelta(hours=1))
    q2 = qc("q2", "7", T0 + timedelta(hours=2))
    q3 = qc("q3", "9", T0 + timedelta(hours=3), key="lot:L2")
    snap = snapshot_at([q2, lot("a"), q3, q1], CUTOFF)
    for kind in EVENT_KINDS:
        with pytest.raises(NotAnObservation):
            current(snap, kind, "lot:L1")
    assert ids(events(snap, FactKind.FABRIC_QC, "lot:L1")) == ["q1", "q2"]
    assert events(snap, FactKind.FABRIC_QC, "lot:L9") == []
    # A superseded event is hidden like any other fact.
    fix = qc("q1b", "6", T0 + timedelta(hours=4)).model_copy(update={"supersedes_id": "q1"})
    assert ids(events(snapshot_at([q1, q2, fix], CUTOFF), FactKind.FABRIC_QC, "lot:L1")) == [
        "q2",
        "q1b",
    ]  # ordered by valid_from, then known_at


# ---------------------------------------------------------------------------
# Review fixes: validate_fact
# ---------------------------------------------------------------------------


def test_validate_fact_emits_canonical_decimal_text_everywhere() -> None:
    fact = lot("a", kg="1200.500", gsm="180.0", width_m="1.50")
    out = validate_fact(fact).payload
    assert out["qty"] == {"value": "1200.5", "unit": "kg"}
    assert (out["gsm"], out["width_m"]) == ("180", "1.5")
    order = Fact(
        id="o",
        kind=FactKind.ORDER_REQUEST,
        entity_key="order:O1",
        payload={
            "buyer": "B",
            "style_id": "S1",
            "colours": [{"colour": "NAVY", "qty_pcs": 10}],
            "ship_date": "2026-04-01",
            "order_value_inr": "100.00",
            "partial_shipment_allowed": False,
        },
        valid_from=T0,
        valid_to=None,
        known_at=T0,
        supersedes_id=None,
        source=SourceProfile.ORDER_REQUESTS,
        artifact_id=None,
    )
    assert validate_fact(order).payload["order_value_inr"] == "100"


@pytest.mark.parametrize("gsm", ["1" * 31, "0." + "1" * 3 + "0" * 40, "1E+40", "1E-40"])
def test_validate_fact_bounds_digits_and_exponents(gsm: str) -> None:
    with pytest.raises(FactValidationError) as err:
        validate_fact(lot("a", gsm=gsm))
    assert err.value.code == "bad_payload"


@pytest.mark.parametrize("qty", ["1" * 31, "1E+40"])
def test_validate_fact_bounds_quantity_digits(qty: str) -> None:
    with pytest.raises(FactValidationError) as err:
        validate_fact(lot("a", kg=qty))
    assert err.value.code == "bad_payload"


@pytest.mark.parametrize(
    "payload",
    [
        lot_payload(kg="-1"),
        {**lot_payload(), "gsm": "-3"},
    ],
)
def test_validate_fact_rejects_negative_numbers(payload: dict[str, Any]) -> None:
    with pytest.raises(FactValidationError):
        validate_fact(lot("a").model_copy(update={"payload": payload}))


def other_fact(kind: FactKind, key: str, payload: dict[str, Any], src: SourceProfile) -> Fact:
    return Fact(
        id="x",
        kind=kind,
        entity_key=key,
        payload=payload,
        valid_from=T0,
        valid_to=None,
        known_at=T0,
        supersedes_id=None,
        source=src,
        artifact_id=None,
    )


def trim(**over: Any) -> Fact:
    payload = {"on_hand": {"value": "5", "unit": "pcs"}, "supplier": "S", **over}
    return other_fact(
        FactKind.TRIM_STATUS, "trim:S1:ZIP", payload, SourceProfile.SHEET_TRIMS_STATUS
    )


def cap(**over: Any) -> Fact:
    payload = {"available_minutes": {"value": "480", "unit": "minutes"}, **over}
    return other_fact(
        FactKind.LINE_CAPACITY, "line:LINE-1:2026-03-02", payload, SourceProfile.SHIFT_CAPACITY
    )


def commitment(**over: Any) -> Fact:
    payload = {"committed_minutes": {"value": "60", "unit": "minutes"}, **over}
    return other_fact(
        FactKind.LINE_COMMITMENT,
        "commit:O1:LINE-1:2026-03-02",
        payload,
        SourceProfile.SHIFT_CAPACITY,
    )


def order(colours: list[dict[str, Any]] | None = None, **over: Any) -> Fact:
    payload = {
        "buyer": "B",
        "style_id": "S1",
        "colours": colours or [{"colour": "NAVY", "qty_pcs": 10}],
        "ship_date": "2026-04-01",
        "order_value_inr": "1000",
        "partial_shipment_allowed": True,
        **over,
    }
    return other_fact(FactKind.ORDER_REQUEST, "order:O1", payload, SourceProfile.ORDER_REQUESTS)


def bom(trims: list[dict[str, Any]] | None = None, **over: Any) -> Fact:
    payload = {
        "fabric_quality": "SJ180",
        "consumption_per_pc": {"value": "0.3", "unit": "kg"},
        "trims": trims if trims is not None else [{"trim_id": "ZIP", "qty_per_pc": "1"}],
        "sam_minutes": "12",
        **over,
    }
    return other_fact(FactKind.BOM, "bom:S1", payload, SourceProfile.ORDER_REQUESTS)


@pytest.mark.parametrize(
    "fact",
    [
        trim(on_hand={"value": "-1", "unit": "pcs"}),
        trim(inbound_qty={"value": "-1", "unit": "pcs"}),
        cap(available_minutes={"value": "-1", "unit": "minutes"}),
        commitment(committed_minutes={"value": "-1", "unit": "minutes"}),
        order(order_value_inr="-1"),
        order(colours=[{"colour": "NAVY", "qty_pcs": -1}]),
        order(colours=[{"colour": "NAVY", "qty_pcs": 0}]),  # qty_pcs must be > 0
        bom(trims=[{"trim_id": "ZIP", "qty_per_pc": "-1"}]),
        order(buyer=""),
        order(style_id=""),
        order(colours=[{"colour": "", "qty_pcs": 1}]),
        bom(fabric_quality=""),
        bom(trims=[{"trim_id": "", "qty_per_pc": "1"}]),
        trim(supplier=""),
    ],
)
def test_validate_fact_rejects_negative_and_empty_values(fact: Fact) -> None:
    with pytest.raises(FactValidationError) as err:
        validate_fact(fact)
    assert err.value.code == "bad_payload"


def test_zero_is_allowed_except_for_order_pieces() -> None:
    validate_fact(trim(on_hand={"value": "0", "unit": "pcs"}))
    validate_fact(cap(available_minutes={"value": "0", "unit": "minutes"}))
    validate_fact(commitment(committed_minutes={"value": "0", "unit": "minutes"}))
    validate_fact(order(order_value_inr="0"))
    validate_fact(lot("a", kg="0"))


def test_duplicate_colours_and_trims_are_rejected() -> None:
    dup_colour = order(colours=[{"colour": "NAVY", "qty_pcs": 1}, {"colour": "NAVY", "qty_pcs": 2}])
    dup_trim = bom(
        trims=[{"trim_id": "ZIP", "qty_per_pc": "1"}, {"trim_id": "ZIP", "qty_per_pc": "2"}]
    )
    for fact in (dup_colour, dup_trim):
        with pytest.raises(FactValidationError) as err:
            validate_fact(fact)
        assert err.value.code == "duplicate_item"
    # Distinct items, in any order, are fine and normalise to one form.
    a = bom(trims=[{"trim_id": "ZIP", "qty_per_pc": "1"}, {"trim_id": "LABEL", "qty_per_pc": "2"}])
    b = bom(trims=[{"trim_id": "LABEL", "qty_per_pc": "2"}, {"trim_id": "ZIP", "qty_per_pc": "1"}])
    assert semantic_digest(a) == semantic_digest(b)


@pytest.mark.parametrize(
    ("kind", "key"),
    [
        (FactKind.FABRIC_LOT, "lot:L\u00e9"),  # non-ASCII
        (FactKind.FABRIC_LOT, "lot:L\uff11"),  # full-width digit
        (FactKind.FABRIC_LOT, "lot:L1\n"),
        (FactKind.FABRIC_LOT, "lot:"),
        (FactKind.LINE_CAPACITY, "line:LINE-1:2026-02-31"),  # impossible date
        (FactKind.LINE_CAPACITY, "line:LINE-1:2026-13-01"),
        (FactKind.LINE_CAPACITY, "line:LINE-1:\u0662\u0660\u0662\u0666-03-02"),  # Arabic digits
        (FactKind.LINE_CAPACITY, "line:LINE-1:2026-3-2"),
    ],
)
def test_entity_keys_are_ascii_and_real_dates(kind: FactKind, key: str) -> None:
    payload = cap().payload if kind is FactKind.LINE_CAPACITY else lot_payload()
    fact = other_fact(kind, key, payload, SourceProfile.SHIFT_CAPACITY)
    with pytest.raises(FactValidationError) as err:
        validate_fact(fact)
    assert err.value.code == "bad_entity_key"


def test_valid_date_keys_and_leap_day_pass() -> None:
    for day in ("2026-03-02", "2028-02-29"):
        validate_fact(
            other_fact(
                FactKind.LINE_CAPACITY,
                f"line:LINE-1:{day}",
                cap().payload,
                SourceProfile.SHIFT_CAPACITY,
            )
        )
    with pytest.raises(FactValidationError):
        validate_fact(
            other_fact(
                FactKind.LINE_CAPACITY,
                "line:LINE-1:2027-02-29",
                cap().payload,
                SourceProfile.SHIFT_CAPACITY,
            )
        )


def test_validate_fact_rejects_backdated_facts() -> None:
    backdated = lot("a", valid_from=T0, known_at=T0 - timedelta(minutes=1))
    with pytest.raises(FactValidationError) as err:
        validate_fact(backdated)
    assert err.value.code == "backdated"
    validate_fact(lot("b", valid_from=T0, known_at=T0))  # equal is allowed


@settings(deadline=None)
@given(facts(future_dated=True))
def test_future_dated_generated_facts_fail_validation(fact: Fact) -> None:
    with pytest.raises(FactValidationError) as err:
        validate_fact(fact)
    assert err.value.code == "backdated"


@settings(deadline=None)
@given(st.text(max_size=12))
def test_validate_fact_only_ever_raises_fact_validation_error(text: str) -> None:
    for payload in (
        {**lot_payload(), "gsm": text},
        {**lot_payload(), "colour": text},
        {**lot_payload(), "qty": {"value": text, "unit": "kg"}},
    ):
        with contextlib.suppress(FactValidationError):
            validate_fact(lot("a").model_copy(update={"payload": payload}))


# ---------------------------------------------------------------------------
# Review fixes: invalid visible facts do not break snapshots
# ---------------------------------------------------------------------------


def test_invalid_visible_payload_is_excluded_with_a_finding() -> None:
    good = lot("good", key="lot:L2")
    bad = lot("bad").model_copy(update={"payload": {"surprise": 1}})
    snap = snapshot_at([good, bad], CUTOFF)
    assert ids(snap.facts) == ["good"]
    (finding,) = snap.findings
    assert finding.code == INVALID_PAYLOAD
    assert (finding.kind, finding.entity_key) == (FactKind.FABRIC_LOT, "lot:L1")
    assert finding.fact_ids == ("bad",) and finding.detail == "bad_payload"
    assert current(snap, FactKind.FABRIC_LOT, "lot:L1").status is CurrentStatus.UNKNOWN
    assert snapshot_at([bad, good], CUTOFF) == snap
    assert snapshot_at([good], CUTOFF).digest != snap.digest


@pytest.mark.parametrize(
    ("update", "detail"),
    [
        ({"entity_key": "lot:L 1"}, "bad_entity_key"),
        ({"known_at": T0 - timedelta(hours=1)}, "backdated"),
        (
            {"payload": {**lot_payload(), "qty": {"value": "-1", "unit": "kg"}}},
            "bad_payload",
        ),
    ],
)
def test_other_invalid_visible_facts_become_invalid_payload_findings(
    update: dict[str, Any], detail: str
) -> None:
    bad = lot("bad").model_copy(update=update)
    snap = snapshot_at([bad], CUTOFF)
    assert snap.facts == ()
    assert [(f.code, f.detail) for f in snap.findings] == [(INVALID_PAYLOAD, detail)]


def test_graph_errors_among_visible_facts_still_raise() -> None:
    with pytest.raises(CorrectionError):
        snapshot_at([lot("a", supersedes_id="ghost")], CUTOFF)


@settings(deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    fact_histories(), instants(), st.sampled_from(["payload", "key", "duplicate_id", "backdated"])
)
def test_every_kind_of_invalid_later_fact_leaves_earlier_replays_alone(
    history: list[Fact], cutoff: datetime, variant: str
) -> None:
    baseline = snapshot_at(history, cutoff)
    later = cutoff + timedelta(minutes=5)
    bad = lot("zz", valid_from=later, known_at=later)
    match variant:
        case "payload":
            bad = bad.model_copy(update={"payload": {}})
        case "key":
            bad = bad.model_copy(update={"entity_key": "not a key"})
        case "duplicate_id":
            bad = bad.model_copy(update={"id": history[0].id})
        case "backdated":
            bad = bad.model_copy(update={"valid_from": later + timedelta(days=1)})
    extended = [*history, bad]
    assert snapshot_at(extended, cutoff) == baseline
    if variant == "duplicate_id":
        with pytest.raises(CorrectionError) as err:
            validate_corrections(extended)
        assert err.value.code == CorrectionErrorCode.DUPLICATE_ID
    else:
        with pytest.raises(FactValidationError):
            validate_fact(bad)
