"""Separate delayed or missing source records from production that was reported.

A planned interval with no output record is not lost production: the record may
still be on its way, or the source may have skipped it. This module reports which
case each interval is in, as known at the revision cutoff, without changing the
deterministic analysis.
"""

from __future__ import annotations

from datetime import datetime
from statistics import median
from typing import Any

from .incident_engine import _scope_matches, _time, _visible, analyze_incident

LATE_RECORD_MINUTES = 15


def _minutes(delta_seconds: float) -> int:
    return int(delta_seconds // 60)


def source_health(revision: dict[str, Any], imports: list[dict[str, Any]]) -> dict[str, Any]:
    """Return the as-known state of each source feed for one incident revision."""
    scope, cutoff = revision["scope"], _time(revision["cutoff"])
    start, end = _time(revision["window"]["start"]), _time(revision["window"]["end"])
    report = analyze_incident(revision)
    plans = [row for row in _visible(revision.get("plan_buckets", []), cutoff, scope) if _scope_matches(row, scope) and start <= _time(row["start"]) and _time(row["end"]) <= end]
    outputs = [row for row in _visible(revision.get("output_buckets", []), cutoff, scope) if _scope_matches(row, scope)]
    by_interval: dict[datetime, list[dict[str, Any]]] = {}
    for row in outputs:
        by_interval.setdefault(_time(row["start"]), []).append(row)
    delays = [(_time(row["available_at"]) - _time(row["end"])).total_seconds() for row in outputs]
    typical_delay = _minutes(median(delays)) if delays else None
    latest_reported = max((_time(row["end"]) for row in outputs), default=None)

    intervals: list[dict[str, Any]] = []
    for plan in sorted(plans, key=lambda row: _time(row["start"])):
        interval_start, interval_end = _time(plan["start"]), _time(plan["end"])
        entry: dict[str, Any] = {"start": plan["start"], "end": plan["end"], "plan_id": plan["id"], "planned": plan["quantity"]}
        reported = by_interval.get(interval_start, [])
        if interval_end > cutoff:
            entry["status"] = "NOT_DUE"
        elif len(reported) > 1:
            entry.update(status="CONFLICTING", output_ids=sorted(str(row["id"]) for row in reported))
        elif reported:
            entry.update(status="REPORTED", output_id=reported[0]["id"], reported=reported[0]["quantity"])
        else:
            waited = _minutes((cutoff - interval_end).total_seconds())
            # A later reported interval means the feed moved past this one without a record.
            status = "GAP" if latest_reported is not None and latest_reported > interval_end else "AWAITING"
            entry.update(status=status, minutes_since_due=waited)
            if status == "AWAITING" and typical_delay is not None:
                entry["overdue"] = waited > typical_delay
        intervals.append(entry)

    counts = {status: sum(entry["status"] == status for entry in intervals) for status in ("REPORTED", "AWAITING", "GAP", "CONFLICTING", "NOT_DUE")}
    shortfall_intervals = [entry["plan_id"] for entry in intervals if entry["status"] == "REPORTED" and entry["reported"] < entry["planned"]]
    lag = _minutes((cutoff - max(_time(row["available_at"]) for row in outputs)).total_seconds()) if outputs else None
    events = [row for row in _visible(revision.get("events", []), cutoff, scope) if _scope_matches(row, scope)]
    late = [str(row["id"]) for row in events if (row.get("occurred_at") or row.get("start")) and (_time(row["available_at"]) - _time(row.get("occurred_at") or row["start"])).total_seconds() > LATE_RECORD_MINUTES * 60]
    return {
        "as_of": cutoff.isoformat(),
        "production_feed": {
            "expected_interval_minutes": 15,
            "latest_reported_interval_end": latest_reported.isoformat() if latest_reported else None,
            "latest_available_at": max((row["available_at"] for row in outputs), key=_time) if outputs else None,
            "minutes_since_latest_record": lag,
            "typical_delay_minutes": typical_delay,
            "counts": counts,
            "intervals": intervals,
            "intervals_reported_below_plan": shortfall_intervals,
        },
        "operations_feed": {
            "records": len(events),
            "latest_available_at": max((row["available_at"] for row in events), key=_time) if events else None,
            "late_threshold_minutes": LATE_RECORD_MINUTES,
            "late_record_ids": late,
        },
        "conflicts": {"correction_conflicts": report["correction_conflicts"], "conflicting_intervals": [entry["plan_id"] for entry in intervals if entry["status"] == "CONFLICTING"]},
        "imports": imports,
        "rejections": {"recorded": False, "reason": "Blocked previews are never stored, so rejected rows are not counted here. Only published imports appear."},
        "summary": _summary(counts, shortfall_intervals),
    }


def _intervals(count: int) -> str:
    return f"{count} due interval{'' if count == 1 else 's'}"


def _summary(counts: dict[str, int], shortfall_intervals: list[str]) -> str:
    unreported = counts["AWAITING"] + counts["GAP"]
    parts = [f"{_intervals(counts['REPORTED'])} reported"]
    if shortfall_intervals:
        parts.append(f"{len(shortfall_intervals)} below plan")
    if unreported:
        parts.append(f"{_intervals(unreported)} without a record ({counts['AWAITING']} awaiting, {counts['GAP']} skipped by the feed). A missing record is missing data, not lost output")
    if counts["CONFLICTING"]:
        parts.append(f"{_intervals(counts['CONFLICTING'])} with conflicting records")
    return "; ".join(parts) + "."
