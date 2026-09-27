"""Expectation evaluation: did this replay behave the way we demand?

Expectations are pinned per scenario revision, versioned in Git with a
written rationale, and evaluated independently of the replay. An
expectation may assert the domain outcome, required issue codes, required
failed/passed constraints, forbidden or allowed operators, and whether
policy execution is permitted. Operator identity is required only when the
identity itself is the subject under test.
"""

from __future__ import annotations

from .types import (
    ConstraintCode,
    DomainOutcome,
    IssueCode,
    OperatorId,
    ReplayOutcome,
    Verdict,
)


class Expectation:
    __slots__ = (
        "expected_outcome",
        "required_issue_codes",
        "required_failed_constraints",
        "required_passed_constraints",
        "forbidden_operators",
        "allowed_operators",
        "required_operator",
        "policy_execution_permitted",
    )

    def __init__(
        self,
        expected_outcome: DomainOutcome | None = None,
        required_issue_codes: tuple[IssueCode, ...] = (),
        required_failed_constraints: tuple[ConstraintCode, ...] = (),
        required_passed_constraints: tuple[ConstraintCode, ...] = (),
        forbidden_operators: tuple[OperatorId, ...] = (),
        allowed_operators: tuple[OperatorId, ...] = (),
        required_operator: OperatorId | None = None,
        policy_execution_permitted: bool | None = None,
    ) -> None:
        self.expected_outcome = expected_outcome
        self.required_issue_codes = required_issue_codes
        self.required_failed_constraints = required_failed_constraints
        self.required_passed_constraints = required_passed_constraints
        self.forbidden_operators = forbidden_operators
        self.allowed_operators = allowed_operators
        self.required_operator = required_operator
        self.policy_execution_permitted = policy_execution_permitted


class ExpectationVerdict:
    __slots__ = ("verdict", "failures")

    def __init__(self, verdict: Verdict, failures: tuple[str, ...]) -> None:
        self.verdict = verdict
        self.failures = failures


def evaluate(result: ReplayOutcome, expectation: Expectation) -> ExpectationVerdict:
    failures: list[str] = []

    if expectation.expected_outcome is not None and result.outcome != expectation.expected_outcome:
        failures.append(
            f"expected outcome {expectation.expected_outcome.value}, got {result.outcome.value}"
        )

    present_issue_codes = {i.code for i in result.gate_issues}
    for issue_code in expectation.required_issue_codes:
        if issue_code not in present_issue_codes:
            failures.append(f"required issue code {issue_code.value} not reported")

    failed = {c.code for c in result.constraints if c.verdict is Verdict.FAIL}
    passed = {c.code for c in result.constraints if c.verdict is Verdict.PASS}
    for failed_code in expectation.required_failed_constraints:
        if failed_code not in failed:
            failures.append(f"required failed constraint {failed_code.value} did not fail")
    for passed_code in expectation.required_passed_constraints:
        if passed_code not in passed:
            failures.append(f"required passed constraint {passed_code.value} did not pass")

    if result.proposal is not None:
        proposed = result.proposal.operator_id
        if proposed in expectation.forbidden_operators:
            failures.append(f"forbidden operator {proposed} was proposed")
        if expectation.allowed_operators and proposed not in expectation.allowed_operators:
            failures.append(f"proposed operator {proposed} is not in the allowed set")
        if (
            expectation.required_operator is not None
            and proposed != expectation.required_operator
        ):
            failures.append(
                f"required operator {expectation.required_operator}, got {proposed}"
            )

    policy_ran = result.proposal is not None or result.abstention is not None
    if expectation.policy_execution_permitted is False and policy_ran and (
        result.proposal is not None
        or not _blocked_outcome(result.outcome)
    ):
        failures.append("policy execution was expected to be blocked but a decision was produced")
    if expectation.policy_execution_permitted is True and not policy_ran:
        failures.append("policy execution was expected but the replay was blocked")

    return ExpectationVerdict(
        Verdict.PASS if not failures else Verdict.FAIL, tuple(failures)
    )


def _blocked_outcome(outcome: DomainOutcome) -> bool:
    return outcome in (DomainOutcome.NEEDS_CONTEXT, DomainOutcome.CONFLICTING_CONTEXT)
