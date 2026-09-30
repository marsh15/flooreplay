"""Preview bounded local incident files before all-or-nothing publication.

The caller stores original bytes and persists only a READY preview. This module
does no I/O, network fetching, or partial publication.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import datetime, timedelta
from pathlib import PurePath
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 10_000
PROFILES = {"production-v1", "operations-v1", "notes-v1"}
EVENT_TYPES = {
    "material_readiness", "line_block", "line_start", "machine_interruption",
    "staffing_event", "qc_hold", "qc_release", "setup_changeover",
    "reporting_correction", "plan_revision", "routine_note",
}
NOTE_TYPES = {"maintenance_note", "supervisor_note"}

HYPOTHESIS_CATEGORIES = {"material", "machine", "quality", "staffing", "changeover", "planning_reporting"}


def _list_field(value: Any) -> list[Any]:
    if value in (None, ""):
        return []
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, list):
        raise ValueError("Relationship fields must be JSON arrays")
    return value


def preview_identity(preview: dict[str, Any]) -> str:
    fields = ("raw_digest", "profile", "source_system", "timezone", "filename", "requested_unit", "scope", "interpretation_version", "plan_buckets", "output_buckets", "events", "issues", "status")
    encoded = json.dumps({field: preview.get(field) for field in fields}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _issue(row: int, field: str, code: str, message: str) -> dict[str, Any]:
    return {"row": row, "field": field, "code": code, "severity": "BLOCKING", "message": message}


def _time(value: Any, timezone: ZoneInfo) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Timestamp is required")
    try:
        moment = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Invalid ISO 8601 timestamp") from exc
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone)
        # A local time skipped by a DST transition has no real instant.
        if moment.astimezone(ZoneInfo("UTC")).astimezone(timezone).replace(fold=moment.fold) != moment:
            raise ValueError("Local time does not exist in the declared timezone")
    return moment.isoformat()


def _records(raw: bytes, filename: str) -> list[dict[str, Any]]:
    text = raw.decode("utf-8-sig")
    suffix = PurePath(filename).suffix.lower()
    if suffix == ".csv":
        reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
        if not reader.fieldnames or len(reader.fieldnames) != len(set(reader.fieldnames)):
            raise ValueError("CSV needs unique headers")
        csv_rows: list[dict[str, Any]] = []
        for row in reader:
            if None in row:
                raise ValueError("CSV row has more cells than headers")
            csv_rows.append(row)
            if len(csv_rows) > MAX_ROWS:
                raise ValueError("More than 10,000 rows")
        return csv_rows
    if suffix == ".json":
        payload = json.loads(text)
        rows = payload.get("records") if isinstance(payload, dict) else payload
    elif suffix == ".jsonl":
        rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    else:
        raise ValueError("Expected a local .csv, .json, or .jsonl file")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("JSON must contain an array of record objects")
    if len(rows) > MAX_ROWS:
        raise ValueError("More than 10,000 rows")
    return rows


def _normalize(row: dict[str, Any], profile: str, source_system: str, timezone: ZoneInfo, unit: str | None) -> tuple[str, dict[str, Any]]:
    record_id = str(row.get("id", "")).strip()
    if not record_id:
        raise ValueError("id is required")
    kind = str(row.get("record_type", "")).strip()
    available = _time(row.get("available_at"), timezone)
    common: dict[str, Any] = {"id": record_id, "available_at": available, "source_id": str(row.get("source_id") or f"{source_system}:{record_id}")}
    if row.get("supersedes_id"):
        common["supersedes_id"] = str(row["supersedes_id"])
    for field in ("factory", "line_id", "order_id", "style_id", "stage"):
        if row.get(field):
            common[field] = str(row[field]).strip()
    if not common.get("line_id"):
        raise ValueError("line_id is required to establish incident scope")
    if profile == "production-v1":
        if any(not common.get(field) for field in ("factory", "order_id", "style_id", "stage")):
            raise ValueError("Production records require factory, order_id, style_id, and stage")
        if kind not in {"baseline_plan", "final_good_delta"}:
            raise ValueError("Production record_type must be baseline_plan or final_good_delta")
        declared_unit = str(row.get("unit") or unit or "")
        if declared_unit != "good_units":
            raise ValueError("Production unit must be explicitly declared as good_units")
        if row.get("count_mode", "delta") != "delta":
            raise ValueError("Cumulative counts are unsupported; supply 15-minute deltas")
        quantity = row.get("quantity")
        quantity_text = str(quantity)
        if isinstance(quantity, bool) or not quantity_text.isdigit():
            raise ValueError("quantity must be a nonnegative integer")
        start = _time(row.get("start"), timezone)
        end = _time(row.get("end"), timezone)
        start_at = datetime.fromisoformat(start)
        if start_at.minute % 15 or start_at.second or start_at.microsecond:
            raise ValueError("Production buckets must start on a 15-minute boundary")
        if datetime.fromisoformat(end) - datetime.fromisoformat(start) != timedelta(minutes=15):
            raise ValueError("Production buckets must span exactly 15 minutes")
        return ("plan_buckets" if kind == "baseline_plan" else "output_buckets"), {
            **common, "kind": kind, "quantity": int(quantity_text), "unit": declared_unit,
            "start": start, "end": end,
        }
    if profile == "operations-v1":
        if kind not in EVENT_TYPES:
            raise ValueError("Unsupported operations record_type")
    elif kind not in NOTE_TYPES:
        raise ValueError("Notes record_type must be maintenance_note or supervisor_note")
    summary = row.get("summary") or row.get("text")
    if not isinstance(summary, str) or not summary.strip() or len(summary) > 2000:
        raise ValueError("summary or text must contain 1–2000 characters")
    event = {**common, "type": kind, "summary": summary.strip(), "lane": {
        "material_readiness": "materials", "machine_interruption": "machines",
        "maintenance_note": "machines", "qc_hold": "quality", "qc_release": "quality",
        "staffing_event": "staffing",
    }.get(kind, "production")}
    if profile == "notes-v1":
        if not row.get("author_role"):
            raise ValueError("Notes require author_role attribution")
        event["assertion"] = True
        event["author_role"] = str(row["author_role"])
    links = _list_field(row.get("hypothesis_links"))
    for link in links:
        if not isinstance(link, dict) or set(link) - {"category", "relation", "source_id"} or link.get("category") not in HYPOTHESIS_CATEGORIES or link.get("relation") not in {"SUPPORTS", "CONTRADICTS"}:
            raise ValueError("Hypothesis links require a known category and SUPPORTS or CONTRADICTS relation")
    # Preserve legacy category fields as typed, source-attributed links.
    for field, relation in (("linked_categories", "SUPPORTS"), ("contradicts_categories", "CONTRADICTS")):
        for category in _list_field(row.get(field)):
            if category not in HYPOTHESIS_CATEGORIES:
                raise ValueError("Unknown hypothesis category")
            links.append({"category": category, "relation": relation})
    event["hypothesis_links"] = [{**link, "source_id": common["source_id"]} for link in links]
    refs = _list_field(row.get("contradiction_refs"))
    if row.get("contradicts"):
        refs.append(row["contradicts"])
    if any(not isinstance(ref, str) or not ref.strip() for ref in refs):
        raise ValueError("Contradiction references must be record IDs")
    event["contradiction_refs"] = refs
    if row.get("carry_in_state"):
        if row["carry_in_state"] != "UNRESOLVED":
            raise ValueError("carry_in_state must be UNRESOLVED")
        event["carry_in_state"] = "UNRESOLVED"
    if row.get("occurred_at"):
        event["occurred_at"] = _time(row["occurred_at"], timezone)
    if row.get("start"):
        event["start"] = _time(row["start"], timezone)
    if row.get("end"):
        event["end"] = _time(row["end"], timezone)
    if not (event.get("occurred_at") or event.get("start")):
        raise ValueError("occurred_at or start is required")
    if event.get("end") and (not event.get("start") or datetime.fromisoformat(event["end"]) <= datetime.fromisoformat(event["start"])):
        raise ValueError("end must follow start")
    if row.get("line_blocking") in (True, "true", "TRUE", "1", "yes"):
        if kind != "line_block" or not (event.get("start") and event.get("end")):
            raise ValueError("Only explicit line_block intervals may be line_blocking")
        event["line_blocking"] = True
    return "events", event


def preview_incident_import(
    raw: bytes, *, profile: str, source_system: str, timezone: str,
    filename: str, unit: str | None = None, scope: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Return diagnostics and normalized records; any issue blocks publication."""
    if profile not in PROFILES or not source_system.strip() or not timezone.strip():
        raise ValueError("Explicit profile, source_system, and timezone are required")
    if filename.startswith(("http://", "https://")):
        raise ValueError("Remote URLs are unsupported")
    try:
        zone = ZoneInfo(timezone)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("Unknown timezone") from exc
    if not raw or len(raw) > MAX_BYTES:
        raise ValueError("File must contain 1 byte to 2 MiB")
    try:
        rows = _records(raw, filename)
    except (UnicodeDecodeError, csv.Error, json.JSONDecodeError) as exc:
        raise ValueError(f"File cannot be decoded: {type(exc).__name__}") from exc
    if not rows:
        raise ValueError("File has no records")
    normalized: dict[str, list[dict[str, Any]]] = {"plan_buckets": [], "output_buckets": [], "events": []}
    issues: list[dict[str, Any]] = []
    seen: set[str] = set()
    seen_buckets: set[tuple[str, str, str, str, str, str, str, str]] = set()
    for number, row in enumerate(rows, start=1):
        try:
            section, value = _normalize(row, profile, source_system, zone, unit)
            if value["id"] in seen:
                raise ValueError("Duplicate record id")
            if section in {"plan_buckets", "output_buckets"}:
                natural = (value["kind"], value["factory"], value["line_id"], value["order_id"], value["style_id"], value["stage"], value["start"], value["end"])
                if natural in seen_buckets and not value.get("supersedes_id"):
                    raise ValueError("Duplicate production bucket for the same scope and interval")
                seen_buckets.add(natural)
            seen.add(value["id"])
            normalized[section].append(value)
        except ValueError as exc:
            issues.append(_issue(number, "record", "INVALID_RECORD", str(exc)))
    preview = {
        "requested_unit": unit, "scope": scope, "interpretation_version": "incident-import-v2",
        "status": "READY" if not issues else "BLOCKED", "profile": profile,
        "source_system": source_system, "timezone": timezone, "filename": filename,
        "raw_digest": hashlib.sha256(raw).hexdigest(), "row_count": len(rows),
        "issues": issues, **normalized,
    }
    preview["preview_digest"] = preview_identity(preview)
    return preview


def publish_incident_import(preview: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Return revision payload sections only if every row passed preview."""
    if preview.get("status") != "READY" or preview.get("issues"):
        raise ValueError("All rows must pass preview before publication")
    return {section: list(preview[section]) for section in ("plan_buckets", "output_buckets", "events")}
