"""CSV import: fixed source profiles, row-level diagnostics, publication.

The import flow is: select a documented source profile, submit CSV text,
receive a normalized preview with per-row issues and a content-addressed
digest, then publish that exact digest as an immutable snapshot. Publication
is all-or-nothing: a malformed row can never silently disappear and make an
incomplete export look complete.

Missing data keeps its meaning: a blank attendance cell normalizes to
UNKNOWN (never absent), and unknown skill stays unknown (never level zero).
Raw cells are retained on every normalized row for inspection.
"""

from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from .domain.hashing import digest
from .domain.types import (
    AttendanceRecord,
    AttendanceStatus,
    Catalog,
    SkillRecord,
    Snapshot,
    SnapshotKind,
)
from .fixtures import CATALOG

FACTORY_TZ = ZoneInfo("Asia/Kolkata")
MAX_BYTES = 1024 * 1024
MAX_ROWS = 5000


class ImportStructuralError(ValueError):
    """File-level problems that prevent any preview. HTTP 422."""

    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


class Profile:
    def __init__(
        self,
        id: str,
        kind: SnapshotKind,
        required_headers: tuple[str, ...],
        natural_key: tuple[str, ...],
        source_system: str,
        default_scope: str,
    ) -> None:
        self.id = id
        self.kind = kind
        self.required_headers = required_headers
        self.natural_key = natural_key
        self.source_system = source_system
        self.default_scope = default_scope


PROFILES: dict[str, Profile] = {
    p.id: p
    for p in (
        Profile(
            id="attendance-v1",
            kind=SnapshotKind.ATTENDANCE,
            required_headers=("operator_id", "status", "observed_at"),
            natural_key=("operator_id",),
            source_system="attendance-export",
            default_scope="roster:declared-by-importer; single point in time",
        ),
        Profile(
            id="skills-v1",
            kind=SnapshotKind.SKILLS,
            required_headers=("operator_id", "operation_id", "level", "assessed_at"),
            natural_key=("operator_id", "operation_id"),
            source_system="skill-matrix-export",
            default_scope="roster:declared-by-importer; operations:as-listed",
        ),
    )
}

ATTENDANCE_STATUS_MAP: dict[str, AttendanceStatus] = {
    "P": AttendanceStatus.PRESENT,
    "PRESENT": AttendanceStatus.PRESENT,
    "1": AttendanceStatus.PRESENT,
    "A": AttendanceStatus.ABSENT,
    "ABSENT": AttendanceStatus.ABSENT,
    "0": AttendanceStatus.ABSENT,
    "": AttendanceStatus.UNKNOWN,
    "U": AttendanceStatus.UNKNOWN,
    "UNKNOWN": AttendanceStatus.UNKNOWN,
}


@dataclass(frozen=True)
class RowIssue:
    row: int  # 1-based data row number (after the header)
    column: str
    code: str  # MISSING_REQUIRED_CELL | UNSUPPORTED_VALUE | INVALID_TIMESTAMP | UNKNOWN_OPERATOR | UNKNOWN_OPERATION | DUPLICATE_NATURAL_KEY | FORMULA_LIKE_CELL
    severity: str  # BLOCKING | WARNING
    raw_value: str
    message: str


@dataclass(frozen=True)
class NormalizedRow:
    row: int
    raw: dict[str, str]  # original cells, preserved verbatim for inspection
    normalized: dict[str, str]
    normalizations: tuple[str, ...] = ()
    source_ref: str = ""


@dataclass(frozen=True)
class ImportPreview:
    profile_id: str
    snapshot_kind: str
    headers: tuple[str, ...]
    ignored_columns: tuple[str, ...]
    rows: tuple[NormalizedRow, ...]
    issues: tuple[RowIssue, ...]
    blocking_count: int
    warning_count: int
    raw_digest: str
    preview_digest: str
    declared_evidence_at: str
    scope: str
    coverage_complete: bool


@dataclass
class _ParsedCsv:
    headers: list[str]
    rows: list[dict[str, str]] = field(default_factory=list)


