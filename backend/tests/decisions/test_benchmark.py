"""Offline scoring for the note extraction benchmark."""

from __future__ import annotations

from decimal import Decimal, localcontext
from typing import Any

import pytest

from flooreplay.decisions.extraction.benchmark import score_benchmark
from flooreplay.decisions.extraction.checks import run_checks
from flooreplay.decisions.extraction.provider import MockProvider
from flooreplay.decisions.extraction.schema import (
    SIGNAL_FIELDS,
    note_digest,
    note_signal_json_schema,
    validate_signal_payload,
)

NOTE = "Lot L-1042 navy single jersey: shade variation, 1,200 kg held."
GOOD_RAW: dict[str, Any] = {
    "lot_id": {"value": "L-1042", "evidence": "L-1042"},
    "issue": {"value": "shade_fail", "evidence": "shade variation"},
    "qty": {"value": "1200", "evidence": "1,200 kg"},
    "unit": {"value": "kg", "evidence": "kg"},
    "colour": {"value": "NAVY", "evidence": "navy"},
    "fabric_quality": {"value": "Single Jersey", "evidence": "single jersey"},
    "language": "en",
}
EMPTY_TA_NOTE = "எல்லாம் சரி"


def field(value: str, evidence: str) -> dict[str, str]:
    return {"value": value, "evidence": evidence}


def absent_signal(language: str) -> dict[str, Any]:
    return {**{name: None for name in SIGNAL_FIELDS}, "language": language}


def gold_record(note_id: str, language: str, text: str, values: dict[str, Any]) -> dict[str, Any]:
    return {
        "note_id": note_id,
        "language": language,
        "text": text,
        **{name: values.get(name) for name in SIGNAL_FIELDS},
        "gold_status": "draft_unreviewed",
    }


def outcomes_for(predictions: dict[str, dict[str, Any]], notes: dict[str, str]):
    table = {note_digest(notes[note_id]): raw for note_id, raw in predictions.items()}
    provider = MockProvider(table)
    outcomes = {}
    for note_id, note in notes.items():
        raw = provider.extract(note, prompt_version="test", schema=note_signal_json_schema()).raw
        outcomes[note_id] = run_checks(note, validate_signal_payload(raw), {"L-1042", "L-77"})
    return outcomes


def ratio_tuple(metric) -> tuple[int, int, Decimal | None]:
    return metric.numerator, metric.denominator, metric.ratio


def test_scores_accuracy_missing_recall_span_validity_and_precision_by_language_and_field():
    empty_ta = absent_signal("ta")
    predictions = {"good": GOOD_RAW, "empty-ta": empty_ta}
    notes = {"good": NOTE, "empty-ta": EMPTY_TA_NOTE}
    checks = outcomes_for(predictions, notes)
    gold = [
        gold_record(
            "good",
            "en",
            NOTE,
            {name: value for name, value in GOOD_RAW.items() if name != "language"},
        ),
        gold_record("empty-ta", "ta", EMPTY_TA_NOTE, {}),
    ]

    report = score_benchmark(gold, predictions, checks)

    assert ratio_tuple(report.overall.field_accuracy) == (12, 12, Decimal(1))
    assert ratio_tuple(report.overall.missing_field_recall) == (6, 6, Decimal(1))
    assert ratio_tuple(report.overall.span_validity_rate) == (6, 6, Decimal(1))
    assert ratio_tuple(report.overall.checks_passed_precision) == (6, 6, Decimal(1))
    assert ratio_tuple(report.by_language["en"].field_accuracy) == (6, 6, Decimal(1))
    assert ratio_tuple(report.by_language["ta"].missing_field_recall) == (6, 6, Decimal(1))
    assert ratio_tuple(report.by_field["qty"].overall.field_accuracy) == (2, 2, Decimal(1))
    assert ratio_tuple(report.by_field["qty"].by_language["en"].checks_passed_precision) == (
        1,
        1,
        Decimal(1),
    )


def test_missing_prediction_is_not_counted_as_a_correct_gold_null():
    gold = [gold_record("empty", "en", "Routine update", {})]
    report = score_benchmark(gold, {}, {})

    assert ratio_tuple(report.overall.field_accuracy) == (0, 6, Decimal(0))
    assert ratio_tuple(report.overall.missing_field_recall) == (0, 6, Decimal(0))
    assert ratio_tuple(report.overall.span_validity_rate) == (0, 0, None)
    assert ratio_tuple(report.overall.checks_passed_precision) == (0, 0, None)


