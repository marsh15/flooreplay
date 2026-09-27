"""Canonical hashing: reorder invariance and digest sensitivity."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from flooreplay.domain.hashing import canonical_json, digest
from flooreplay.domain.types import SkillRecord
from flooreplay.fixtures import hero_context, hero_snapshots_v1, hero_snapshots_v2

IST = ZoneInfo("Asia/Kolkata")


def test_timestamps_normalized_to_utc():
    # Same instant expressed in two zones canonicalizes identically.
    a = datetime(2026, 9, 22, 7, 58, tzinfo=IST)
    b = datetime(2026, 9, 22, 2, 28, tzinfo=UTC)
    assert canonical_json(a) == canonical_json(b)
    assert canonical_json(a) == '"2026-09-22T02:28:00Z"'


def test_reordered_unordered_collections_do_not_change_digest():
    ctx = hero_context(hero_snapshots_v1())
    ctx2 = hero_context(tuple(sorted(hero_snapshots_v1(), key=lambda s: s.id, reverse=True)))
    # snapshots tuple order is semantically unordered; skills rows likewise
    assert digest({"snapshots": ctx.snapshots}) == digest({"snapshots": ctx2.snapshots})


def test_changed_evidence_timestamp_changes_digest():
    ctx1 = hero_context(hero_snapshots_v1())
    ctx2 = hero_context(hero_snapshots_v2())
    assert digest(ctx1.snapshots) != digest(ctx2.snapshots)


def test_relevant_fact_change_changes_digest():
    base = SkillRecord(
        operator_id="O219",
        operation_id="OP-SLM",
        level=3,
        assessed_at=datetime(2026, 9, 18, 15, 0, tzinfo=IST),
        source_ref="row:9",
    )
    bumped = base.model_copy(
        update={"assessed_at": base.assessed_at + timedelta(days=1)}
    )
    assert digest(base) != digest(bumped)


def test_non_finite_numbers_rejected():
    import pytest

    with pytest.raises(ValueError):
        canonical_json({"x": float("nan")})