def _parse_csv(text: str) -> _ParsedCsv:
    reader = csv.DictReader(io.StringIO(text))
    headers = reader.fieldnames or []
    rows: list[dict[str, str]] = []
    for raw in reader:
        row = {
            (key or ""): ("" if value is None else value) for key, value in raw.items()
        }
        rows.append(row)
    return _ParsedCsv(headers=list(headers), rows=rows)


def _check_structure(profile: Profile, text: str) -> _ParsedCsv:
    if not text or not text.strip("\ufeff\r\n \t"):
        raise ImportStructuralError("EMPTY_FILE", "The submitted file has no content.")
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise ImportStructuralError(
            "TOO_LARGE", f"CSV exceeds the {MAX_BYTES // 1024} KiB limit.", {"max_bytes": MAX_BYTES}
        )
    parsed = _parse_csv(text.lstrip("\ufeff"))
    if not parsed.headers or all(not h.strip() for h in parsed.headers):
        raise ImportStructuralError("BAD_HEADERS", "The file has no header row.")
    missing = [h for h in profile.required_headers if h not in parsed.headers]
    if missing:
        raise ImportStructuralError(
            "BAD_HEADERS",
            f"Required column(s) missing for profile {profile.id}: {', '.join(missing)}.",
            {"required": list(profile.required_headers), "missing": missing},
        )
    if len(parsed.rows) > MAX_ROWS:
        raise ImportStructuralError(
            "TOO_MANY_ROWS", f"CSV exceeds the {MAX_ROWS} row limit.", {"max_rows": MAX_ROWS}
        )
    if not parsed.rows:
        raise ImportStructuralError(
            "BAD_HEADERS", "The file has a header row but no data rows."
        )
    return parsed


def _parse_timestamp(raw_value: str, row_number: int, normalizations: list[str]) -> datetime | None:
    value = raw_value.strip()
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        # Documented profile rule: naive timestamps are factory-local time.
        parsed = parsed.replace(tzinfo=FACTORY_TZ)
        normalizations.append(f"naive timestamp '{value}' interpreted as Asia/Kolkata")
    return parsed


def _formula_like(value: str) -> bool:
    return value[:1] in ("=", "+", "@") or value.startswith("\t=")


def _common_row_issues(
    row: dict[str, str],
    row_number: int,
    catalog: Catalog,
    issues: list[RowIssue],
) -> None:
    operator_id = row.get("operator_id", "").strip()
    if not operator_id:
        issues.append(
            RowIssue(row_number, "operator_id", "MISSING_REQUIRED_CELL", "BLOCKING", "",
                     "operator_id is required.")
        )
    elif operator_id not in {op.id for op in catalog.operators}:
        issues.append(
            RowIssue(row_number, "operator_id", "UNKNOWN_OPERATOR", "BLOCKING", operator_id,
                     f"Operator {operator_id} is not in the pinned catalog.")
        )
    operation_id = row.get("operation_id", "").strip()
    if operation_id and operation_id not in {op.id for op in catalog.operations}:
        issues.append(
            RowIssue(row_number, "operation_id", "UNKNOWN_OPERATION", "BLOCKING", operation_id,
                     f"Operation {operation_id} is not in the pinned catalog.")
        )
    for column, value in row.items():
        if value and _formula_like(value):
            issues.append(
                RowIssue(row_number, column, "FORMULA_LIKE_CELL", "WARNING", value[:40],
                         "Cell begins with a spreadsheet-formula character; it is stored and "
                         "rendered as text only.")
            )


def _duplicate_issues(
    profile: Profile, parsed: _ParsedCsv, issues: list[RowIssue]
) -> None:
    seen: dict[tuple[str, ...], int] = {}
    for index, row in enumerate(parsed.rows, start=1):
        key = tuple(row.get(c, "").strip() for c in profile.natural_key)
        if all(k for k in key):
            if key in seen:
                issues.append(
                    RowIssue(index, profile.natural_key[0], "DUPLICATE_NATURAL_KEY", "BLOCKING",
                             ",".join(key),
                             f"Duplicate {profile.natural_key} {','.join(key)}; first seen on "
                             f"row {seen[key]}.")
                )
            else:
                seen[key] = index


