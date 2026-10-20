"""As-known snapshots: visibility, corrections, observation ties, purity of inputs."""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from decisions.strategies import fact_histories, facts, instants
from flooreplay.decisions.facts import (
    NON_SEMANTIC_FIELDS,
    CorrectionError,
    CorrectionErrorCode,
    FactValidationError,
    semantic_digest,
    validate_corrections,
    validate_fact,
)
from flooreplay.decisions.snapshot import (
    CurrentStatus,
    current,
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


@given(fact_histories(), instants())
def test_cutoff_no_fact_known_after_cutoff(history: list[Fact], cutoff: datetime) -> None:
    snap = snapshot_at(history, cutoff)
    assert all(f.known_at <= cutoff for f in snap.facts)
    assert snap.cutoff == cutoff


@given(fact_histories(), instants(), st.randoms(use_true_random=False))
def test_shuffle_does_not_change_digest(
    history: list[Fact], cutoff: datetime, rnd: random.Random
) -> None:
    shuffled = list(history)
    rnd.shuffle(shuffled)
    a, b = snapshot_at(history, cutoff), snapshot_at(shuffled, cutoff)
    assert a.digest == b.digest
    assert a == b


@given(fact_histories())
def test_generated_facts_are_schema_valid(history: list[Fact]) -> None:
    for fact in history:
        assert validate_fact(fact).payload  # parses and normalises
    validate_corrections(history)


@given(fact_histories())
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
        assert correction.id in ids(after.facts) or any(
            f.supersedes_id == correction.id and f.known_at <= correction.known_at for f in history
        )
    assert history == before  # the input is never mutated


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
    assert findings[0].fact_ids == tuple(sorted(f.id for f in replacements))
    assert "orig" not in ids(snap.facts)  # superseded, and neither replacement wins silently
    assert sorted(ids(snap.facts)) == sorted(f.id for f in replacements)

    # Before the second replacement arrives there is only one: no finding.
    early = snapshot_at(history, replacements[0].known_at)
    assert early.findings == ()


@settings(suppress_health_check=[HealthCheck.too_slow])
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
    for kind, key in ((FactKind.FABRIC_LOT, "lot:L9"), (FactKind.FABRIC_QC, "lot:L1")):
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


@given(facts())
def test_generated_facts_are_never_backdated(fact: Fact) -> None:
    assert fact.valid_from <= fact.known_at


@given(facts(future_dated=True))
def test_future_dated_facts_are_available_for_negative_tests(fact: Fact) -> None:
    assert fact.known_at < fact.valid_from


@given(fact_histories(), instants())
def test_forked_histories_with_known_at_ties_are_deterministic(
    history: list[Fact], cutoff: datetime
) -> None:
    # Force a known_at tie across the whole history; supersession (strictly later)
    # is dropped, so only ties and forks remain. Order must not matter.
    tied = [
        f.model_copy(update={"known_at": history[0].known_at, "supersedes_id": None})
        for f in history
    ]
    forward = snapshot_at(tied, history[0].known_at)
    backward = snapshot_at(list(reversed(tied)), history[0].known_at)
    assert forward == backward
    for f in forward.facts:
        r = current(forward, f.kind, f.entity_key)
        assert r == current(backward, f.kind, f.entity_key)
