"""Held-out parser evaluation with a hard rupee budget.

Scoring compares each parser draft (after deterministic resolution) against
labels written by a careful human in fixtures_eval.py. The harness never
flatters: misses are reported per field, and the offline rule baseline is
scored with exactly the same code path as the live model.

Budget: the live parser charges the published pinned-model price per token,
converted to INR at a rate pinned in code. When the budget is exhausted the
run stops and reports BUDGET_EXHAUSTED with whatever was measured — a
half-finished evaluation still reports honestly. The offline baseline costs
nothing, so running it needs no budget at all.

Usage:
    uv run python -m flooreplay.eval_notes            # offline rule baseline
    uv run python -m flooreplay.eval_notes --live     # requires the API key
    uv run python -m flooreplay.eval_notes --budget-inr 500 --live
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from .config import settings
from .domain.types import Catalog
from .fixtures import CATALOG
from .fixtures_eval import HELD_OUT_NOTES, NoteCase
from .parsing import (
    OPENAI_MODEL,
    NoteParser,
    ParserUnavailable,
    get_parser,
    resolve_draft,
)

# Published pricing for the pinned model, per 1M tokens. Revisit only when
# OPENAI_MODEL changes; the budget's meaning depends on this staying pinned.
USD_PER_1M_INPUT = 0.40
USD_PER_1M_OUTPUT = 1.60
INR_PER_USD = 88.0  # pinned conversion rate for the ₹ budget


@dataclass
class BudgetGuard:
    budget_inr: float
    spent_usd: float = 0.0

    @property
    def spent_inr(self) -> float:
        return self.spent_usd * INR_PER_USD

    @property
    def exhausted(self) -> bool:
        return self.spent_inr >= self.budget_inr

    def charge(self, usage: dict[str, int]) -> None:
        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)
        self.spent_usd += (
            input_tokens * USD_PER_1M_INPUT + output_tokens * USD_PER_1M_OUTPUT
        ) / 1_000_000


@dataclass
class CaseResult:
    case_id: str
    probes: str
    fields: dict[str, bool]
    exact_match: bool
    parser_event_category: str
    resolved_subjects: list[str]
    resolved_operations: list[str]
    uncertainty_phrase: str | None
    usage: dict[str, int] = field(default_factory=dict)


@dataclass
class EvalReport:
    parser_kind: str
    model: str | None
    status: str  # COMPLETED | BUDGET_EXHAUSTED
    cases: list[CaseResult]
    total_cases: int
    spent_inr: float
    budget_inr: float
    created_at: str

    def summary(self) -> dict[str, object]:
        scored = self.cases
        n = len(scored) or 1
        per_field = {
            name: sum(1 for c in scored if c.fields.get(name)) / n
            for name in ("event_category", "subject_operator_ids", "operation_ids", "uncertainty")
        }
        return {
            "status": self.status,
            "parser_kind": self.parser_kind,
            "model": self.model,
            "cases_measured": len(scored),
            "cases_total": self.total_cases,
            "exact_match_rate": sum(1 for c in scored if c.exact_match) / n,
            "per_field_accuracy": per_field,
            "spent_inr": round(self.spent_inr, 4),
            "budget_inr": self.budget_inr,
            "missed_cases": [c.case_id for c in scored if not c.exact_match],
        }


def score_case(case: NoteCase, parser: NoteParser, catalog: Catalog) -> CaseResult:
    draft = parser.parse(case.note, catalog)
    resolution = resolve_draft(draft, catalog)
    resolved_subjects = sorted(
        str(entry["resolved_id"])
        for entry in resolution["operators"]
        if isinstance(entry["resolved_id"], str)
    )
    resolved_operations = sorted(
        str(entry["resolved_id"])
        for entry in resolution["operations"]
        if isinstance(entry["resolved_id"], str)
    )
    fields = {
        "event_category": draft.event_category == case.event_category,
        "subject_operator_ids": resolved_subjects == sorted(case.subject_operator_ids),
        "operation_ids": resolved_operations == sorted(case.operation_ids),
        "uncertainty": (draft.uncertainty_phrase is not None) == case.uncertainty,
    }
    return CaseResult(
        case_id=case.id,
        probes=case.probes,
        fields=fields,
        exact_match=all(fields.values()),
        parser_event_category=draft.event_category,
        resolved_subjects=resolved_subjects,
        resolved_operations=resolved_operations,
        uncertainty_phrase=draft.uncertainty_phrase,
        usage=dict(draft.usage),
    )


def run_eval(
    parser: NoteParser,
    catalog: Catalog,
    budget_inr: float = 500.0,
    cases: tuple[NoteCase, ...] = HELD_OUT_NOTES,
) -> EvalReport:
    budget = BudgetGuard(budget_inr=budget_inr)
    results: list[CaseResult] = []
    status = "COMPLETED"
    for case in cases:
        if budget.exhausted:
            status = "BUDGET_EXHAUSTED"
            break
        result = score_case(case, parser, catalog)
        budget.charge(result.usage)
        results.append(result)
    return EvalReport(
        parser_kind=parser.kind,
        model=getattr(parser, "model", None),
        status=status,
        cases=results,
        total_cases=len(cases),
        spent_inr=budget.spent_inr,
        budget_inr=budget_inr,
        created_at=datetime.now(tz=UTC).isoformat(),
    )


def print_summary(report: EvalReport) -> None:
    n = len(report.cases) or 1
    print(f"parser: {report.parser_kind} ({report.model or 'n/a'})  status: {report.status}")
    print(
        f"cases: {len(report.cases)}/{report.total_cases} measured · "
        f"exact-match {sum(1 for c in report.cases if c.exact_match) / n:.0%} · "
        f"spent ₹{round(report.spent_inr, 4)}"
    )
    for name in ("event_category", "subject_operator_ids", "operation_ids", "uncertainty"):
        accuracy = sum(1 for c in report.cases if c.fields.get(name)) / n
        print(f"  {name:24s} {accuracy:.0%}")
    missed = [c.case_id for c in report.cases if not c.exact_match]
    if missed:
        print(f"missed: {', '.join(missed)}")


def main(argv: list[str] | None = None) -> int:
    argument_parser = argparse.ArgumentParser(description=__doc__)
    argument_parser.add_argument(
        "--live",
        action="store_true",
        help=f"use the live OpenAI parser ({OPENAI_MODEL}); needs FLOORREPLAY_OPENAI_API_KEY",
    )
    argument_parser.add_argument(
        "--budget-inr", type=float, default=500.0, help="maximum spend in rupees (default 500)"
    )
    args = argument_parser.parse_args(argv)

    try:
        parser = get_parser(settings.openai_api_key if args.live else None)
    except ParserUnavailable as exc:
        print(f"cannot start live evaluation: {exc}", file=sys.stderr)
        return 1
    if args.live and parser.kind != "openai-structured":
        print("no FLOORREPLAY_OPENAI_API_KEY configured; refusing to pretend this is live", file=sys.stderr)
        return 1

    report = run_eval(parser, CATALOG, budget_inr=args.budget_inr)
    print_summary(report)

    out_dir = Path("eval-reports")
    out_dir.mkdir(exist_ok=True)
    stamp = datetime.now(tz=UTC).strftime("%Y%m%d-%H%M%S")
    out_path = out_dir / f"notes-eval-{report.parser_kind}-{stamp}.json"
    out_path.write_text(json.dumps(asdict(report), indent=2))
    print(f"report written to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
