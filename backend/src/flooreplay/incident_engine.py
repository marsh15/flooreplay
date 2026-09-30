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


def validate_corrections(rows: list[dict[str, Any]], scope: dict[str, Any] | None = None) -> None:
    """Validate the complete graph before selecting the as-known active records."""
    scope = scope or {}
    by_id = {str(row["id"]): row for row in rows}
    if len(by_id) != len(rows):
        raise ValueError("Duplicate source record ID")
    scope_fields = ("factory", "line_id", "order_id", "style_id", "stage", "unit")
    for row in rows:
        target_id = row.get("supersedes_id") or row.get("supersedes")
        if not target_id:
            continue
        target = by_id.get(str(target_id))
        if target is None:
            raise ValueError("Correction references an unknown record")
        visited = {str(row["id"])}
        cursor: dict[str, Any] | None = target
        while cursor:
            if str(cursor["id"]) in visited:
                raise ValueError("Correction graph contains a cycle")
            visited.add(str(cursor["id"]))
            cursor = by_id.get(str(cursor.get("supersedes_id") or cursor.get("supersedes")))
        if any(row.get(field, scope.get(field)) != target.get(field, scope.get(field)) for field in scope_fields):
            raise ValueError("Correction scope must match its referenced record")
        if row.get("type") != target.get("type") or row.get("kind") != target.get("kind"):
            raise ValueError("Correction category must match its referenced record")
        if "quantity" in row and any(_time(row[field]) != _time(target[field]) for field in ("start", "end")):
            raise ValueError("Correction must refer to the same production interval")
        if _time(row["available_at"]) <= _time(target["available_at"]):
            raise ValueError("Correction must become available after its referenced record")


