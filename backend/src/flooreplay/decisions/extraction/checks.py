"""Deterministic per-field checks (`checks-v1`). No model confidence is ever consulted.

A field that fails any applicable check sends the whole signal to review. The outcome
(version + results) is stored with the extraction and never recomputed on replay.
"""

from __future__ import annotations

import re
from collections.abc import Collection
from decimal import Decimal, InvalidOperation

from flooreplay.decisions.extraction.lexicon import lexicon_hits
from flooreplay.decisions.extraction.schema import (
    ISSUES,
    SIGNAL_FIELDS,
    FieldValue,
    NoteSignal,
    normalize_note,
)
from flooreplay.decisions.types import FrozenModel, ReviewState

CHECKS_VERSION = "checks-v1"
LOT_ID_PATTERN = r"^L-\d{2,5}$"

_LOT_RE = re.compile(LOT_ID_PATTERN)
# Plain digits, one optional decimal point, optional Western (1,234,567) or
# Indian (12,34,567) thousands grouping. No "1.2k", no "lakh".
_QTY_RE = re.compile(r"^(?:\d{1,3}(?:,\d{3})+|\d{1,2}(?:,\d{2})+,\d{3}|\d+)(?:\.\d+)?$")
_QTY_TOKEN_RE = re.compile(r"(?<![\w.,])\d[\d,]*(?:\.\d+)?(?![\d,]|\.\d)")
_MULTIPLIER_RE = re.compile(r"^\s*(?:k(?![a-z])|lakhs?|lacs?|crores?)", re.IGNORECASE)
_KG_RE = re.compile(r"(?<![a-z])(?:kgs?|kilos?|kilograms?)(?![a-z])|கிலோ", re.IGNORECASE)
_M_RE = re.compile(r"(?<![a-z])(?:m|mtrs?|meters?|metres?)(?![a-z])|மீட்டர்", re.IGNORECASE)


class CheckResult(FrozenModel):
    field: str
    check: str
    passed: bool
    detail: str


class ChecksOutcome(FrozenModel):
    checks_version: str
    results: tuple[CheckResult, ...]
    failed_fields: tuple[str, ...]
    review_state: ReviewState


def _res(field: str, check: str, passed: bool, detail: str) -> CheckResult:
    return CheckResult(field=field, check=check, passed=passed, detail=detail)


def _missing(field: str, check: str, what: str = "value") -> CheckResult:
    return _res(field, check, False, f"missing {what}")


def parse_qty(text: str) -> Decimal | None:
    """Decimal for a plain quantity string, else None."""
    if not _QTY_RE.match(text):
        return None
    try:
        return Decimal(text.replace(",", ""))
    except InvalidOperation:  # pragma: no cover - the regex already guarantees a number
        return None


def check_span_exact(field: str, note: str, fv: FieldValue) -> CheckResult:
    check = "span_exact"
    span = fv.span
    if span is None:
        return _missing(field, check, "span")
    if not span.text:
        return _res(field, check, False, "span text is empty")
    nfc = normalize_note(note)
    if span.end > len(nfc):
        return _res(field, check, False, f"span end {span.end} beyond note length {len(nfc)}")
    actual = nfc[span.start : span.end]
    if actual != span.text:
        return _res(field, check, False, f"note[{span.start}:{span.end}] is {actual!r}")
    return _res(field, check, True, "span matches NFC note")


def _reparse_qty(value: str, span_text: str) -> tuple[bool, str]:
    wanted = parse_qty(value)
    if wanted is None:
        return False, f"value {value!r} is not a plain quantity"
    tokens = list(_QTY_TOKEN_RE.finditer(span_text))
    if len(tokens) != 1:
        return False, f"span has {len(tokens)} numeric tokens, need exactly 1"
    tok = tokens[0]
    if _MULTIPLIER_RE.match(span_text[tok.end() :]):
        return False, "span uses a multiplier suffix"
    got = parse_qty(tok.group(0))
    if got is None:
        return False, f"span number {tok.group(0)!r} is not a plain quantity"
    if got != wanted:
        return False, f"span parses to {got}, value is {wanted}"
    return True, f"span parses to {got}"


def _reparse_unit(value: str, span_text: str) -> tuple[bool, str]:
    found = set()
    if _KG_RE.search(span_text):
        found.add("kg")
    if _M_RE.search(span_text):
        found.add("m")
    if found == {value}:
        return True, f"span names {value}"
    return False, f"span names {sorted(found) or 'no unit'}, value is {value!r}"


def check_value_reparses(field: str, note: str, fv: FieldValue) -> CheckResult:
    check = "value_reparses"
    if fv.value is None:
        return _missing(field, check)
    if fv.span is None:
        return _missing(field, check, "span")
    if field == "qty":
        ok, detail = _reparse_qty(fv.value, fv.span.text)
    elif field == "unit":
        ok, detail = _reparse_unit(fv.value, fv.span.text)
    else:
        ok = fv.value.casefold() == fv.span.text.casefold() and bool(fv.value)
        detail = "value equals span (case-insensitive)" if ok else "value differs from span"
    return _res(field, check, ok, detail)


def check_lot_regex(field: str, fv: FieldValue) -> CheckResult:
    check = "lot_regex"
    if fv.value is None:
        return _missing(field, check)
    # fullmatch: `$` would otherwise accept a trailing newline.
    ok = _LOT_RE.fullmatch(fv.value) is not None
    return _res(field, check, ok, "matches lot pattern" if ok else f"does not match {LOT_ID_PATTERN}")


def check_issue_enum_and_lexicon(field: str, note: str, fv: FieldValue) -> CheckResult:
    check = "issue_enum_and_lexicon"
    if fv.value is None:
        return _missing(field, check)
    if fv.value not in ISSUES:
        return _res(field, check, False, f"{fv.value!r} is not in the issue enum")
    if not lexicon_hits(note, fv.value):
        return _res(field, check, False, f"no {fv.value} lexicon cue in the note")
    return _res(field, check, True, "in enum with a lexicon cue")


def check_entity_exists(field: str, fv: FieldValue, known_lots: Collection[str]) -> CheckResult:
    check = "entity_exists"
    if fv.value is None:
        return _missing(field, check)
    ok = fv.value in known_lots
    return _res(field, check, ok, "lot is known" if ok else "lot is not in the known lots")


def run_checks(note: str, signal: NoteSignal, known_lots: Collection[str]) -> ChecksOutcome:
    results: list[CheckResult] = []
    for field in SIGNAL_FIELDS:
        fv: FieldValue = getattr(signal, field)
        results.append(check_span_exact(field, note, fv))
        if field == "issue":
            results.append(check_issue_enum_and_lexicon(field, note, fv))
            continue
        results.append(check_value_reparses(field, note, fv))
        if field == "lot_id":
            results.append(check_lot_regex(field, fv))
            results.append(check_entity_exists(field, fv, known_lots))
    failed = tuple(f for f in SIGNAL_FIELDS if any(r.field == f and not r.passed for r in results))
    state = ReviewState.NEEDS_REVIEW if failed else ReviewState.CHECKS_PASSED
    return ChecksOutcome(
        checks_version=CHECKS_VERSION,
        results=tuple(results),
        failed_fields=failed,
        review_state=state,
    )
