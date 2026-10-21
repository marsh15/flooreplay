"""Deterministic per-field checks (`checks-v2`). No model confidence is ever consulted.

The model supplies a `value` and `evidence` per field. Code locates the evidence in the
NFC note (exactly one occurrence, else the field fails) and every later check is about that
located span and the text around it in the note, never about what the model says it saw.

Outcome rules:
- every field is `passed`, `missing` (the model said nothing) or `failed` (it claimed
  something the checks do not support); results carry `missing` vs `claimed_and_failed`;
- `lot_id`, `issue`, `qty` and `unit` are required, `colour` and `fabric_quality` optional
  (null is fine, present must pass);
- an all-null signal is `no_signal`: no fact and no review item;
- a note with more than one lot-like or quantity-like token, or over the length limit, makes
  every field fail (`ambiguous_note` / `note_too_long`).

The outcome is self-describing (versions, lot pattern, known-lots digest, located spans,
canonical values) and is stored with the extraction; replay never recomputes it.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Collection
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any, NamedTuple

from flooreplay.decisions.extraction.lexicon import (
    LEXICON,
    LEXICON_VERSION,
    MAX_NOTE_CODE_POINTS,
    lexicon_hits,
)
from flooreplay.decisions.extraction.schema import (
    ISSUES,
    REQUIRED_FIELDS,
    SCHEMA_VERSION,
    SIGNAL_FIELDS,
    UNITS,
    FieldValue,
    NoteSignal,
    Span,
    normalize_note,
)
from flooreplay.decisions.types import FrozenModel, ReviewState, canonical, decision_digest

CHECKS_VERSION = "checks-v2"
LOT_ID_PATTERN = r"^L-\d{2,5}$"

_LOT_RE = re.compile(LOT_ID_PATTERN, re.ASCII)

_NUM = r"(?:\d{1,3}(?:,\d{3})+|\d{1,2}(?:,\d{2})+,\d{3}|\d+)(?:\.\d+)?"
_UNIT_WORDS = r"(?:kgs?|kilos?|kilograms?|mtrs?|meters?|metres?|m|கிலோ|மீட்டர்)"
# Plain ASCII digits, one optional decimal point, optional Western (1,234,567) or Indian
# (12,34,567) grouping. No "1.2k", no "lakh", no fullwidth or Tamil digits.
_QTY_RE = re.compile(_NUM, re.ASCII)
# A qty span is the number, optionally followed directly by its unit ("1,200 kg", "50kg").
_QTY_SPAN_RE = re.compile(
    rf"(?P<num>{_NUM})(?:\s*(?P<unit>{_UNIT_WORDS})(?![A-Za-z]))?", re.ASCII | re.IGNORECASE
)
_MULTIPLIER_RE = re.compile(r"\s*(?:k(?![a-z])|lakhs?|lacs?|crores?)", re.IGNORECASE)
_UNIT_RE = re.compile(
    r"(?<![A-Za-z])(?:(?P<kg>kgs?|kilos?|kilograms?)|(?P<m>mtrs?|meters?|metres?|m))(?![A-Za-z])"
    r"|(?P<kg_ta>கிலோ)|(?P<m_ta>மீட்டர்)",
    re.IGNORECASE,
)
_LOT_LIKE_RE = re.compile(r"(?<![\w-])L-\d+(?![\w-])", re.IGNORECASE)
_LOT_FRAGMENT_RE = re.compile(r"L-\d+", re.IGNORECASE)
_QTY_LIKE_RE = re.compile(
    r"(?<![\w.,-])[0-9]+(?:,[0-9]+)*(?:\.[0-9]+)?\s*"
    r"(?:(?:k|lakhs?|lacs?|crores?)\s*)?"
    rf"{_UNIT_WORDS}(?![A-Za-z])",
    re.IGNORECASE,
)
_WORDISH = re.compile(r"[\w-]")
_NUMBERISH = re.compile(r"[\w.,]")


class CheckStatus(StrEnum):
    PASSED = "passed"
    MISSING = "missing"  # the model reported nothing for the field
    CLAIMED_AND_FAILED = "claimed_and_failed"  # it reported something the checks reject


class FieldStatus(StrEnum):
    PASSED = "passed"
    MISSING = "missing"
    FAILED = "failed"


class SignalOutcome(StrEnum):
    CHECKS_PASSED = "checks_passed"
    NEEDS_REVIEW = "needs_review"
    NO_SIGNAL = "no_signal"


class CheckResult(FrozenModel):
    field: str
    check: str
    status: CheckStatus
    code: str  # machine-readable reason; "ok" when passed
    detail: str

    @property
    def passed(self) -> bool:
        return self.status == CheckStatus.PASSED


class FieldOutcome(FrozenModel):
    field: str
    status: FieldStatus
    value: str | None  # canonical when it re-parsed (qty as canonical Decimal text)
    span: Span | None  # located evidence, code points of the NFC note


class ChecksOutcome(FrozenModel):
    checks_version: str
    lexicon_version: str
    schema_version: str
    lot_pattern: str
    known_lots_digest: str
    note_digest: str
    fields: tuple[FieldOutcome, ...]
    results: tuple[CheckResult, ...]
    failed_fields: tuple[str, ...]
    outcome: SignalOutcome
    review_state: ReviewState | None  # None for `no_signal`: no fact, no review item

    def canonical_payload(self) -> dict[str, Any]:
        """Canonical JSON-able form (enums as values, Decimals as text, NFC strings)."""
        payload = canonical(self)
        assert isinstance(payload, dict)
        return payload

    def canonical_digest(self) -> str:
        return decision_digest(self)


class Location(NamedTuple):
    span: Span | None
    code: str  # ok | span_not_found | ambiguous_span


def locate_evidence(note: str, evidence: str) -> Location:
    """Find `evidence` in the NFC note. Exactly one occurrence yields the span.

    Occurrences are counted with overlaps ("aa" in "aaa" is two), because an overlapping
    repeat is as ambiguous as a disjoint one. Matching is exact and case-sensitive.
    """
    nfc = normalize_note(note)
    needle = unicodedata.normalize("NFC", evidence)
    if not needle:
        return Location(None, "span_not_found")
    first = nfc.find(needle)
    if first == -1:
        return Location(None, "span_not_found")
    if nfc.find(needle, first + 1) != -1:
        return Location(None, "ambiguous_span")
    return Location(Span(start=first, end=first + len(needle), text=needle), "ok")


def parse_qty(text: str) -> Decimal | None:
    """Positive Decimal for a plain ASCII quantity string, else None."""
    if _QTY_RE.fullmatch(text) is None:
        return None
    try:
        value = Decimal(text.replace(",", ""))
    except InvalidOperation:  # pragma: no cover - the regex already guarantees a number
        return None
    return value if value > 0 else None


def _canonical_qty(value: str) -> str:
    parsed = parse_qty(value)
    if parsed is None:
        return value
    text = canonical(parsed)
    assert isinstance(text, str)
    return text


def _overlaps(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    return a_start < b_end and b_start < a_end


class _Sink:
    """Collects the results of one field."""

    def __init__(self, field: str) -> None:
        self.field = field
        self.results: list[CheckResult] = []

    def add(self, check: str, ok: bool, code: str, detail: str) -> bool:
        status = CheckStatus.PASSED if ok else CheckStatus.CLAIMED_AND_FAILED
        self.results.append(
            CheckResult(
                field=self.field,
                check=check,
                status=status,
                code="ok" if ok else code,
                detail=detail,
            )
        )
        return ok

    def missing(self, check: str, code: str, detail: str) -> None:
        self.results.append(
            CheckResult(
                field=self.field, check=check, status=CheckStatus.MISSING, code=code, detail=detail
            )
        )

    @property
    def failed(self) -> bool:
        return any(r.status == CheckStatus.CLAIMED_AND_FAILED for r in self.results)


class _Ctx:
    def __init__(self, note: str, signal: NoteSignal, known_lots: Collection[str]) -> None:
        self.note = normalize_note(note)
        self.signal = signal
        self.known_lots = frozenset(known_lots)
        ev = signal.qty.evidence
        self.qty_span: Span | None = locate_evidence(self.note, ev).span if ev else None

    def char_before(self, span: Span) -> str:
        return self.note[span.start - 1] if span.start > 0 else ""

    def char_after(self, span: Span) -> str:
        return self.note[span.end] if span.end < len(self.note) else ""

    def qty_number(self) -> tuple[int, int] | None:
        """Absolute (start, end) of the numeric token inside the located qty span."""
        span = self.qty_span
        if span is None:
            return None
        m = _QTY_SPAN_RE.fullmatch(span.text)
        if m is None:
            return None
        return span.start + m.start("num"), span.start + m.end("num")


def _grapheme_safe(sink: _Sink, ctx: _Ctx, span: Span) -> None:
    first = span.text[0]
    after = ctx.char_after(span)
    if unicodedata.category(first).startswith("M"):
        sink.add("grapheme_safe", False, "splits_grapheme", "evidence starts with a combining mark")
    elif after and unicodedata.category(after).startswith("M"):
        sink.add(
            "grapheme_safe", False, "splits_grapheme", "evidence stops before a combining mark"
        )
    else:
        sink.add("grapheme_safe", True, "ok", "evidence does not split a grapheme")


def _check_text_field(sink: _Sink, ctx: _Ctx, value: str, span: Span) -> None:
    """lot_id, colour, fabric_quality: the value is the evidence, and a whole token."""
    if not any(ch.isalnum() for ch in value.strip()):
        code, detail = "value_blank", "value has no letter or digit"
    elif span.text != span.text.strip():
        code, detail = "evidence_padded", "evidence has surrounding whitespace"
    elif value.casefold() != span.text.casefold():
        code, detail = "value_mismatch", "value differs from evidence (case-insensitive)"
    else:
        code, detail = "ok", "value equals evidence (case-insensitive)"
    sink.add("value_reparses", code == "ok", code, detail)
    before, after = ctx.char_before(span), ctx.char_after(span)
    whole = not (before and _WORDISH.match(before)) and not (after and _WORDISH.match(after))
    sink.add(
        "token_boundary",
        whole,
        "not_a_whole_token",
        "evidence is a whole token in the note" if whole else "evidence sits inside a longer token",
    )


def _check_lot_id(sink: _Sink, ctx: _Ctx, value: str, span: Span) -> None:
    _check_text_field(sink, ctx, value, span)
    ok = _LOT_RE.fullmatch(value) is not None
    sink.add(
        "lot_regex",
        ok,
        "bad_lot_format",
        "matches lot pattern" if ok else f"does not match {LOT_ID_PATTERN}",
    )
    known = value in ctx.known_lots
    sink.add(
        "entity_exists",
        known,
        "unknown_lot",
        "lot is known" if known else "lot is not in the known lots",
    )


def _check_issue(sink: _Sink, ctx: _Ctx, value: str, span: Span) -> None:
    check = "issue_enum_and_lexicon"
    if value not in ISSUES:
        sink.add(check, False, "not_in_enum", f"{value!r} is not in the issue enum")
        return
    own = [
        h for h in lexicon_hits(ctx.note, value) if _overlaps(h.start, h.end, span.start, span.end)
    ]
    if not own:
        sink.add(check, False, "no_cue_in_evidence", f"no live {value} cue overlaps the evidence")
        return
    for other in LEXICON:
        if other == value:
            continue
        if any(
            _overlaps(h.start, h.end, span.start, span.end) for h in lexicon_hits(ctx.note, other)
        ):
            sink.add(check, False, "other_issue_cue", f"evidence overlaps a {other} cue")
            return
    sink.add(
        check, True, "ok", "in enum; a live cue overlaps the evidence and no other issue's does"
    )


def _check_qty(sink: _Sink, ctx: _Ctx, value: str, span: Span) -> None:
    wanted = parse_qty(value)
    m = _QTY_SPAN_RE.fullmatch(span.text)
    if wanted is None:
        code, detail = "value_not_plain_qty", f"value {value!r} is not a positive plain quantity"
    elif m is None:
        code, detail = (
            "span_not_a_quantity",
            "evidence is not one plain number (with optional unit)",
        )
    else:
        got = parse_qty(m.group("num"))
        if got is None:
            code, detail = "span_not_plain_qty", f"evidence number {m.group('num')!r} is not plain"
        elif got != wanted:
            code, detail = "value_mismatch", f"evidence parses to {got}, value is {wanted}"
        elif _MULTIPLIER_RE.match(ctx.note, span.start + m.end("num")):
            code, detail = "multiplier", "the number is followed by k / lakh / lac / crore"
        else:
            code, detail = "ok", f"evidence parses to {got}"
    sink.add("value_reparses", code == "ok", code, detail)

    if any(
        _overlaps(f.start(), f.end(), span.start, span.end)
        for f in _LOT_FRAGMENT_RE.finditer(ctx.note)
    ):
        sink.add("qty_boundary", False, "qty_inside_lot_id", "evidence overlaps a lot id")
        return
    before, after = ctx.char_before(span), ctx.char_after(span)
    tail = ctx.note[span.end + 1 : span.end + 2]
    bad_before = bool(before) and _NUMBERISH.match(before) is not None
    bad_after = bool(after) and (
        re.match(r"\w", after) is not None or (after in ".," and tail.isdecimal())
    )
    sink.add(
        "qty_boundary",
        not (bad_before or bad_after),
        "qty_not_standalone",
        "evidence is a standalone number"
        if not (bad_before or bad_after)
        else "evidence is part of a longer number or word",
    )


def _check_unit(sink: _Sink, ctx: _Ctx, value: str, span: Span) -> None:
    matches = [
        m
        for m in _UNIT_RE.finditer(ctx.note, span.start, min(len(ctx.note), span.end + 1))
        if m.end() <= span.end
    ]
    if value not in UNITS:
        code, detail, word = "not_in_enum", f"{value!r} is not a unit", None
    elif not matches:
        code, detail, word = "no_unit_in_evidence", "evidence names no unit", None
    elif len(matches) > 1:
        code, detail, word = "ambiguous_unit", "evidence names several units", None
    else:
        word = matches[0]
        kind = "kg" if (word.group("kg") or word.group("kg_ta")) else "m"
        if kind != value:
            code, detail, word = (
                "value_mismatch",
                f"evidence names {kind}, value is {value!r}",
                None,
            )
        elif word.end() != span.end:
            code, detail, word = "extra_text", "evidence continues past the unit", None
        else:
            code, detail = "ok", f"evidence names {value}"
    sink.add("value_reparses", code == "ok", code, detail)

    adjacent = False
    why = "no unit word to anchor"
    qty = ctx.qty_number()
    if word is not None:
        if qty is None:
            why = "no usable qty span to be adjacent to"
        else:
            q_start, q_end = qty
            prefix = span.text[: word.start() - span.start]
            starts_ok = word.start() == span.start or (
                span.start == q_start and prefix.rstrip() == ctx.note[q_start:q_end]
            )
            gap_ok = word.start() >= q_end and ctx.note[q_end : word.start()].strip() == ""
            adjacent = starts_ok and gap_ok
            why = (
                "unit directly follows the quantity"
                if adjacent
                else "unit is not next to the quantity"
            )
    sink.add("unit_adjacent", adjacent, "unit_not_adjacent", why)


def _check_claimed(field: str, fv: FieldValue, ctx: _Ctx) -> tuple[_Sink, str | None, Span | None]:
    sink = _Sink(field)
    value = unicodedata.normalize("NFC", fv.value) if fv.value is not None else None
    evidence = fv.evidence
    if "\x00" in (value or "") or "\x00" in (evidence or ""):
        sink.add("text_valid", False, "nul_character", "text contains a NUL character")
        return sink, None, None
    if value is None:
        sink.add("value_reparses", False, "value_missing", "evidence given without a value")
        return sink, None, None
    if not evidence:
        sink.add("span_located", False, "evidence_missing", "value given without evidence")
        return sink, value, None
    loc = locate_evidence(ctx.note, evidence)
    sink.add("span_located", loc.span is not None, loc.code, f"evidence occurs {loc.code}")
    span = loc.span
    if span is None:
        return sink, value, None
    _grapheme_safe(sink, ctx, span)
    if field == "lot_id":
        _check_lot_id(sink, ctx, value, span)
    elif field == "issue":
        _check_issue(sink, ctx, value, span)
    elif field == "qty":
        _check_qty(sink, ctx, value, span)
    elif field == "unit":
        _check_unit(sink, ctx, value, span)
    else:
        _check_text_field(sink, ctx, value, span)
    shown = _canonical_qty(value) if field == "qty" and not sink.failed else value
    return sink, shown, span


def _ambiguous(note: str) -> bool:
    lots = {m.group(0).casefold() for m in _LOT_LIKE_RE.finditer(note)}
    quantities = {m.span() for m in _QTY_LIKE_RE.finditer(note)}
    return len(lots) > 1 or len(quantities) > 1


def run_checks(note: str, signal: NoteSignal, known_lots: Collection[str]) -> ChecksOutcome:
    ctx = _Ctx(note, signal, known_lots)
    too_long = len(ctx.note) > MAX_NOTE_CODE_POINTS
    ambiguous = not too_long and _ambiguous(ctx.note)
    results: list[CheckResult] = []
    fields: list[FieldOutcome] = []
    failed: list[str] = []
    claimed_any = False

    for field in SIGNAL_FIELDS:
        fv: FieldValue = getattr(signal, field)
        claimed = fv.value is not None or fv.evidence is not None
        claimed_any = claimed_any or claimed
        sink = _Sink(field)
        value: str | None = None
        span: Span | None = None
        if too_long:
            if claimed:
                sink.add(
                    "note_length",
                    False,
                    "note_too_long",
                    f"note exceeds {MAX_NOTE_CODE_POINTS} code points",
                )
            else:
                sink.missing("note_length", "note_too_long", "note too long to check")
        elif not claimed:
            sink.missing("present", "no_value", "no value reported")
        else:
            sink, value, span = _check_claimed(field, fv, ctx)
            if ambiguous:
                sink.add(
                    "ambiguous_note",
                    False,
                    "ambiguous_note",
                    "note names several lots or quantities",
                )
        if ambiguous and not claimed:
            sink.missing(
                "ambiguous_note", "ambiguous_note", "note names several lots or quantities"
            )
        if not claimed:
            status = FieldStatus.MISSING
        else:
            status = FieldStatus.FAILED if sink.failed else FieldStatus.PASSED
        if status == FieldStatus.FAILED or (
            status == FieldStatus.MISSING and field in REQUIRED_FIELDS
        ):
            failed.append(field)
        results.extend(sink.results)
        fields.append(FieldOutcome(field=field, status=status, value=value, span=span))

    forced = too_long or ambiguous
    if forced:
        failed = list(SIGNAL_FIELDS)
    if not forced and not claimed_any:
        outcome, state = SignalOutcome.NO_SIGNAL, None
        failed = []
    elif failed:
        outcome, state = SignalOutcome.NEEDS_REVIEW, ReviewState.NEEDS_REVIEW
    else:
        outcome, state = SignalOutcome.CHECKS_PASSED, ReviewState.CHECKS_PASSED

    return ChecksOutcome(
        checks_version=CHECKS_VERSION,
        lexicon_version=LEXICON_VERSION,
        schema_version=SCHEMA_VERSION,
        lot_pattern=LOT_ID_PATTERN,
        known_lots_digest=decision_digest(sorted(set(known_lots))),
        note_digest=decision_digest(ctx.note.replace("\x00", "\\x00")),
        fields=tuple(fields),
        results=tuple(results),
        failed_fields=tuple(failed),
        outcome=outcome,
        review_state=state,
    )