def _visible(rows: list[dict[str, Any]], cutoff: datetime, scope: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    validate_corrections(rows, scope)
    visible = [row for row in rows if _time(row["available_at"]) <= cutoff]
    replaced = {str(row.get("supersedes_id") or row.get("supersedes")) for row in visible}
    return [row for row in visible if str(row["id"]) not in replaced]


def _correction_conflicts(rows: list[dict[str, Any]], cutoff: datetime) -> list[dict[str, Any]]:
    children: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        target = row.get("supersedes_id") or row.get("supersedes")
        if target and _time(row["available_at"]) <= cutoff:
            children[str(target)].append(str(row["id"]))
    return [{"record_id": target, "replacement_ids": sorted(ids)} for target, ids in children.items() if len(ids) > 1]


def _in_window(event: dict[str, Any], start: datetime, end: datetime) -> bool:
    occurrence = _time(event.get("start") or event["occurred_at"])
    if event.get("end"):
        return occurrence < end and _time(event["end"]) > start
    return start <= occurrence < end or (occurrence < start and event.get("carry_in_state") == "UNRESOLVED")


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
    for row in _visible(rows, cutoff, scope):
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
        if not event.get("line_blocking") or event.get("context_only") or "start" not in event:
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
    all_records = [row for section in ("plan_buckets", "output_buckets", "events") for row in revision.get(section, [])]
    ids = {str(row["id"]) for row in all_records}
    if len(ids) != len(all_records):
        raise ValueError("Duplicate source record ID across incident sections")
    for event in revision.get("events", []):
        if any(ref not in ids for ref in event.get("contradiction_refs", [])):
            raise ValueError("Contradiction references an unknown record")
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
    metric_inputs: list[dict[str, Any]] = [
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

    correction_conflicts: list[dict[str, Any]] = [conflict for section in ("plan_buckets", "output_buckets", "events") for conflict in _correction_conflicts(revision.get(section, []), cutoff)]
    events = []
    for event in _visible(revision.get("events", []), cutoff, scope):
        if not _scope_matches(event, scope):
            continue
        occurrence = event.get("occurred_at") or event.get("start")
        if occurrence is None or _time(occurrence) > effective_end:
            continue
        item = dict(event)
        item["context_only"] = not _in_window(item, start, effective_end)
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
    observation_watermark = max((key[1] for key in matched), default=start)
    remaining_minutes = max(0, int((end - observation_watermark).total_seconds() / 60))
    remaining_target = max(0, baseline_target - matched_observed) if complete and baseline_target is not None else None
    target_pressure = {
        "remaining_target": remaining_target,
        "remaining_working_minutes": remaining_minutes,
        "remaining_elapsed_minutes": remaining_minutes,
        "as_of": observation_watermark.isoformat(),
        "time_basis": "elapsed_wall_clock",
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
        "assumptions": ["Elapsed wall-clock time from the observation watermark to window end; breaks and shift calendars are not modeled."],
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
            if not event.get("context_only") and (event.get("type") in event_types or category in event.get("linked_categories", []) or any(link["category"] == category and link["relation"] == "SUPPORTS" for link in event.get("hypothesis_links", [])))
        ]
        if not related:
            continue
        support = [str(event["id"]) for event in related]
        contradict = [
            str(event["id"])
            for event in events
            if not event.get("context_only") and (event.get("contradicts") in support or any(target in support for target in event.get("contradiction_refs", [])) or category in event.get("contradicts_categories", []) or any(link["category"] == category and link["relation"] == "CONTRADICTS" for link in event.get("hypothesis_links", [])))
        ]
        established = any(event.get("line_blocking") and event.get("start") and _time(event["start"]) < effective_end and _time(event.get("end", effective_end.isoformat())) > start for event in related)
        conflicted_ids = {record_id for conflict in correction_conflicts for record_id in conflict["replacement_ids"]}
        evidence_conflict = bool(conflicted_ids.intersection(support))
        hypotheses.append(
            {
                "category": category,
                "status": "CONFLICTING" if evidence_conflict else "CONTRADICTED" if contradict else "SUPPORTED" if established else "PLAUSIBLE",
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

    production_refs = [record["id"] for entry in metric_inputs for record in (entry["plan"], entry["output"])]
    interval = {"start": start.isoformat(), "end": observation_watermark.isoformat()}
    metrics["observation_watermark"] = observation_watermark.isoformat()
    metrics["descriptors"] = [
        {"id": name, "value": metrics[name], "unit": unit, "formula": formula, "interval": interval, "input_refs": production_refs}
        for name, formula in (("planned", "sum(matched baseline plan quantities)"), ("observed", "sum(matched final-good delta quantities)"), ("variance", "observed - planned"), ("shortfall", "max(0, planned - observed)"))
    ] + [{"id": "baseline_target", "value": baseline_target, "unit": unit, "formula": "sum(all baseline plan quantities for declared window)", "interval": {"start": start.isoformat(), "end": end.isoformat()}, "input_refs": [plans[key][0]["id"] for key in expected_keys if key in plans and len(plans[key]) == 1]}] + [{"id": "blocked_minutes", "value": blocked_minutes, "unit": "minutes", "formula": "duration(union(explicit line-block intervals intersected with investigation window))", "interval": {"start": start.isoformat(), "end": effective_end.isoformat()}, "input_refs": sorted({ref for segment in block_segments for ref in segment["evidence"]})}]
    metrics["descriptors"].extend([
        {"id": "remaining_target", "value": remaining_target, "unit": unit, "formula": "max(0, baseline_target - observed)", "interval": {"start": observation_watermark.isoformat(), "end": end.isoformat()}, "input_refs": sorted(set(production_refs + [plans[key][0]["id"] for key in expected_keys if key in plans and len(plans[key]) == 1]))},
        {"id": "remaining_elapsed_minutes", "value": remaining_minutes, "unit": "minutes", "formula": "window_end - observation_watermark (elapsed wall-clock)", "interval": {"start": observation_watermark.isoformat(), "end": end.isoformat()}, "input_refs": production_refs},
        {"id": "required_units_per_hour", "value": target_pressure["required_units_per_hour"], "unit": f"{unit}/hour", "formula": "remaining_target * 60 / remaining_elapsed_minutes", "interval": {"start": observation_watermark.isoformat(), "end": end.isoformat()}, "input_refs": sorted(set(production_refs + [plans[key][0]["id"] for key in expected_keys if key in plans and len(plans[key]) == 1]))},
    ])
    declarations = revision.get("coverage", {})
    coverage_complete = bool(declarations) and all(
        isinstance(value, dict) and value.get("complete") is True and not value.get("gaps")
        and value.get("start") and value.get("end")
        and _time(value["start"]) <= start and _time(value["end"]) >= effective_end
        for value in declarations.values()
    )
    timeline_status = "CONFLICTING" if correction_conflicts else "COMPLETE" if coverage_complete else "PARTIAL" if events else "UNAVAILABLE"
    capabilities = {
        "production": {"status": production_status, "reasons": reasons},
        "timeline": {"status": timeline_status, "reasons": [] if coverage_complete else ["Source coverage for the investigation interval is not declared complete."]},
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
        "scope": scope,
        "revision": revision.get("revision"),
        "cutoff": cutoff.isoformat(),
        "observation_watermark": observation_watermark.isoformat(),
        "source_coverage": declarations,
        "correction_conflicts": correction_conflicts,
        "correction_history": [{**row, "previous_record": next(record for record in all_records if str(record["id"]) == str(row.get("supersedes_id") or row.get("supersedes")))} for row in all_records if (row.get("supersedes_id") or row.get("supersedes")) and _time(row["available_at"]) <= cutoff],
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
