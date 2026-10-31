"""Offline measurement for the comparative pilot in docs/comparative-pilot.md.

The input is one CSV with one row per method attempt. A baseline row and a
FloorReplay row that share a pair_id form one pair, measured on comparable
cases of the same participant, cohort and complexity. Invalid input is refused
with line-numbered problems and no summary is written, so blank or malformed
data is never reported as a result.

Blank cells mean "not recorded". They are left out of denominators and never
counted as zero. The notes column is kept for the practitioner's own record and
is not summarised.

The summary describes the observed sample only. It makes no claim about
manufacturing benefit, productivity or return on investment.

Usage:
    uv run python -m flooreplay.pilot_measurement INPUT.csv --output OUTPUT.json
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import re
import statistics
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

COLUMNS: tuple[str, ...] = (
    "pair_id",
    "cohort",
    "participant_id",
    "case_id",
    "case_complexity",
    "method",
    "method_order",
    "release",
    "outcome",
    "completion_seconds",
    "first_missing_evidence_seconds",
    "report_seconds",
    "evidence_expected",
    "evidence_found",
    "unsupported_conclusions",
    "conclusions_assessed",
    "errors",
    "source_omissions",
    "clarification_rounds",
    "assistance_count",
    "reviewer_confidence",
    "usefulness_rating",
    "notes",
)
REQUIRED = ("pair_id", "cohort", "participant_id", "case_id", "case_complexity", "method", "method_order", "outcome")
COHORTS = ("synthetic", "practitioner")
METHODS = ("baseline", "flooreplay")
OUTCOMES = ("success", "failed", "timed_out")
COMPLEXITIES = ("low", "medium", "high")
METHOD_ORDERS = ("baseline_first", "flooreplay_first")
PAIR_STATUSES = ("both_success", "baseline_only_success", "flooreplay_only_success", "neither_success")
DISCLAIMER = (
    "Descriptive summary of a convenience sample. Times and counts describe the observed cases only. "
    "This is not evidence of manufacturing benefit, productivity or return on investment."
)

_WHOLE = re.compile(r"[0-9]+")
_SECONDS = re.compile(r"(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)")


@dataclass(frozen=True)
class Record:
    line: int
    pair_id: str
    cohort: str
    participant_id: str
    case_id: str
    case_complexity: str
    method: str
    method_order: str
    release: str
    outcome: str
    completion_seconds: float | None
    first_missing_evidence_seconds: float | None
    report_seconds: float | None
    evidence_expected: int | None
    evidence_found: int | None
    unsupported_conclusions: int | None
    conclusions_assessed: int | None
    errors: int | None
    source_omissions: int | None
    clarification_rounds: int | None
    assistance_count: int | None
    reviewer_confidence: int | None
    usefulness_rating: int | None


@dataclass(frozen=True)
class Pair:
    pair_id: str
    baseline: Record
    flooreplay: Record


def _whole(name: str, text: str, line: int, problems: list[str], *, low: int = 0, high: int | None = None) -> int | None:
    if not text:
        return None
    if not _WHOLE.fullmatch(text):
        problems.append(f"line {line}: {name} must be a whole number, got {text!r}")
        return None
    value = int(text)
    if value < low or (high is not None and value > high):
        problems.append(f"line {line}: {name} must be a whole number from {low} to {high}, got {text!r}")
        return None
    return value


def _seconds(name: str, text: str, line: int, problems: list[str]) -> float | None:
    if not text:
        return None
    try:
        value = float(text) if _SECONDS.fullmatch(text) else math.nan
    except ValueError:
        value = math.nan
    if not math.isfinite(value) or value < 0:
        problems.append(f"line {line}: {name} must be a non-negative number, got {text!r}")
        return None
    return value


def _choice(name: str, value: str, allowed: tuple[str, ...], line: int, problems: list[str]) -> None:
    if value and value not in allowed:
        problems.append(f"line {line}: {name} must be one of {', '.join(allowed)}, got {value!r}")


def _record(cells: dict[str, str], line: int, problems: list[str]) -> Record:
    for name in REQUIRED:
        if not cells[name]:
            problems.append(f"line {line}: {name} is required")
    _choice("cohort", cells["cohort"], COHORTS, line, problems)
    _choice("case_complexity", cells["case_complexity"], COMPLEXITIES, line, problems)
    _choice("method", cells["method"], METHODS, line, problems)
    _choice("method_order", cells["method_order"], METHOD_ORDERS, line, problems)
    _choice("outcome", cells["outcome"], OUTCOMES, line, problems)

    release = cells["release"]
    if cells["method"] == "flooreplay" and not release:
        problems.append(f"line {line}: release is required for flooreplay rows")
    if cells["method"] == "baseline" and release:
        problems.append(f"line {line}: release must be blank for baseline rows")

    completion = _seconds("completion_seconds", cells["completion_seconds"], line, problems)
    if cells["outcome"] == "success" and not cells["completion_seconds"]:
        problems.append(f"line {line}: completion_seconds is required when outcome is success")
    if cells["outcome"] in {"failed", "timed_out"} and cells["completion_seconds"]:
        problems.append(f"line {line}: completion_seconds must be blank when outcome is {cells['outcome']}")
    first = _seconds("first_missing_evidence_seconds", cells["first_missing_evidence_seconds"], line, problems)
    if first is not None and completion is not None and first > completion:
        problems.append(f"line {line}: first_missing_evidence_seconds is after completion_seconds")

    expected = _whole("evidence_expected", cells["evidence_expected"], line, problems)
    found = _whole("evidence_found", cells["evidence_found"], line, problems)
    if expected is not None and found is not None and found > expected:
        problems.append(f"line {line}: evidence_found exceeds evidence_expected")
    assessed = _whole("conclusions_assessed", cells["conclusions_assessed"], line, problems)
    unsupported = _whole("unsupported_conclusions", cells["unsupported_conclusions"], line, problems)
    if assessed is not None and unsupported is not None and unsupported > assessed:
        problems.append(f"line {line}: unsupported_conclusions exceeds conclusions_assessed")

    return Record(
        line=line,
        pair_id=cells["pair_id"],
        cohort=cells["cohort"],
        participant_id=cells["participant_id"],
        case_id=cells["case_id"],
        case_complexity=cells["case_complexity"],
        method=cells["method"],
        method_order=cells["method_order"],
        release=release,
        outcome=cells["outcome"],
        completion_seconds=completion,
        first_missing_evidence_seconds=first,
        report_seconds=_seconds("report_seconds", cells["report_seconds"], line, problems),
        evidence_expected=expected,
        evidence_found=found,
        unsupported_conclusions=unsupported,
        conclusions_assessed=assessed,
        errors=_whole("errors", cells["errors"], line, problems),
        source_omissions=_whole("source_omissions", cells["source_omissions"], line, problems),
        clarification_rounds=_whole("clarification_rounds", cells["clarification_rounds"], line, problems),
        assistance_count=_whole("assistance_count", cells["assistance_count"], line, problems),
        reviewer_confidence=_whole("reviewer_confidence", cells["reviewer_confidence"], line, problems, low=1, high=5),
        usefulness_rating=_whole("usefulness_rating", cells["usefulness_rating"], line, problems, low=1, high=5),
    )


def _read_records(text: str, problems: list[str]) -> list[Record]:
    try:
        reader = csv.DictReader(io.StringIO(text))
        fieldnames = list(reader.fieldnames or [])
        missing = [column for column in COLUMNS if column not in fieldnames]
        unknown = [column for column in fieldnames if column not in COLUMNS]
        if missing:
            problems.append(f"header is missing column(s): {', '.join(missing)}")
        if unknown:
            problems.append(f"header has unknown column(s): {', '.join(unknown)}")
        if len(set(fieldnames)) != len(fieldnames):
            problems.append("header repeats a column name")
        if problems:
            return []

        records: list[Record] = []
        for row in reader:
            line = reader.line_num
            if None in row or any(row.get(column) is None for column in COLUMNS):
                problems.append(f"line {line}: row does not have the {len(COLUMNS)} columns in the header")
                continue
            cells = {column: str(row[column]).strip() for column in COLUMNS}
            records.append(_record(cells, line, problems))
        return records
    except csv.Error as error:
        problems.append(f"unreadable CSV: {error}")
        return []


def _pair_rows(records: list[Record], problems: list[str]) -> list[Pair]:
    rows_by_pair: defaultdict[str, list[Record]] = defaultdict(list)
    for record in records:
        rows_by_pair[record.pair_id].append(record)

    pairs: list[Pair] = []
    for pair_id, rows in rows_by_pair.items():
        by_method = {row.method: row for row in rows}
        if len(rows) != 2 or set(by_method) != set(METHODS):
            lines = ", ".join(str(row.line) for row in rows)
            problems.append(
                f"pair {pair_id!r} needs exactly one baseline and one flooreplay row; "
                f"found {len(rows)} row(s) (lines {lines})"
            )
            continue
        baseline, flooreplay = by_method["baseline"], by_method["flooreplay"]
        for name in ("cohort", "participant_id", "case_complexity", "method_order"):
            if getattr(baseline, name) != getattr(flooreplay, name):
                problems.append(
                    f"pair {pair_id!r}: {name} differs between baseline and flooreplay rows "
                    f"(lines {baseline.line}, {flooreplay.line})"
                )
        pairs.append(Pair(pair_id=pair_id, baseline=baseline, flooreplay=flooreplay))
    return pairs


def _cross_row_checks(records: list[Record], problems: list[str]) -> None:
    first_line: dict[tuple[str, str, str, str], int] = {}
    for record in records:
        key = (record.cohort, record.participant_id, record.method, record.case_id)
        if record.case_id and key in first_line:
            problems.append(
                f"case_id {record.case_id!r} is measured more than once for participant {record.participant_id!r} and method {record.method} "
                f"(lines {first_line[key]}, {record.line})"
            )
        else:
            first_line.setdefault(key, record.line)

    releases = sorted({record.release for record in records if record.method == "flooreplay" and record.release})
    if len(releases) > 1:
        problems.append(f"flooreplay rows name more than one release ({', '.join(releases)}); split the pilot by release")


def load_pairs(text: str) -> tuple[list[Pair], list[str]]:
    """Parse and validate pilot CSV text. Summarise only when the problem list is empty."""
    problems: list[str] = []
    records = _read_records(text, problems)
    if not records and not problems:
        problems.append("no records: nothing to measure")
    pairs = _pair_rows(records, problems)
    _cross_row_checks(records, problems)
    return pairs, problems


def _present[T: (int, float)](values: Iterable[T | None]) -> list[T]:
    return [value for value in values if value is not None]


def _both_present(rows: list[Record], first: str, second: str) -> list[tuple[Any, Any]]:
    values = [(getattr(row, first), getattr(row, second)) for row in rows]
    return [(a, b) for a, b in values if a is not None and b is not None]


def _stat(values: Sequence[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0, "median": None, "min": None, "max": None}
    return {"n": len(values), "median": statistics.median(values), "min": min(values), "max": max(values)}


def _count_stat(values: Sequence[int]) -> dict[str, Any]:
    return {**_stat(values), "total": sum(values)}


def _ratio(numerator: int, denominator: int) -> dict[str, Any]:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "rate": numerator / denominator if denominator else None,
    }


def _method_summary(rows: list[Record]) -> dict[str, Any]:
    outcomes = Counter(row.outcome for row in rows)
    evidence = _both_present(rows, "evidence_found", "evidence_expected")
    conclusions = _both_present(rows, "unsupported_conclusions", "conclusions_assessed")
    return {
        "records": len(rows),
        "outcomes": {outcome: outcomes[outcome] for outcome in OUTCOMES},
        "success_rate": _ratio(outcomes["success"], len(rows)),
        "completion_seconds": _stat(_present(row.completion_seconds for row in rows if row.outcome == "success")),
        "first_missing_evidence_seconds": _stat(_present(row.first_missing_evidence_seconds for row in rows)),
        "report_seconds": _stat(_present(row.report_seconds for row in rows)),
        "evidence_recall": {
            **_ratio(sum(found for found, _ in evidence), sum(expected for _, expected in evidence)),
            "rows": len(evidence),
        },
        "unsupported_conclusion_rate": {
            **_ratio(sum(unsupported for unsupported, _ in conclusions), sum(assessed for _, assessed in conclusions)),
            "rows": len(conclusions),
        },
        "errors": _count_stat(_present(row.errors for row in rows)),
        "source_omissions": _count_stat(_present(row.source_omissions for row in rows)),
        "clarification_rounds": _count_stat(_present(row.clarification_rounds for row in rows)),
        "assistance_count": _count_stat(_present(row.assistance_count for row in rows)),
        "reviewer_confidence": _stat(_present(row.reviewer_confidence for row in rows)),
        "usefulness_rating": _stat(_present(row.usefulness_rating for row in rows)),
    }


def _pair_status(pair: Pair) -> str:
    baseline_ok = pair.baseline.outcome == "success"
    flooreplay_ok = pair.flooreplay.outcome == "success"
    if baseline_ok and flooreplay_ok:
        return "both_success"
    if baseline_ok:
        return "baseline_only_success"
    if flooreplay_ok:
        return "flooreplay_only_success"
    return "neither_success"


def _completed(pair: Pair) -> tuple[float, float] | None:
    """Completion times for a comparable completed pair; None otherwise."""
    baseline, flooreplay = pair.baseline, pair.flooreplay
    if baseline.outcome != "success" or flooreplay.outcome != "success":
        return None
    if baseline.completion_seconds is None or flooreplay.completion_seconds is None:
        return None
    return baseline.completion_seconds, flooreplay.completion_seconds


def _paired_summary(pairs: list[Pair]) -> dict[str, Any]:
    statuses = Counter(_pair_status(pair) for pair in pairs)
    timed = [times for times in (_completed(pair) for pair in pairs) if times is not None]
    differences = [flooreplay - baseline for baseline, flooreplay in timed]
    repeated = sum(pair.baseline.case_id == pair.flooreplay.case_id for pair in pairs)
    return {
        "pairs": len(pairs),
        "outcome_pairs": {status: statuses[status] for status in PAIR_STATUSES},
        "comparable_pairs": len(timed),
        "comparable_definition": "both rows succeeded and recorded completion_seconds",
        "same_case_pairs": repeated,
        "learning_effect_warning": (
            "The same case was repeated across methods. Timing differences may reflect prior exposure; method order does not remove that effect."
            if repeated else None
        ),
        "method_order_pairs": {order: sum(pair.baseline.method_order == order for pair in pairs) for order in METHOD_ORDERS},
        "baseline_completion_seconds": _stat([baseline for baseline, _ in timed]),
        "flooreplay_completion_seconds": _stat([flooreplay for _, flooreplay in timed]),
        "per_pair_difference_seconds_flooreplay_minus_baseline": _stat(differences),
        "flooreplay_slower_pairs": sum(difference > 0 for difference in differences),
        "flooreplay_faster_pairs": sum(difference < 0 for difference in differences),
        "same_time_pairs": sum(difference == 0 for difference in differences),
    }


def _cohort_summary(cohort: str, pairs: list[Pair]) -> dict[str, Any]:
    cohort_pairs = [pair for pair in pairs if pair.baseline.cohort == cohort]
    return {
        "pairs": len(cohort_pairs),
        "participants": len({pair.baseline.participant_id for pair in cohort_pairs}),
        "methods": {
            "baseline": _method_summary([pair.baseline for pair in cohort_pairs]),
            "flooreplay": _method_summary([pair.flooreplay for pair in cohort_pairs]),
        },
        "paired": _paired_summary(cohort_pairs),
    }


def _pair_detail(pair: Pair) -> dict[str, Any]:
    completed = _completed(pair)
    return {
        "pair_id": pair.pair_id,
        "cohort": pair.baseline.cohort,
        "participant_id": pair.baseline.participant_id,
        "case_complexity": pair.baseline.case_complexity,
        "method_order": pair.baseline.method_order,
        "same_case_repeated": pair.baseline.case_id == pair.flooreplay.case_id,
        "baseline": {"case_id": pair.baseline.case_id, "outcome": pair.baseline.outcome},
        "flooreplay": {"case_id": pair.flooreplay.case_id, "outcome": pair.flooreplay.outcome},
        "difference_seconds_flooreplay_minus_baseline": None if completed is None else completed[1] - completed[0],
    }


def summarize(pairs: list[Pair]) -> dict[str, Any]:
    """Summarise validated pairs. Call only after load_pairs reports no problems."""
    releases = sorted({pair.flooreplay.release for pair in pairs})
    return {
        "schema_version": 1,
        "disclaimer": DISCLAIMER,
        "release": releases[0] if len(releases) == 1 else None,
        "records": 2 * len(pairs),
        "pairs": len(pairs),
        "cohorts": {cohort: _cohort_summary(cohort, pairs) for cohort in COHORTS},
        "pair_details": [_pair_detail(pair) for pair in pairs],
    }


def measure_csv(text: str) -> tuple[dict[str, Any] | None, list[str]]:
    pairs, problems = load_pairs(text)
    if problems:
        return None, problems
    return summarize(pairs), []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input", type=Path, help="pilot CSV with one row per method attempt")
    parser.add_argument("--output", type=Path, required=True, help="JSON summary to write")
    args = parser.parse_args(argv)

    try:
        text = args.input.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as error:
        print(f"Cannot read {args.input}: {error}", file=sys.stderr)
        return 1

    summary, problems = measure_csv(text)
    if summary is None:
        for problem in problems:
            print(problem, file=sys.stderr)
        print(f"Refused: {len(problems)} problem(s); no output written.", file=sys.stderr)
        return 1

    if args.output.resolve() == args.input.resolve():
        print("Refused: output must differ from the source CSV; no output written.", file=sys.stderr)
        return 1
    try:
        args.output.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    except OSError as error:
        print(f"Cannot write {args.output}: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
