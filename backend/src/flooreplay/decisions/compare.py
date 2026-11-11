"""Pure case-by-case regression comparisons."""

from __future__ import annotations

from collections.abc import Mapping

from flooreplay.decisions.types import Classification, FrozenModel, Verdict


class CaseComparison(FrozenModel):
    case_id: str
    baseline: Verdict | None
    candidate: Verdict | None
    classification: Classification


def classify(baseline: Verdict | None, candidate: Verdict | None) -> Classification:
    """Missing or failed evaluations are not evidence of a pass or regression."""
    if baseline is None or candidate is None:
        return Classification.NOT_COMPARABLE
    return {
        (Verdict.PASS, Verdict.PASS): Classification.UNCHANGED_PASS,
        (Verdict.FAIL, Verdict.FAIL): Classification.UNCHANGED_FAIL,
        (Verdict.FAIL, Verdict.PASS): Classification.FIXED,
        (Verdict.PASS, Verdict.FAIL): Classification.REGRESSION,
    }.get((baseline, candidate), Classification.NOT_COMPARABLE)


def compare_cases(
    baseline: Mapping[str, Verdict | None],
    candidate: Mapping[str, Verdict | None],
    *,
    baseline_suite_digest: str,
    candidate_suite_digest: str,
) -> tuple[CaseComparison, ...]:
    """Compare the union of cases; errors, missing cases, and suite changes are incomparable."""
    same_suite = bool(baseline_suite_digest) and baseline_suite_digest == candidate_suite_digest
    return tuple(
        CaseComparison(
            case_id=case_id,
            baseline=baseline.get(case_id),
            candidate=candidate.get(case_id),
            classification=(
                classify(baseline.get(case_id), candidate.get(case_id))
                if same_suite
                else Classification.NOT_COMPARABLE
            ),
        )
        for case_id in sorted(baseline.keys() | candidate.keys())
    )