def test_overlapping_evidence_occurrences_are_invalid_spans():
    note = "aaa"
    prediction = absent_signal("en")
    prediction["colour"] = field("aa", "aa")
    provider = MockProvider({note_digest(note): prediction})
    raw = provider.extract(note, prompt_version="test", schema=note_signal_json_schema()).raw
    check = run_checks(note, validate_signal_payload(raw), set())
    report = score_benchmark(
        [gold_record("overlap", "en", note, {})], {"overlap": raw}, {"overlap": check}
    )

    assert ratio_tuple(report.overall.span_validity_rate) == (0, 1, Decimal(0))


def test_precision_does_not_trust_a_passed_check_for_a_different_prediction():
    predictions = {"good": GOOD_RAW}
    checks = outcomes_for(predictions, {"good": NOTE})
    stale_prediction = {**GOOD_RAW, "lot_id": field("L-77", "L-1042")}
    gold = [
        gold_record(
            "good",
            "en",
            NOTE,
            {name: value for name, value in GOOD_RAW.items() if name != "language"},
        )
    ]

    report = score_benchmark(gold, {"good": stale_prediction}, checks)

    assert ratio_tuple(report.overall.checks_passed_precision) == (5, 6, Decimal(5) / Decimal(6))


def test_zero_denominators_are_none_and_ratios_ignore_ambient_decimal_precision():
    note = "Routine update NAVY"
    prediction = absent_signal("en")
    prediction["colour"] = field("NAVY", "NAVY")
    predictions = {"empty": prediction}
    checks = outcomes_for(predictions, {"empty": note})
    gold = [gold_record("empty", "en", note, {})]

    with localcontext() as context:
        context.prec = 3
        first = score_benchmark(gold, predictions, checks)
    with localcontext() as context:
        context.prec = 50
        second = score_benchmark(gold, predictions, checks)

    assert first == second
    assert ratio_tuple(first.overall.missing_field_recall) == (5, 6, Decimal(5) / Decimal(6))
    assert ratio_tuple(first.overall.checks_passed_precision) == (0, 1, Decimal(0))


def test_empty_checks_and_empty_gold_have_none_for_zero_denominators():
    report = score_benchmark([], {}, {})

    assert ratio_tuple(report.overall.field_accuracy) == (0, 0, None)
    assert ratio_tuple(report.overall.missing_field_recall) == (0, 0, None)
    assert ratio_tuple(report.overall.span_validity_rate) == (0, 0, None)
    assert ratio_tuple(report.overall.checks_passed_precision) == (0, 0, None)


@pytest.mark.parametrize("bad_language", ["mixed", "Hindi", ""])
def test_unsupported_benchmark_languages_are_rejected(bad_language: str):
    gold = [gold_record("empty", bad_language, "Routine update", {})]
    with pytest.raises(ValueError):
        score_benchmark(gold, {}, {})


def test_malformed_gold_and_unmatched_prediction_ids_are_rejected():
    malformed = gold_record("empty", "en", "Routine update", {})
    del malformed["qty"]
    with pytest.raises(ValueError):
        score_benchmark([malformed], {}, {})

    with pytest.raises(ValueError):
        score_benchmark([gold_record("empty", "en", "Routine update", {})], {"extra": {}}, {})


def test_ratios_ignore_ambient_rounding_and_inexact_traps():
    from decimal import ROUND_UP, Inexact

    note = "Routine update NAVY"
    prediction = absent_signal("en")
    prediction["colour"] = field("NAVY", "NAVY")
    predictions = {"routine": prediction}
    checks = outcomes_for(predictions, {"routine": note})
    gold = [gold_record("routine", "en", note, {})]
    expected = score_benchmark(gold, predictions, checks)
    with localcontext() as context:
        context.rounding = ROUND_UP
        context.traps[Inexact] = True
        actual = score_benchmark(gold, predictions, checks)
    assert actual == expected


def test_quantities_canonicalized_by_the_checks_match_gold_for_accuracy_and_precision():
    prediction = {**GOOD_RAW, "qty": field("1,200", "1,200 kg")}
    predictions = {"grouped": prediction}
    checks = outcomes_for(predictions, {"grouped": NOTE})
    gold = [gold_record("grouped", "en", NOTE, GOOD_RAW)]
    report = score_benchmark(gold, predictions, checks)
    assert ratio_tuple(report.overall.field_accuracy) == (6, 6, Decimal(1))
    assert ratio_tuple(report.overall.checks_passed_precision) == (6, 6, Decimal(1))
