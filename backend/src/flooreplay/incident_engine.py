"""Pure, as-known analysis for a single sewing-line incident revision."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any


def _time(value: str) -> datetime:
    instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("Incident timestamps must include a timezone")
    return instant


def _visible(rows: list[dict[str, Any]], cutoff: datetime) -> list[dict[str, Any]]:
    visible = [row for row in rows if _time(row["available_at"]) <= cutoff]
    ids = [str(row["id"]) for row in visible]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate source record ID")
    replaced = {str(row.get("supersedes_id") or row.get("supersedes")) for row in visible}
    return [row for row in visible if str(row["id"]) not in replaced]


def _scope_matches(row: dict[str, Any], scope: dict[str, Any]) -> bool:
    return all(key not in row or row[key] == value for key, value in scope.items())


def _bucket_key(row: dict[str, Any]) -> tuple[datetime, datetime]:
    start, end = _time(row["start"]), _time(row["end"])
    if end - start != timedelta(minutes=15):
        raise ValueError("Production buckets must be exactly 15 minutes")
    return start, end


def _buckets(
    rows: list[dict[str, Any]], scope: dict[str, Any], cutoff: datetime
) -> dict[tuple[datetime, datetime], list[dict[str, Any]]]:
    grouped: dict[tuple[datetime, datetime], list[dict[str, Any]]] = defaultdict(list)
    for row in _visible(rows, cutoff):
        if not _scope_matches(row, scope):
            continue
        if row.get("kind", "final_good_delta") not in ("final_good_delta", "baseline_plan"):
            raise ValueError("Only final-good delta output and baseline plan buckets are supported")
        quantity = row["quantity"]
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 0:
            raise ValueError("Bucket quantity must be a nonnegative integer")
        grouped[_bucket_key(row)].append(row)
    return grouped


def _blocks(events: list[dict[str, Any]], start: datetime, end: datetime) -> tuple[int, list[dict[str, Any]]]:
    boundaries: set[datetime] = set()
    intervals: list[tuple[datetime, datetime, str]] = []
    for event in events:
        if not event.get("line_blocking") or "start" not in event:
            continue
        left = max(_time(event["start"]), start)
        right = min(_time(event.get("end", end.isoformat())), end)
        if left < right:
            boundaries.update((left, right))
            intervals.append((left, right, str(event["id"])))
    ordered = sorted(boundaries)
    segments: list[dict[str, Any]] = []
    for left, right in zip(ordered, ordered[1:], strict=False):
        reasons = sorted(event_id for a, b, event_id in intervals if a < right and b > left)
        if reasons:
            segments.append(
                {"start": left.isoformat(), "end": right.isoformat(), "evidence": reasons}
            )
    minutes = int(
        sum((_time(s["end"]) - _time(s["start"])).total_seconds() / 60 for s in segments)
    )
    return minutes, segments


def analyze_incident(revision: dict[str, Any]) -> dict[str, Any]:
    """Return a JSON-serializable report; never read external state or infer missing counts."""
    scope = revision["scope"]
    unit = scope["unit"]
    start, end = _time(revision["window"]["start"]), _time(revision["window"]["end"])
    cutoff = _time(revision["cutoff"])
    if not start < end or cutoff < start:
        raise ValueError("Invalid investigation window or cutoff")
    if (end - start).total_seconds() % 900:
        raise ValueError("Investigation window must contain complete 15-minute buckets")
    effective_end = min(end, cutoff)

    plans = _buckets(revision.get("plan_buckets", []), scope, cutoff)
    outputs = _buckets(revision.get("output_buckets", []), scope, cutoff)
    plan_keys = sorted(key for key in plans if start <= key[0] and key[1] <= end)
    expected_keys = [
        (start + timedelta(minutes=15 * i), start + timedelta(minutes=15 * (i + 1)))
        for i in range(int((end - start).total_seconds() // 900))
    ]
    missing_plans = [key for key in expected_keys if key[1] <= effective_end and key not in plans]
    unexpected_plans = [key for key in plan_keys if key not in expected_keys]
    orphan_outputs = [key for key in outputs if start <= key[0] and key[1] <= effective_end and key not in plans]
    completed = [key for key in plan_keys if key[1] <= effective_end]
    unfinished = [plans[key][0]["id"] for key in plan_keys if key[0] < effective_end < key[1]]
    conflicts = [key for key in plan_keys if len(plans[key]) != 1 or len(outputs.get(key, [])) > 1]
    missing = [plans[key][0]["id"] for key in completed if key not in outputs and len(plans[key]) == 1]
    matched = [key for key in completed if len(plans[key]) == len(outputs.get(key, [])) == 1]
    baseline_complete = all(key in plans and len(plans[key]) == 1 for key in expected_keys)
    baseline_target = sum(plans[key][0]["quantity"] for key in expected_keys) if baseline_complete else None
    matched_planned = sum(plans[key][0]["quantity"] for key in matched)
    matched_observed = sum(outputs[key][0]["quantity"] for key in matched)
    metric_inputs = [
        {
            "start": key[0].isoformat(), "end": key[1].isoformat(),
            "plan": {"id": plans[key][0]["id"], "quantity": plans[key][0]["quantity"]},
            "output": {"id": outputs[key][0]["id"], "quantity": outputs[key][0]["quantity"]},
        }
        for key in matched
    ]

    if not plan_keys:
        production_status = "UNAVAILABLE"
        reasons = ["No baseline plan buckets are available at this cutoff."]
    elif conflicts or orphan_outputs or unexpected_plans:
        production_status = "CONFLICTING"
        reasons = ["Production buckets conflict or output has no matching baseline plan bucket."]
    elif not completed:
        production_status = "PARTIAL"
        reasons = ["No complete planned bucket has ended by the cutoff."]
    elif missing or missing_plans or not baseline_complete:
        production_status = "PARTIAL"
        reasons = ["Baseline plan or output is missing for the declared investigation window."]
    else:
        production_status = "COMPLETE"
        reasons = []
    if unfinished:
        reasons.append("The bucket containing the cutoff is excluded from comparable totals.")

    events = []
    for event in _visible(revision.get("events", []), cutoff):
        if not _scope_matches(event, scope):
            continue
        occurrence = event.get("occurred_at") or event.get("start")
        if occurrence is None or _time(occurrence) > effective_end:
            continue
        item = dict(event)
        if item.get("line_blocking") and item.get("end") and _time(item["end"]) > effective_end:
            item["end"] = effective_end.isoformat()
            item["truncated_at_cutoff"] = True
        events.append(item)
    events.sort(key=lambda event: (_time(event.get("occurred_at") or event["start"]), str(event["id"])))
    blocked_minutes, block_segments = _blocks(events, start, effective_end)

    # A complete shortfall needs observations for every completed planned bucket.
    complete = production_status == "COMPLETE"
    planned = matched_planned if complete else None
    observed = matched_observed if complete else None
    variance = matched_observed - matched_planned if complete else None
    shortfall = max(0, matched_planned - matched_observed) if complete else None
    remaining_minutes = max(0, int((end - effective_end).total_seconds() / 60))
    remaining_target = max(0, baseline_target - matched_observed) if complete and baseline_target is not None else None
    target_pressure = {
        "remaining_target": remaining_target,
        "remaining_working_minutes": remaining_minutes,
        "required_units_per_hour": (
            round(remaining_target * 60 / remaining_minutes, 2)
            if remaining_target is not None and remaining_minutes
            else None
        ),
        "baseline_units_per_hour": (
            round(baseline_target * 60 / ((end - start).total_seconds() / 60), 2)
            if baseline_target is not None
            else None
        ),
        "target_met": remaining_target == 0 if remaining_target is not None else None,
        "assumptions": ["Remaining scheduled time runs through the investigation window end."],
    }
    metrics = {
        "status": production_status,
        "planned": planned,
        "observed": observed,
        "variance": variance,
        "shortfall": shortfall,
        "unit": unit,
        "formula": "variance = observed - planned; shortfall = max(0, planned - observed)",
        "inputs": metric_inputs,
        "matched_buckets": [plans[key][0]["id"] for key in matched],
        "missing_buckets": missing,
        "missing_plan_buckets": [key[0].isoformat() for key in missing_plans],
        "unfinished_buckets": unfinished,
        "baseline_target": baseline_target,
        "blocked_minutes": blocked_minutes,
        "block_segments": block_segments,
        "target_pressure": target_pressure,
    }

    categories = {
        "material": ({"material_readiness"}, "verify_material_availability", "Production lead"),
        "machine": ({"machine_interruption", "maintenance_note"}, "request_maintenance_status", "Maintenance lead"),
        "quality": ({"qc_hold"}, "request_qc_disposition", "Quality reviewer"),
        "staffing": ({"staffing", "staffing_event"}, "verify_staffing_coverage", "Production lead"),
        "changeover": ({"setup_changeover"}, "review_shift_target", "Production lead"),
        "planning_reporting": ({"reporting_correction", "plan_revision"}, "review_shift_target", "Production lead"),
    }
    hypotheses = []
    proposals = []
    for category, (event_types, action_type, owner) in categories.items():
        related = [
            event for event in events
            if event.get("type") in event_types or category in event.get("linked_categories", [])
        ]
        if not related:
            continue
        support = [str(event["id"]) for event in related]
        contradict = [
            str(event["id"])
            for event in events
            if event.get("contradicts") in support or category in event.get("contradicts_categories", [])
        ]
        established = any(event.get("line_blocking") for event in related)
        hypotheses.append(
            {
                "category": category,
                "status": "CONTRADICTED" if contradict else "SUPPORTED" if established else "PLAUSIBLE",
                "mechanism": (
                    "A recorded line block establishes lost operating time. Its share of the output shortfall is unknown."
                    if established
                    else "This event may have affected production, but a line-level effect is not established."
                ),
                "supporting_evidence": support,
                "contradicting_evidence": contradict,
                "next_check": f"Confirm whether the {category.replace('_', ' ')} event blocked this line and for how long.",
            }
        )
        proposals.append(
            {
                "id": f"verify-{category}",
                "type": action_type,
                "owner_role": owner,
                "supporting_evidence": support,
                "preconditions": ["Review the cited evidence and current incident revision."],
                "missing_information": [hypotheses[-1]["next_check"]],
                "purpose": "Clarify the blocker before choosing a recovery response.",
                "state": "DRAFT",
            }
        )

    capabilities = {
        "production": {"status": production_status, "reasons": reasons},
        "timeline": {"status": "COMPLETE" if events else "UNAVAILABLE", "reasons": [] if events else ["No events are available at this cutoff."]},
        "hypotheses": {"status": "PARTIAL" if hypotheses else "UNAVAILABLE", "reasons": ["Causal attribution requires more than chronology."] if hypotheses else ["No relevant event evidence is available."]},
        "actions": {"status": "PARTIAL" if proposals else "UNAVAILABLE", "reasons": ["Proposals require human review and do not execute factory changes."] if proposals else ["No evidence-linked proposal is available."]},
    }
    situation = (
        f"Recorded good output is {observed} {unit} against {planned} planned; the observed shortfall is {shortfall} {unit}."
        if complete
        else "Available production records do not support a complete shortfall calculation."
    )
    summary = f"{situation} {blocked_minutes} minutes of explicit line blocking are recorded. Event timing alone does not establish how much of the shortfall each event caused."
    return {
        "metrics": metrics,
        "timeline": events,
        "hypotheses": hypotheses,
        "capabilities": capabilities,
        "proposals": proposals,
        "summary": summary,
    }


def incident_evidence_card(revision: dict[str, Any]) -> str:
    """Only facts visible at this revision's cutoff enter lexical search."""
    timeline = analyze_incident(revision)["timeline"]
    return " ".join([revision["title"], *(f"{event['type']} {event['summary']}" for event in timeline)])[:20_000]
