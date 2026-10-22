"""Offline scoring for the draft note extraction benchmark.

This module has no provider or filesystem dependency. Gold records carry their note text so
predicted evidence can be checked against the exact NFC note being scored. Ratios are Decimal
values computed at a fixed precision, independently of the caller's Decimal context.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from typing import Any

from flooreplay.decisions.extraction.checks import (
    ChecksOutcome,
    FieldStatus,
    locate_evidence,
    parse_qty,
)
from flooreplay.decisions.extraction.schema import SIGNAL_FIELDS, normalize_note, note_digest
from flooreplay.decisions.types import FrozenModel

LANGUAGES = ("en", "ta", "tanglish")
_RATIO_PRECISION = 28
_MISSING = object()


class Metric(FrozenModel):
    numerator: int
    denominator: int
    ratio: Decimal | None


class BenchmarkMetrics(FrozenModel):
    field_accuracy: Metric
    missing_field_recall: Metric
    span_validity_rate: Metric
    checks_passed_precision: Metric


class FieldBenchmark(FrozenModel):
    overall: BenchmarkMetrics
    by_language: dict[str, BenchmarkMetrics]


class BenchmarkReport(FrozenModel):
    overall: BenchmarkMetrics
    by_language: dict[str, BenchmarkMetrics]
    by_field: dict[str, FieldBenchmark]


class _Counts:
    """Mutable internal counters; the public report is made of frozen models."""

    def __init__(self) -> None:
        self.field_accuracy = [0, 0]
        self.missing_field_recall = [0, 0]
        self.span_validity_rate = [0, 0]
        self.checks_passed_precision = [0, 0]

    def record(
        self,
        *,
        accuracy: bool,
        gold_missing: bool,
        prediction_missing: bool,
        span_claimed: bool,
        span_valid: bool,
        checks_passed: bool,
        checks_match_gold: bool,
    ) -> None:
        self.field_accuracy[0] += int(accuracy)
        self.field_accuracy[1] += 1
        if gold_missing:
            self.missing_field_recall[0] += int(prediction_missing)
            self.missing_field_recall[1] += 1
        if span_claimed:
            self.span_validity_rate[0] += int(span_valid)
            self.span_validity_rate[1] += 1
        if checks_passed:
            self.checks_passed_precision[0] += int(checks_match_gold)
            self.checks_passed_precision[1] += 1

    def metric(self, counts: list[int]) -> Metric:
        numerator, denominator = counts
        if denominator == 0:
            ratio = None
        else:
            with localcontext(Context(prec=_RATIO_PRECISION, rounding=ROUND_HALF_EVEN)):
                ratio = Decimal(numerator) / Decimal(denominator)
        return Metric(numerator=numerator, denominator=denominator, ratio=ratio)

    def freeze(self) -> BenchmarkMetrics:
        return BenchmarkMetrics(
            field_accuracy=self.metric(self.field_accuracy),
            missing_field_recall=self.metric(self.missing_field_recall),
            span_validity_rate=self.metric(self.span_validity_rate),
            checks_passed_precision=self.metric(self.checks_passed_precision),
        )


def _validate_gold_field(value: Any, *, note_id: str, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, Mapping) or set(value) != {"value", "evidence"}:
        raise ValueError(f"gold {note_id}.{field} must be null or contain value and evidence")
    field_value = value["value"]
    evidence = value["evidence"]
    if not isinstance(field_value, str) or not isinstance(evidence, str) or not evidence:
        raise ValueError(f"gold {note_id}.{field} requires non-empty string value and evidence")
    return normalize_note(field_value)


def _prediction_field(prediction: Mapping[str, Any] | None, field: str) -> tuple[Any, Any, bool]:
    """Return value, evidence and whether the field makes any claim.

    A missing note or missing field is deliberately distinct from an explicit null field: it
    counts as an incorrect prediction even when the gold field is null.
    """
    if prediction is None or field not in prediction:
        return _MISSING, _MISSING, False
    item = prediction[field]
    if item is None:
        return None, None, False
    if not isinstance(item, Mapping):
        return _MISSING, _MISSING, True
    value = item.get("value", _MISSING)
    evidence = item.get("evidence", _MISSING)
    claimed = value not in (_MISSING, None) or evidence not in (_MISSING, None)
    return value, evidence, claimed


def _normalized_value(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    return normalize_note(value)


def _values_match(field: str, left: Any, right: Any) -> bool:
    if left is None or right is None:
        return left is None and right is None
    normalized_left = _normalized_value(left)
    normalized_right = _normalized_value(right)
    if field == "qty" and normalized_left is not None and normalized_right is not None:
        left_number = parse_qty(normalized_left)
        right_number = parse_qty(normalized_right)
        if left_number is not None and right_number is not None:
            return left_number == right_number
    return normalized_left is not None and normalized_left == normalized_right


def score_benchmark(
    gold: Sequence[Mapping[str, Any]],
    predictions: Mapping[str, Mapping[str, Any]],
    checks: Mapping[str, ChecksOutcome],
) -> BenchmarkReport:
    """Score note-signal predictions against draft gold records.

    Gold records must contain ``note_id``, ``language``, ``text`` and all six signal fields;
    each signal field is null or ``{value, evidence}``. Predictions and checks are keyed by
    note id. Missing prediction notes/fields are incorrect, while explicit null fields mean
    no claim. Field accuracy and trusted-value precision compare canonical values; quantity
    values compare numerically with Decimal. Predicted evidence is valid only when it occurs
    exactly once in the NFC note (including overlapping occurrences).
    """
    if not isinstance(gold, Sequence) or isinstance(gold, (str, bytes)):
        raise ValueError("gold must be a sequence of records")
    if not isinstance(predictions, Mapping) or not isinstance(checks, Mapping):
        raise ValueError("predictions and checks must be mappings keyed by note_id")

    note_ids: set[str] = set()
    prepared: list[tuple[str, str, str, dict[str, str | None]]] = []
    for record in gold:
        if not isinstance(record, Mapping):
            raise ValueError("each gold record must be a mapping")
        note_id = record.get("note_id")
        language = record.get("language")
        note = record.get("text")
        if not isinstance(note_id, str) or not note_id:
            raise ValueError("gold note_id must be a non-empty string")
        if note_id in note_ids:
            raise ValueError(f"duplicate gold note_id: {note_id}")
        note_ids.add(note_id)
        if language not in LANGUAGES:
            raise ValueError(f"unsupported benchmark language for {note_id}: {language!r}")
        if not isinstance(note, str):
            raise ValueError(f"gold text for {note_id} must be a string")
        if any(field not in record for field in SIGNAL_FIELDS):
            raise ValueError(f"gold record {note_id} is missing one or more signal fields")
        values = {
            field: _validate_gold_field(record[field], note_id=note_id, field=field)
            for field in SIGNAL_FIELDS
        }
        prepared.append((note_id, language, normalize_note(note), values))

    unknown_predictions = set(predictions) - note_ids
    unknown_checks = set(checks) - note_ids
    if unknown_predictions:
        raise ValueError(f"prediction ids are absent from gold: {sorted(unknown_predictions)}")
    if unknown_checks:
        raise ValueError(f"check ids are absent from gold: {sorted(unknown_checks)}")

    overall = _Counts()
    by_language: dict[str, _Counts] = {}
    by_field: dict[str, _Counts] = {field: _Counts() for field in SIGNAL_FIELDS}
    by_field_language: dict[str, dict[str, _Counts]] = {field: {} for field in SIGNAL_FIELDS}

    for note_id, language, note, gold_values in prepared:
        prediction = predictions.get(note_id)
        if prediction is not None and not isinstance(prediction, Mapping):
            raise ValueError(f"prediction for {note_id} must be a note-signal mapping")
        if prediction is not None:
            extra_fields = set(prediction) - {*SIGNAL_FIELDS, "language"}
            if extra_fields:
                raise ValueError(
                    f"prediction for {note_id} has unknown fields: {sorted(extra_fields)}"
                )
        outcome = checks.get(note_id)
        if outcome is not None and not isinstance(outcome, ChecksOutcome):
            raise ValueError(f"checks for {note_id} must be a ChecksOutcome")
        if outcome is not None and outcome.note_digest != note_digest(note):
            raise ValueError(f"checks note digest does not match gold note {note_id}")
        checked_fields = {field.field: field for field in outcome.fields} if outcome else {}

        language_counts = by_language.setdefault(language, _Counts())
        for field in SIGNAL_FIELDS:
            gold_value = gold_values[field]
            predicted_value, evidence, claimed = _prediction_field(prediction, field)
            explicit_null = (
                prediction is not None and field in prediction and prediction[field] is None
            ) or (
                prediction is not None
                and field in prediction
                and isinstance(prediction[field], Mapping)
                and prediction[field].get("value", _MISSING) is None
                and prediction[field].get("evidence", _MISSING) is None
            )
            absent_prediction = explicit_null
            accuracy = _values_match(field, predicted_value, gold_value) and (
                gold_value is not None or absent_prediction
            )

            span_valid = False
            if isinstance(evidence, str) and evidence:
                span_valid = locate_evidence(note, evidence).span is not None

            checked = checked_fields.get(field)
            checks_passed = checked is not None and checked.status is FieldStatus.PASSED
            checks_match_gold = False
            if checks_passed and checked is not None:
                checks_match_gold = _values_match(field, checked.value, gold_value) and (
                    _values_match(field, checked.value, predicted_value)
                )

            args = {
                "accuracy": accuracy,
                "gold_missing": gold_value is None,
                "prediction_missing": absent_prediction,
                "span_claimed": claimed,
                "span_valid": span_valid,
                "checks_passed": checks_passed,
                "checks_match_gold": checks_match_gold,
            }
            overall.record(**args)
            language_counts.record(**args)
            by_field[field].record(**args)
            by_field_language[field].setdefault(language, _Counts()).record(**args)

    return BenchmarkReport(
        overall=overall.freeze(),
        by_language={language: counts.freeze() for language, counts in by_language.items()},
        by_field={
            field: FieldBenchmark(
                overall=counts.freeze(),
                by_language={
                    language: language_counts.freeze()
                    for language, language_counts in by_field_language[field].items()
                },
            )
            for field, counts in by_field.items()
        },
    )
