"""Half-open interval semantics."""

from __future__ import annotations

from datetime import UTC, datetime

from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from flooreplay.domain.intervals import contains, overlaps, validate

T = UTC


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 9, 22, hour, minute, tzinfo=T)


def test_touching_endpoints_do_not_overlap():
    assert not overlaps(at(7), at(8), at(8), at(9))


def test_one_minute_overlap_does_overlap():
    assert overlaps(at(7), at(8, 1), at(8), at(9))


def test_containment_is_not_overlap_at_edges():
    assert overlaps(at(7), at(10), at(8), at(9))  # strict containment overlaps


def test_reversed_interval_rejected():
    import pytest

    with pytest.raises(ValueError):
        validate(at(9), at(8))


def test_zero_length_interval_rejected():
    import pytest

    with pytest.raises(ValueError):
        validate(at(8), at(8))


def test_naive_interval_rejected():
    import pytest

    with pytest.raises(ValueError):
        validate(datetime(2026, 9, 22, 8), datetime(2026, 9, 22, 9))


@hyp_settings(max_examples=200)
@given(
    a_start=st.integers(0, 20),
    a_end=st.integers(1, 21),
    b_start=st.integers(0, 20),
    b_end=st.integers(1, 21),
)
def test_overlap_is_symmetric(a_start, a_end, b_start, b_end):
    s1, e1, s2, e2 = at(a_start), at(max(a_start + 1, a_end)), at(b_start), at(max(b_start + 1, b_end))
    assert overlaps(s1, e1, s2, e2) == overlaps(s2, e2, s1, e1)


def test_contains_requires_full_inclusion():
    assert contains(at(8), at(12), at(8), at(12))
    assert contains(at(8), at(12), at(9), at(11))
    assert not contains(at(8), at(12), at(9), at(13))
    assert not contains(at(9), at(12), at(8), at(11))
    assert not contains(at(8), at(12), at(7), at(11))
