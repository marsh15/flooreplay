"""Evaluate a hand-authored case expectation against a decision's observable result."""

from __future__ import annotations

from flooreplay.decisions.types import FrozenModel, Recommendation, Verdict


class Expectation(FrozenModel):
    correct: Recommendation
    rationale: str
    required_findings: tuple[str, ...] = ()


class ExpectationVerdict(FrozenModel):
    verdict: Verdict
    failures: tuple[str, ...]


def evaluate_expectation(
    expectation: Expectation, outcome: Recommendation, finding_codes: tuple[str, ...]
) -> ExpectationVerdict:
    """Compare the recommended outcome and required gate finding codes with the gold case."""
    failures: list[str] = []
    if outcome != expectation.correct:
        failures.append(f"expected {expectation.correct.value}, got {outcome.value}")
    present = set(finding_codes)
    for code in sorted(set(expectation.required_findings) - present):
        failures.append(f"required finding {code} not reported")
    return ExpectationVerdict(
        verdict=Verdict.FAIL if failures else Verdict.PASS, failures=tuple(failures)
    )