def preview_import(
    profile_id: str,
    text: str,
    declared_evidence_at: str,
    coverage_complete: bool,
    scope: str | None = None,
    catalog: Catalog = CATALOG,
) -> ImportPreview:
    profile = PROFILES.get(profile_id)
    if profile is None:
        raise ImportStructuralError(
            "UNKNOWN_PROFILE", f"Unknown source profile: {profile_id}.",
            {"supported": sorted(PROFILES)},
        )
    if not declared_evidence_at:
        raise ImportStructuralError(
            "MISSING_META", "declared_evidence_at is required: state when the source says this "
            "data was true. It is never taken from the upload clock."
        )
    try:
        declared_at = datetime.fromisoformat(declared_evidence_at)
        if declared_at.tzinfo is None:
            raise ValueError("naive")
    except ValueError:
        raise ImportStructuralError(
            "INVALID_META", "declared_evidence_at must be an ISO timestamp with an explicit "
            "UTC offset (for example 2026-09-22T07:55:00+05:30)."
        ) from None

    parsed = _check_structure(profile, text)
    ignored = tuple(h for h in parsed.headers if h not in profile.required_headers)

    issues: list[RowIssue] = []
    normalized_rows: list[NormalizedRow] = []
    known_operators = {op.id for op in catalog.operators}

    _duplicate_issues(profile, parsed, issues)

    for index, row in enumerate(parsed.rows, start=1):
        normalizations: list[str] = []
        _common_row_issues(row, index, catalog, issues)

        normalized: dict[str, str] = {}
        if profile.kind is SnapshotKind.ATTENDANCE:
            raw_status = row.get("status", "")
            status_key = raw_status.strip().upper()
            status = ATTENDANCE_STATUS_MAP.get(status_key)
            if status is None:
                issues.append(
                    RowIssue(index, "status", "UNSUPPORTED_VALUE", "BLOCKING", raw_status,
                             f"Status '{raw_status}' is not in the documented set "
                             f"(P, A, PRESENT, ABSENT, U, UNKNOWN, 1, 0, blank).")
                )
            else:
                if raw_status.strip() == "":
                    normalizations.append("blank status -> UNKNOWN; never read as absent")
                elif status_key not in ("PRESENT", "ABSENT", "UNKNOWN"):
                    normalizations.append(f"status '{raw_status.strip()}' -> {status.value}")
                normalized["status"] = status.value
            observed = _parse_timestamp(row.get("observed_at", ""), index, normalizations)
            if observed is None:
                issues.append(
                    RowIssue(index, "observed_at", "INVALID_TIMESTAMP", "BLOCKING",
                             row.get("observed_at", ""),
                             "observed_at must be an ISO timestamp; naive values are "
                             "interpreted as Asia/Kolkata.")
                )
            else:
                normalized["observed_at"] = observed.isoformat()
            normalized["operator_id"] = row.get("operator_id", "").strip()
        else:  # SKILLS
            level_raw = row.get("level", "").strip()
            try:
                level = int(level_raw)
                if not 1 <= level <= 4:
                    raise ValueError
            except ValueError:
                issues.append(
                    RowIssue(index, "level", "UNSUPPORTED_VALUE", "BLOCKING", level_raw,
                             f"Level '{level_raw}' is not an integer between 1 and 4.")
                )
            else:
                normalized["level"] = str(level)
            assessed = _parse_timestamp(row.get("assessed_at", ""), index, normalizations)
            if assessed is None:
                issues.append(
                    RowIssue(index, "assessed_at", "INVALID_TIMESTAMP", "BLOCKING",
                             row.get("assessed_at", ""),
                             "assessed_at must be an ISO timestamp; naive values are "
                             "interpreted as Asia/Kolkata.")
                )
            else:
                normalized["assessed_at"] = assessed.isoformat()
            normalized["operator_id"] = row.get("operator_id", "").strip()
            normalized["operation_id"] = row.get("operation_id", "").strip()

        normalized_rows.append(
            NormalizedRow(
                row=index,
                raw=dict(row),
                normalized=normalized,
                normalizations=tuple(normalizations),
                source_ref=f"row:{index}",
            )
        )

    # Attendance completeness against the roster is a warning here; the
    # replay gate still refuses to conclude 'absent' from missing rows.
    if (
        profile.kind is SnapshotKind.ATTENDANCE
        and coverage_complete
    ):
        covered = {r.normalized.get("operator_id") for r in normalized_rows}
        gap = sorted(known_operators - covered)
        if gap:
            issues.append(
                RowIssue(0, "", "ROSTER_GAP", "WARNING", f"{len(gap)} operators",
                         f"Coverage is declared complete but {len(gap)} roster operator(s) have "
                         f"no row: {', '.join(gap[:8])}{'...' if len(gap) > 8 else ''}. "
                         f"The published snapshot will block replays until corrected.")
            )

    raw_digest = "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()
    preview_digest = digest(
        {
            "profile_id": profile.id,
            "raw_digest": raw_digest,
            "rows": [
                {"row": r.row, "raw": r.raw, "normalized": r.normalized,
                 "normalizations": list(r.normalizations)}
                for r in normalized_rows
            ],
            "issues": [issue.__dict__ for issue in issues],
            "ignored_columns": list(ignored),
            "declared_evidence_at": declared_at.isoformat(),
            "coverage_complete": coverage_complete,
            "scope": scope or profile.default_scope,
        }
    )

    return ImportPreview(
        profile_id=profile.id,
        snapshot_kind=profile.kind.value,
        headers=tuple(parsed.headers),
        ignored_columns=ignored,
        rows=tuple(normalized_rows),
        issues=tuple(issues),
        blocking_count=sum(1 for i in issues if i.severity == "BLOCKING"),
        warning_count=sum(1 for i in issues if i.severity == "WARNING"),
        raw_digest=raw_digest,
        preview_digest=preview_digest,
        declared_evidence_at=declared_at.isoformat(),
        scope=scope or profile.default_scope,
        coverage_complete=coverage_complete,
    )


