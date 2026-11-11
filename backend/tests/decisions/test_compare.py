from flooreplay.decisions.compare import classify, compare_cases
from flooreplay.decisions.expectations import Expectation, evaluate_expectation
from flooreplay.decisions.types import Classification, Recommendation, Verdict


def test_expectation_requires_outcome_and_all_findings():
    gold = Expectation(
        correct=Recommendation.NEEDS_REVIEW,
        rationale="Conflicting stock needs review",
        required_findings=("conflict", "missing"),
    )
    assert evaluate_expectation(gold, Recommendation.NEEDS_REVIEW, ("missing", "conflict")).verdict == Verdict.PASS
    result = evaluate_expectation(gold, Recommendation.ACCEPT, ("conflict",))
    assert result.verdict == Verdict.FAIL
    assert result.failures == ("expected NEEDS_REVIEW, got ACCEPT", "required finding missing not reported")


def test_classification_and_incomplete_runs():
    assert classify(Verdict.PASS, Verdict.PASS) == Classification.UNCHANGED_PASS
    assert classify(Verdict.FAIL, Verdict.FAIL) == Classification.UNCHANGED_FAIL
    assert classify(Verdict.FAIL, Verdict.PASS) == Classification.FIXED
    assert classify(Verdict.PASS, Verdict.FAIL) == Classification.REGRESSION
    assert classify(Verdict.FAIL, None) == Classification.NOT_COMPARABLE
    assert classify(None, Verdict.PASS) == Classification.NOT_COMPARABLE


def test_suite_mismatch_and_missing_cases_are_not_comparable():
    baseline = {"a": Verdict.PASS, "b": Verdict.FAIL}
    candidate = {"a": Verdict.FAIL, "c": Verdict.PASS}
    result = compare_cases(baseline, candidate, baseline_suite_digest="same", candidate_suite_digest="same")
    assert [(r.case_id, r.classification) for r in result] == [
        ("a", Classification.REGRESSION),
        ("b", Classification.NOT_COMPARABLE),
        ("c", Classification.NOT_COMPARABLE),
    ]
    changed = compare_cases(baseline, candidate, baseline_suite_digest="old", candidate_suite_digest="new")
    assert all(r.classification == Classification.NOT_COMPARABLE for r in changed)
    empty = compare_cases({"a": Verdict.PASS}, {"a": Verdict.PASS}, baseline_suite_digest="", candidate_suite_digest="")
    assert empty[0].classification == Classification.NOT_COMPARABLE
