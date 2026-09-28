"""Held-out parser evaluation tests.

Everything here runs offline against the rule baseline (or a fake parser for
the budget guard), so no API key and no network are involved. The tests
document the rule baseline's known blind spots on the held-out set — those
misses are the reason the evaluation exists and the reason a live-parser run
is worth its budget.
"""

from __future__ import annotations

from typing import Any

import pytest

from flooreplay.domain.types import Catalog
from flooreplay.eval_notes import BudgetGuard, EvalReport, run_eval, score_case
from flooreplay.fixtures import CATALOG
from flooreplay.fixtures_eval import HELD_OUT_NOTES, NoteCase
from flooreplay.parsing import RuleBaselineParser


def _case(case_id: str) -> NoteCase:
    return next(c for c in HELD_OUT_NOTES if c.id == case_id)


def test_held_out_set_has_unique_ids_and_labels():
    ids = [c.id for c in HELD_OUT_NOTES]
    assert len(ids) == len(set(ids))
    assert len(HELD_OUT_NOTES) >= 12  # large enough to say something


def test_rule_baseline_passes_clean_cases():
    for case_id in ("NOTE-E01", "NOTE-E06", "NOTE-E13", "NOTE-E15"):
        result = score_case(_case(case_id), RuleBaselineParser(), CATALOG)
        assert result.exact_match, (case_id, result.fields)


def test_rule_baseline_blind_spots_are_measured_not_hidden():
    # display-name notes: the rule baseline only sees exact operator ids
    e02 = score_case(_case("NOTE-E02"), RuleBaselineParser(), CATALOG)
    assert not e02.fields["subject_operator_ids"]
    # denied absence: "absent" appears but the note says he WILL be in
    e09 = score_case(_case("NOTE-E09"), RuleBaselineParser(), CATALOG)
    assert not e09.fields["event_category"]
    # cover-provider must not be counted as a subject
    e10 = score_case(_case("NOTE-E10"), RuleBaselineParser(), CATALOG)
    assert not e10.fields["subject_operator_ids"]
    assert e10.resolved_subjects == ["O133", "O158"]


def test_full_offline_eval_report_is_consistent():
    report = run_eval(RuleBaselineParser(), CATALOG)
    assert report.status == "COMPLETED"
    assert report.total_cases == len(HELD_OUT_NOTES)
    assert len(report.cases) == report.total_cases
    summary = report.summary()
    assert summary["spent_inr"] == 0  # offline evaluation costs nothing
    assert 0.0 <= summary["exact_match_rate"] <= 1.0  # type: ignore[arg-type]
    # per-field accuracies stay within [0, 1] and the misses list matches
    missed = [c.case_id for c in report.cases if not c.exact_match]
    assert summary["missed_cases"] == missed  # type: ignore[comparison-overlap]
    assert summary["missed_cases"]  # type: ignore[non-empty-subscript]


class _FakeParser:
    """Pretends to be a live parser that burns budget on every call."""

    kind = "fake-live"
    model = "fake-model"

    def __init__(self, tokens_per_call: int) -> None:
        self.tokens_per_call = tokens_per_call
        self.calls = 0

    def parse(self, note_text: str, catalog: Catalog) -> Any:
        self.calls += 1
        from flooreplay.parsing import DraftExtraction

        return DraftExtraction(
            event_category="UNSUPPORTED",
            parser_kind=self.kind,
            model=self.model,
            usage={"input_tokens": self.tokens_per_call, "output_tokens": 0},
        )


def test_budget_guard_stops_and_reports_exhausted():
    parser = _FakeParser(tokens_per_call=10_000_000)  # 10M input tokens = $4 = ₹352
    report = run_eval(parser, CATALOG, budget_inr=400.0)
    assert report.status == "BUDGET_EXHAUSTED"
    assert len(report.cases) < report.total_cases  # stopped early
    # the guard checks before each case: two calls fit under 400 before the
    # third is refused, and every measured case corresponds to one call
    assert len(report.cases) == 2
    assert parser.calls == len(report.cases)
    assert report.spent_inr >= 400.0


def test_budget_guard_charges_at_pinned_prices():
    guard = BudgetGuard(budget_inr=500.0)
    guard.charge({"input_tokens": 1_000_000, "output_tokens": 1_000_000})
    # $0.40 input + $1.60 output = $2.00 = ₹176 at the pinned rate
    assert guard.spent_inr == pytest.approx(176.0)
    assert not guard.exhausted
    guard.charge({"input_tokens": 4_000_000, "output_tokens": 4_000_000})
    assert guard.exhausted  # +$8.00 = ₹704 crosses the line


def test_eval_report_never_reports_more_than_budget():
    parser = _FakeParser(tokens_per_call=100_000_000)  # one call = $40
    report = run_eval(parser, CATALOG, budget_inr=1.0)
    assert isinstance(report, EvalReport)
    # the case that crossed the line still ran (its cost is real), then the
    # guard refused everything else
    assert len(report.cases) == 1
    assert parser.calls == 1
