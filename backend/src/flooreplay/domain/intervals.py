"""Half-open interval semantics: [start, end).

Touching endpoints do not overlap. An assignment ending at 08:00 never
conflicts with coverage starting at 08:00. Zero-length and reversed
intervals are invalid everywhere.
"""

from __future__ import annotations

from datetime import datetime


class InvalidInterval(ValueError):
    pass


def validate(start: datetime, end: datetime, label: str = "interval") -> None:
    if start.tzinfo is None or end.tzinfo is None:
        raise InvalidInterval(f"{label}: naive endpoints are not allowed")
    if end <= start:
        raise InvalidInterval(f"{label}: end must be after start")


def overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    """True when [a_start, a_end) and [b_start, b_end) share any instant."""
    return a_start < b_end and b_start < a_end


def contains(outer_start: datetime, outer_end: datetime, inner_start: datetime, inner_end: datetime) -> bool:
    """True when [inner_start, inner_end) lies wholly inside the outer window."""
    return outer_start <= inner_start and inner_end <= outer_end