def build_snapshot(preview: ImportPreview) -> Snapshot:
    """Construct the immutable domain snapshot a publish will persist."""
    if preview.blocking_count > 0:
        raise ImportStructuralError(
            "BLOCKING_ISSUES",
            f"Preview has {preview.blocking_count} blocking issue(s); publication is "
            "all-or-nothing.",
        )
    profile = PROFILES[preview.profile_id]
    snapshot_id = f"SNAP-IMP-{profile.kind.value[:4]}-{preview.preview_digest[-8:].upper()}"
    declared_at = datetime.fromisoformat(preview.declared_evidence_at)

    if profile.kind is SnapshotKind.ATTENDANCE:
        attendance_records: tuple[AttendanceRecord, ...] = tuple(
            AttendanceRecord(
                operator_id=row.normalized["operator_id"],
                status=AttendanceStatus(row.normalized["status"]),
                observed_at=datetime.fromisoformat(row.normalized["observed_at"]),
                source_ref=row.source_ref,
            )
            for row in preview.rows
        )
        return Snapshot(
            id=snapshot_id,
            kind=profile.kind,
            source_system=profile.source_system,
            scope=preview.scope,
            declared_evidence_at=declared_at,
            coverage_complete=preview.coverage_complete,
            content_digest=preview.preview_digest,
            attendance=attendance_records,
        )

    skill_records: tuple[SkillRecord, ...] = tuple(
        SkillRecord(
            operator_id=row.normalized["operator_id"],
            operation_id=row.normalized["operation_id"],
            level=int(row.normalized["level"]),
            assessed_at=datetime.fromisoformat(row.normalized["assessed_at"]),
            source_ref=row.source_ref,
        )
        for row in preview.rows
    )
    return Snapshot(
        id=snapshot_id,
        kind=profile.kind,
        source_system=profile.source_system,
        scope=preview.scope,
        declared_evidence_at=declared_at,
        coverage_complete=preview.coverage_complete,
        content_digest=preview.preview_digest,
        skills=skill_records,
    )
