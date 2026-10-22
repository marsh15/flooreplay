"""Pure, deterministic CSV previews for the v2 source profiles.

Column mappings always point from a canonical field name to one exact CSV header,
for example ``{"lot_id": "ERP lot"}``. No header aliases or column guessing are
applied. Quantity units come from the mapped ``unit`` column or the ``units``
argument keyed by quantity field. ``order-requests`` combines one order and its
style BOM on each row; colours and trims are JSON arrays. ERP allocation columns
are optional (``allocation_order_id`` and ``allocation_qty``); supplier QC is
optional and becomes a fact only when an explicit ``qc_issue`` and ``qc_qty``
are both present. Incomplete mapped allocation/QC data is a blocking problem.

The module does not read a clock, perform I/O beyond parsing provided bytes, or
write facts anywhere. ``known_at`` is a deterministic placeholder equal to
``as_of`` and must be replaced by the publishing service.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import unicodedata
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import PurePath
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flooreplay.decisions.facts import validate_fact
from flooreplay.decisions.gate import CoverageDecl
from flooreplay.decisions.types import (
    Fact,
    FactKind,
    FrozenModel,
    SourceProfile,
    Unit,
    decision_digest,
)

MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 10_000

PROFILES: dict[str, SourceProfile] = {
    "erp-fabric-stock": SourceProfile.ERP_FABRIC_STOCK,
    "sheet-trims-status": SourceProfile.SHEET_TRIMS_STATUS,
    "shift-capacity": SourceProfile.SHIFT_CAPACITY,
    "supplier-updates": SourceProfile.SUPPLIER_UPDATES,
    "order-requests": SourceProfile.ORDER_REQUESTS,
    "notes": SourceProfile.NOTES,
}


class ImportProblem(FrozenModel):
    row: int
    field: str
    code: str
    message: str


class NoteRecord(FrozenModel):
    note_id: str
    lot_hint: str | None = None
    text: str
    note_digest: str


class ImportPreview(FrozenModel):
    profile: SourceProfile
    filename: str
    raw_digest: str
    as_of: datetime
    facts: tuple[Fact, ...] = ()
    notes: tuple[NoteRecord, ...] = ()
    problems: tuple[ImportProblem, ...] = ()
    coverage: CoverageDecl | None = None
    status: Literal["READY", "BLOCKED"]
    preview_digest: str


class _RowProblem(ValueError):
    def __init__(self, field: str, code: str, message: str) -> None:
        super().__init__(message)
        self.field = field
        self.code = code


_MISSING = {"#N/A", "N/A", "-"}
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
_NAMED_DATE = re.compile(r"\d{2}-[A-Za-z]{3}-\d{4}\Z")
_MONTHS = {name: number for number, name in enumerate(("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), start=1)}
_DECIMAL = re.compile(r"\d+(?:\.\d+)?\Z")
_QUANTITY_FIELDS = {
    "qty", "allocation_qty", "on_hand", "inbound_qty", "available_minutes",
    "committed_minutes", "consumption_per_pc", "qc_qty",
}


def _problem(row: int, field: str, code: str, message: str) -> ImportProblem:
    return ImportProblem(row=row, field=field, code=code, message=message)


def _read_csv(raw: bytes) -> tuple[list[str], list[dict[str, str]]]:
    if not raw:
        raise _RowProblem("file", "empty_file", "The CSV file is empty.")
    if len(raw) > MAX_BYTES:
        raise _RowProblem("file", "file_too_large", f"The file exceeds {MAX_BYTES} bytes.")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise _RowProblem("file", "invalid_encoding", "The file must use UTF-8 encoding.") from exc
    try:
        reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
        headers = list(reader.fieldnames or [])
        if not headers or any(not header.strip() for header in headers):
            raise _RowProblem("header", "invalid_headers", "CSV headers must be nonblank.")
        if len(headers) != len(set(headers)):
            raise _RowProblem("header", "duplicate_headers", "CSV headers must be unique.")
        rows: list[dict[str, str]] = []
        for row_number, row in enumerate(reader, start=2):
            if None in row or any(value is None for value in row.values()):
                raise _RowProblem("row", "invalid_row_width", f"CSV row {row_number} has a different number of cells than its header.")
            rows.append({key: value for key, value in row.items() if key is not None and value is not None})
            if len(rows) > MAX_ROWS:
                raise _RowProblem("file", "too_many_rows", f"The file exceeds {MAX_ROWS} data rows.")
    except csv.Error as exc:
        raise _RowProblem("file", "invalid_csv", "The file is not valid CSV.") from exc
    return headers, rows


def _source_profile(profile: str) -> SourceProfile:
    try:
        return PROFILES[profile]
    except KeyError as exc:
        raise ValueError(f"Unsupported import profile: {profile}") from exc


def _value(row: dict[str, str], mapping: dict[str, str], field: str, *, required: bool = False) -> str | None:
    header = mapping.get(field)
    if header is None:
        if required:
            raise _RowProblem(field, "mapping_required", f"Map the required field {field!r} to a CSV column.")
        return None
    raw = row[header]
    value = unicodedata.normalize("NFC", raw.strip())
    if not value:
        if required:
            raise _RowProblem(field, "missing_value", f"Required field {field!r} is empty or marked missing.")
        return None
    if value.upper() in _MISSING:
        raise _RowProblem(field, "missing_value", f"Field {field!r} is marked missing.")
    return value


def _decimal(row: dict[str, str], mapping: dict[str, str], units: dict[str, str], field: str, *, required: bool = True) -> dict[str, Any] | None:
    text = _value(row, mapping, field, required=required)
    if text is None:
        return None
    if "," in text:
        raise _RowProblem(field, "thousands_separator", "Thousands separators are ambiguous; enter digits without grouping.")
    if not _DECIMAL.fullmatch(text):
        raise _RowProblem(field, "invalid_number", "Enter a non-negative decimal using digits and an optional decimal point.")
    unit_field = f"{field}_unit"
    if field == "consumption_per_pc":
        unit_field = "consumption_unit" if "consumption_unit" in mapping else unit_field
    unit_text = _value(row, mapping, unit_field)
    unit_text = unit_text or units.get(field) or _value(row, mapping, "unit")
    if unit_text is None:
        raise _RowProblem(field, "unit_required", f"Declare a unit for {field!r} in a mapped unit column or units argument.")
    try:
        unit = Unit(unit_text)
    except ValueError as exc:
        raise _RowProblem(field, "invalid_unit", f"Unsupported quantity unit {unit_text!r}.") from exc
    try:
        number = Decimal(text)
    except InvalidOperation as exc:  # guarded by regex; retained as a clear input problem
        raise _RowProblem(field, "invalid_number", "Enter a valid decimal number.") from exc
    return {"value": number, "unit": unit}


def _plain_number(row: dict[str, str], mapping: dict[str, str], field: str, *, required: bool = True) -> Decimal | None:
    text = _value(row, mapping, field, required=required)
    if text is None:
        return None
    if "," in text:
        raise _RowProblem(field, "thousands_separator", "Thousands separators are ambiguous; enter digits without grouping.")
    if not _DECIMAL.fullmatch(text):
        raise _RowProblem(field, "invalid_number", "Enter a non-negative decimal using digits and an optional decimal point.")
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise _RowProblem(field, "invalid_number", "Enter a valid decimal number.") from exc


def _date(row: dict[str, str], mapping: dict[str, str], field: str, *, required: bool = True) -> date | None:
    text = _value(row, mapping, field, required=required)
    if text is None:
        return None
    fmt = "%Y-%m-%d" if _ISO_DATE.fullmatch(text) else "%d-%b-%Y" if _NAMED_DATE.fullmatch(text) else None
    if fmt is None:
        raise _RowProblem(field, "invalid_date", "Use an unambiguous YYYY-MM-DD or DD-MMM-YYYY date.")
    try:
        if fmt == "%d-%b-%Y":
            day_text, month_text, year_text = text.split("-")
            month = _MONTHS.get(month_text.title())
            if month is None:
                raise ValueError("unknown English month")
            return date(int(year_text), month, int(day_text))
        return date.fromisoformat(text)
    except ValueError as exc:
        raise _RowProblem(field, "invalid_date", "The date is not a real calendar date.") from exc


def _json_value(row: dict[str, str], mapping: dict[str, str], field: str, *, required: bool = True) -> Any:
    text = _value(row, mapping, field, required=required)
    if text is None:
        return None
    try:
        return json.loads(text, parse_float=Decimal)
    except json.JSONDecodeError as exc:
        raise _RowProblem(field, "invalid_json", f"{field!r} must contain valid JSON.") from exc


def _json_objects(row: dict[str, str], mapping: dict[str, str], field: str, *, required: bool = True) -> list[dict[str, Any]]:
    value = _json_value(row, mapping, field, required=required)
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise _RowProblem(field, "invalid_array", f"{field!r} must be a JSON array of objects.")
    return value


def _boolean(row: dict[str, str], mapping: dict[str, str], field: str) -> bool:
    text = _value(row, mapping, field, required=True)
    if text is None:  # for static type narrowing
        raise _RowProblem(field, "missing_value", f"Required field {field!r} is empty.")
    if text.casefold() not in {"true", "false"}:
        raise _RowProblem(field, "invalid_boolean", "Use true or false.")
    return text.casefold() == "true"


def _text(row: dict[str, str], mapping: dict[str, str], field: str, *, required: bool = True) -> str | None:
    return _value(row, mapping, field, required=required)


def _fact(profile_name: str, profile: SourceProfile, raw_digest: str, row_number: int, suffix: str, kind: FactKind, key: str, payload: dict[str, Any], as_of: datetime) -> Fact:
    fact = Fact(
        id=f"{profile_name}:{raw_digest.removeprefix('sha256:')[:12]}:{row_number}{suffix}",
        kind=kind,
        entity_key=key,
        payload={**payload, "row_number": row_number},
        valid_from=as_of,
        valid_to=None,
        known_at=as_of,
        supersedes_id=None,
        source=profile,
        artifact_id=None,
    )
    return validate_fact(fact)


def _facts_for_row(profile_name: str, profile: SourceProfile, row: dict[str, str], mapping: dict[str, str], units: dict[str, str], raw_digest: str, row_number: int, as_of: datetime) -> tuple[list[Fact], list[NoteRecord]]:
    made: list[Fact] = []
    notes: list[NoteRecord] = []
    if profile_name == "erp-fabric-stock":
        lot_id = _text(row, mapping, "lot_id")
        qty = _decimal(row, mapping, units, "qty")
        payload = {"qty": qty, "fabric_quality": _text(row, mapping, "fabric_quality"), "colour": _text(row, mapping, "colour"), "gsm": _plain_number(row, mapping, "gsm", required=False), "width_m": _plain_number(row, mapping, "width_m", required=False)}
        made.append(_fact(profile_name, profile, raw_digest, row_number, "", FactKind.FABRIC_LOT, f"lot:{lot_id}", payload, as_of))
        allocation_order = _text(row, mapping, "allocation_order_id", required=False)
        allocation_qty = _decimal(row, mapping, units, "allocation_qty", required=False)
        if allocation_order is not None or allocation_qty is not None:
            if allocation_order is None or allocation_qty is None:
                raise _RowProblem("allocation", "incomplete_allocation", "Allocation needs both allocation_order_id and allocation_qty.")
            quality = _text(row, mapping, "allocation_quality", required=False) or payload["fabric_quality"]
            colour = _text(row, mapping, "allocation_colour", required=False) or payload["colour"]
            made.append(_fact(profile_name, profile, raw_digest, row_number, ":allocation", FactKind.FABRIC_ALLOCATION, f"alloc:{allocation_order}:{quality}:{colour}", {"qty": allocation_qty}, as_of))
    elif profile_name == "sheet-trims-status":
        style_id = _text(row, mapping, "style_id")
        trim_id = _text(row, mapping, "trim_id")
        on_hand = _decimal(row, mapping, units, "on_hand")
        inbound = _decimal(row, mapping, units, "inbound_qty", required=False)
        eta = _date(row, mapping, "eta", required=inbound is not None)
        made.append(_fact(profile_name, profile, raw_digest, row_number, "", FactKind.TRIM_STATUS, f"trim:{style_id}:{trim_id}", {"on_hand": on_hand, "inbound_qty": inbound, "eta": eta, "supplier": _text(row, mapping, "supplier")}, as_of))
    elif profile_name == "shift-capacity":
        line_id = _text(row, mapping, "line_id")
        work_date = _date(row, mapping, "date")
        if work_date is None:
            raise _RowProblem("date", "missing_value", "A work date is required.")
        available = _decimal(row, mapping, units, "available_minutes")
        efficiency = _plain_number(row, mapping, "efficiency_pct", required=False)
        made.append(_fact(profile_name, profile, raw_digest, row_number, "", FactKind.LINE_CAPACITY, f"line:{line_id}:{work_date.isoformat()}", {"available_minutes": available, "efficiency_pct": efficiency}, as_of))
        order_id = _text(row, mapping, "commitment_order_id", required=False)
        committed = _decimal(row, mapping, units, "committed_minutes", required=False)
        if order_id is not None or committed is not None:
            if order_id is None or committed is None:
                raise _RowProblem("commitment", "incomplete_commitment", "Commitment needs both commitment_order_id and committed_minutes.")
            made.append(_fact(profile_name, profile, raw_digest, row_number, ":commitment", FactKind.LINE_COMMITMENT, f"commit:{order_id}:{line_id}:{work_date.isoformat()}", {"committed_minutes": committed}, as_of))
    elif profile_name == "supplier-updates":
        ref = _text(row, mapping, "ref")
        qty = _decimal(row, mapping, units, "qty")
        inbound_payload = {"qty": qty, "fabric_quality": _text(row, mapping, "fabric_quality"), "colour": _text(row, mapping, "colour"), "eta": _date(row, mapping, "eta"), "supplier": _text(row, mapping, "supplier")}
        made.append(_fact(profile_name, profile, raw_digest, row_number, "", FactKind.FABRIC_INBOUND, f"inbound:{ref}", inbound_payload, as_of))
        qc_issue = _text(row, mapping, "qc_issue", required=False)
        qc_qty = _decimal(row, mapping, units, "qc_qty", required=False)
        if qc_issue is not None or qc_qty is not None:
            if qc_issue is None or qc_qty is None:
                raise _RowProblem("qc", "incomplete_qc_result", "An explicit QC result needs both qc_issue and qc_qty.")
            qc_payload = {"qty": qc_qty, "issue": qc_issue, "review_state": "checks_passed", "origin": "supplier_updates"}
            made.append(_fact(profile_name, profile, raw_digest, row_number, ":qc", FactKind.FABRIC_QC, f"lot:{_text(row, mapping, 'lot_id')}", qc_payload, as_of))
    elif profile_name == "order-requests":
        order_id = _text(row, mapping, "order_id")
        style_id = _text(row, mapping, "style_id")
        colours = _json_objects(row, mapping, "colours")
        for colour in colours:
            if isinstance(colour, dict):
                colour["colour"] = unicodedata.normalize("NFC", str(colour.get("colour", "")))
        order_payload = {"buyer": _text(row, mapping, "buyer"), "style_id": style_id, "colours": colours, "ship_date": _date(row, mapping, "ship_date"), "order_value_inr": _plain_number(row, mapping, "order_value_inr"), "partial_shipment_allowed": _boolean(row, mapping, "partial_shipment_allowed")}
        made.append(_fact(profile_name, profile, raw_digest, row_number, ":order", FactKind.ORDER_REQUEST, f"order:{order_id}", order_payload, as_of))
        consumption = _decimal(row, mapping, units, "consumption_per_pc")
        trims = _json_objects(row, mapping, "trims", required=False)
        bom_payload = {"fabric_quality": _text(row, mapping, "fabric_quality"), "consumption_per_pc": consumption, "trims": trims, "sam_minutes": _plain_number(row, mapping, "sam_minutes")}
        made.append(_fact(profile_name, profile, raw_digest, row_number, ":bom", FactKind.BOM, f"bom:{style_id}", bom_payload, as_of))
    else:
        note_text = _text(row, mapping, "text")
        note_id = _text(row, mapping, "note_id", required=False) or f"{raw_digest.removeprefix('sha256:')[:12]}:{row_number}"
        lot_hint = _text(row, mapping, "lot_hint", required=False)
        notes.append(NoteRecord(note_id=note_id, lot_hint=lot_hint, text=note_text or "", note_digest=decision_digest(note_text or "")))
    return made, notes


_REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "erp-fabric-stock": ("lot_id", "qty", "fabric_quality", "colour"),
    "sheet-trims-status": ("style_id", "trim_id", "on_hand", "supplier"),
    "shift-capacity": ("line_id", "date", "available_minutes"),
    "supplier-updates": ("ref", "qty", "fabric_quality", "colour", "eta", "supplier"),
    "order-requests": ("order_id", "buyer", "style_id", "colours", "ship_date", "order_value_inr", "partial_shipment_allowed", "fabric_quality", "consumption_per_pc", "sam_minutes"),
    "notes": ("text",),
}


def preview_import(raw: bytes, *, filename: str, profile: str, column_mapping: dict[str, str], as_of: datetime, timezone: str = "Asia/Kolkata", units: dict[str, str] | None = None, coverage_qualities: list[str] | None = None) -> ImportPreview:
    """Validate a mapped CSV and return immutable facts or blocking row problems.

    ``column_mapping`` is canonical-field → source-header. ``units`` is keyed by
    canonical quantity field and applies when no mapped unit column is present.
    An aware ``as_of`` is mandatory; ``timezone`` is validated and documents the
    user's declared local zone for dates entered elsewhere in the intake flow.
    """
    source = _source_profile(profile)
    raw_hash = "sha256:" + hashlib.sha256(raw).hexdigest()
    problems: list[ImportProblem] = []
    facts: list[Fact] = []
    notes: list[NoteRecord] = []
    coverage: CoverageDecl | None = None
    if not isinstance(as_of, datetime) or as_of.tzinfo is None or as_of.utcoffset() is None:
        problems.append(_problem(0, "as_of", "as_of_timezone_required", "Declare an as_of instant with an explicit timezone."))
    try:
        ZoneInfo(timezone)
    except ZoneInfoNotFoundError:
        problems.append(_problem(0, "timezone", "invalid_timezone", "Declare a valid IANA timezone."))
    if PurePath(filename).suffix.lower() != ".csv" or filename.startswith(("http://", "https://")):
        problems.append(_problem(0, "filename", "csv_required", "Choose a local CSV file."))
    try:
        headers, rows = _read_csv(raw)
    except _RowProblem as exc:
        problems.append(_problem(0, exc.field, exc.code, str(exc)))
        headers, rows = [], []
    mapping = dict(column_mapping or {})
    if not mapping:
        problems.append(_problem(0, "column_mapping", "mapping_required", "Map canonical fields to CSV headers explicitly."))
    allowed_unit_fields = {f"{field}_unit" for field in _QUANTITY_FIELDS} | {"consumption_unit"}
    unknown_fields = set(mapping) - set(_REQUIRED_FIELDS[profile]) - _QUANTITY_FIELDS - allowed_unit_fields - {
        "gsm", "width_m", "eta", "supplier", "inbound_qty", "efficiency_pct", "commitment_order_id", "allocation_order_id", "allocation_quality", "allocation_colour", "qc_issue", "qc_qty", "lot_id", "ref", "colours", "trims", "consumption_unit", "consumption_per_pc_unit", "order_id", "buyer", "style_id", "ship_date", "order_value_inr", "partial_shipment_allowed", "fabric_quality", "sam_minutes", "note_id", "lot_hint", "text", "quality", "colour", "unit", "date", "trim_id", "available_minutes", "committed_minutes", "on_hand", "allocation_qty", "qc_unit",
    }
    if unknown_fields:
        problems.append(_problem(0, "column_mapping", "unknown_mapping_field", f"Unknown canonical field(s): {', '.join(sorted(unknown_fields))}."))
    missing_headers = {header for header in mapping.values() if header not in headers}
    if missing_headers and headers:
        problems.append(_problem(0, "column_mapping", "mapped_header_missing", f"Mapped header(s) not found: {', '.join(sorted(missing_headers))}."))
    if len(set(mapping.values())) != len(mapping):
        problems.append(_problem(0, "column_mapping", "duplicate_source_column", "Each source column may map to only one canonical field."))
    missing_required_mappings = set(_REQUIRED_FIELDS[profile]) - set(mapping)
    for field in sorted(missing_required_mappings):
        problems.append(_problem(0, field, "mapping_required", f"Map the required field {field!r} to a CSV column."))
    units = dict(units or {})
    if profile == "erp-fabric-stock" and coverage_qualities is None:
        problems.append(_problem(0, "coverage_qualities", "coverage_required", "ERP stock previews require explicitly declared coverage qualities."))
    if profile != "erp-fabric-stock" and coverage_qualities is not None:
        problems.append(_problem(0, "coverage_qualities", "coverage_not_allowed", "Coverage qualities apply only to ERP fabric stock."))
    if as_of.tzinfo is not None and as_of.utcoffset() is not None and not problems:
        if profile == "erp-fabric-stock" and coverage_qualities is not None:
            coverage = CoverageDecl(profile=source, as_of=as_of, qualities=frozenset(coverage_qualities))
        for row_number, row in enumerate(rows, start=2):
            before = len(facts), len(notes)
            try:
                for field in _REQUIRED_FIELDS[profile]:
                    if field not in mapping:
                        continue
                    # Validate required cells eagerly; typed converters below perform parsing.
                    _value(row, mapping, field, required=True)
                row_facts, row_notes = _facts_for_row(profile, source, row, mapping, units, raw_hash, row_number, as_of)
                facts.extend(row_facts)
                notes.extend(row_notes)
            except _RowProblem as exc:
                del facts[before[0]:]
                del notes[before[1]:]
                problems.append(_problem(row_number, exc.field, exc.code, str(exc)))
            except (ValueError, TypeError, KeyError) as exc:
                del facts[before[0]:]
                del notes[before[1]:]
                problems.append(_problem(row_number, "row", "invalid_fact", str(exc)))
    facts.sort(key=lambda fact: fact.id)
    notes.sort(key=lambda note: note.note_id)
    status: Literal["READY", "BLOCKED"] = "BLOCKED" if problems else "READY"
    digest_facts = [{**fact.model_dump(mode="python"), "known_at": None} for fact in facts]
    digest_as_of: datetime | str = as_of
    if isinstance(as_of, datetime) and (as_of.tzinfo is None or as_of.utcoffset() is None):
        digest_as_of = as_of.isoformat()
    preview_digest = decision_digest({
        "profile": source,
        "filename": filename,
        "raw_digest": raw_hash,
        "as_of": digest_as_of,
        "timezone": timezone,
        "column_mapping": mapping,
        "units": units,
        "coverage_qualities": coverage_qualities,
        "facts": digest_facts,
        "notes": notes,
        "problems": problems,
        "status": status,
    })
    return ImportPreview(profile=source, filename=filename, raw_digest=raw_hash, as_of=as_of, facts=tuple(facts), notes=tuple(notes), problems=tuple(problems), coverage=coverage, status=status, preview_digest=preview_digest)
