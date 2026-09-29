"""Small author-reviewed synthetic regression set, separate from runtime corpus.

This checks observable category detection and arithmetic, not hidden causes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .incident_ai import evaluate_drafts
from .incident_engine import analyze_incident
from .incident_service import search_incidents
from .models import IncidentRevision

# Frozen manually checked labels for the ten authored historical cases.
LABELS: dict[str, tuple[str | None, int]] = {
    "INC-101": ("material", 48),
    "INC-102": ("machine", 22),
    "INC-103": ("quality", 19),
    "INC-104": ("staffing", 19),
    "INC-105": ("changeover", 34),
    "INC-106": ("planning_reporting", 0),
    "INC-107": ("material", 39),
    "INC-108": ("machine", 10),
    "INC-109": ("quality", 16),
    "INC-110": (None, 0),
}
RETRIEVAL_LABELS = {
    "material": {"INC-101", "INC-107"},
    "machine": {"INC-102", "INC-108"},
    "qc": {"INC-103", "INC-109"},
}


def evaluation_report(session: Session) -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    numeric_pass = category_pass = negative_pass = 0
    for incident_id, (expected_category, expected_shortfall) in LABELS.items():
        row = session.get(IncidentRevision, (incident_id, 1))
        if row is None:
            failures.append({"case": incident_id, "reason": "Fixture revision missing"})
            continue
        report = analyze_incident(row.payload)
        actual_shortfall = report["metrics"]["shortfall"]
        categories = {h["category"] for h in report["hypotheses"]}
        numeric_ok = actual_shortfall == expected_shortfall
        category_ok = expected_category in categories if expected_category else not any(h["status"] == "SUPPORTED" for h in report["hypotheses"])
        numeric_pass += int(numeric_ok)
        category_pass += int(category_ok)
        if expected_category is None:
            negative_pass += int(category_ok)
        result = {
            "incident_id": incident_id, "expected_category": expected_category,
            "observed_categories": sorted(categories), "expected_shortfall": expected_shortfall,
            "actual_shortfall": actual_shortfall, "numeric_pass": numeric_ok,
            "category_pass": category_ok,
        }
        cases.append(result)
        if not numeric_ok or not category_ok:
            failures.append({"case": incident_id, "reason": "Arithmetic or observable category mismatch", "result": result})

    hero = session.get(IncidentRevision, ("INC-001", 1))
    retrieval: list[dict[str, Any]] = []
    if hero is not None:
        for query, relevant in RETRIEVAL_LABELS.items():
            found = search_incidents(session, query, cutoff=hero.cutoff, exclude_incident_id=hero.incident_id)
            retrieved = [item["id"] for item in found]
            hits = relevant.intersection(retrieved)
            title_vector = func.to_tsvector("english", IncidentRevision.title)
            terms = func.websearch_to_tsquery("english", query)
            title_rows = session.execute(
                select(IncidentRevision.incident_id)
                .where(
                    title_vector.op("@@")(terms), IncidentRevision.cutoff < hero.cutoff,
                    IncidentRevision.incident_id != hero.incident_id,
                    IncidentRevision.payload["scope"]["stage"].astext == hero.payload["scope"]["stage"],
                )
                .order_by(func.ts_rank(title_vector, terms).desc(), IncidentRevision.incident_id)
                .limit(5)
            ).scalars().all()
            title_hits = relevant.intersection(title_rows)
            retrieval.append({"query": query, "relevant": sorted(relevant), "retrieved": retrieved, "hits": sorted(hits), "title_only_retrieved": title_rows, "title_only_hits": sorted(title_hits)})
            if not hits:
                failures.append({"case": f"retrieval:{query}", "reason": "No useful precedent in top five"})
    metrics: dict[str, dict[str, int | None]] = {
        "numeric_correctness": {"passed": numeric_pass, "total": len(cases)},
        "observable_category_coverage": {"passed": category_pass, "total": len(cases)},
        "negative_case_qualification": {"passed": negative_pass, "total": sum(1 for label, _ in LABELS.values() if label is None)},
        "retrieval_hit_at_5": {"passed": sum(bool(row["hits"]) for row in retrieval), "total": len(retrieval)},
        "retrieval_recall_at_5": {"passed": sum(len(row["hits"]) for row in retrieval), "total": sum(len(row["relevant"]) for row in retrieval)},
        "ai_evidence_precision": {"passed": None, "total": 0},
    }
    model_evaluation = _recorded_model_review()
    if model_evaluation is not None:
        metrics["local_draft_validity"] = {"passed": model_evaluation["valid_drafts"], "total": model_evaluation["attempted"]}
        metrics["ai_evidence_precision"] = {"passed": model_evaluation["supported_claims"], "total": model_evaluation["reviewed_claims"]}
        failures.extend({"case": f"model:{row['id']}", "reason": row["errors"]} for row in model_evaluation["failed_cases"])
    baseline_comparison = {
        "label_revision": "retrieval-observable-v1",
        "baseline": {"configuration": "postgres-title-only", "hit_at_5": {"passed": sum(bool(row["title_only_hits"]) for row in retrieval), "total": len(retrieval)}, "recall_at_5": {"passed": sum(len(row["title_only_hits"]) for row in retrieval), "total": sum(len(row["relevant"]) for row in retrieval)}},
        "candidate": {"configuration": "postgres-visible-evidence-card", "hit_at_5": metrics["retrieval_hit_at_5"], "recall_at_5": metrics["retrieval_recall_at_5"]},
        "failed_baseline_queries": [row["query"] for row in retrieval if not row["title_only_hits"]],
        "failed_candidate_queries": [row["query"] for row in retrieval if not row["hits"]],
    }
    return {
        "id": "incident-core-v1", "dataset_revision": "authored-synthetic-10-v1",
        "label_revision": "observable-labels-v1", "configuration": "deterministic-v2+postgres-visible-card",
        "execution_kind": "live_evaluation", "case_count": len(cases),
        "metrics": metrics, "model_evaluation": model_evaluation,
        "baseline_comparison": baseline_comparison,
        "model": model_evaluation["model"] if model_evaluation else None,
        "hardware": model_evaluation["hardware"] if model_evaluation else None,
        "runtime": {"deterministic": "live", "local_model": "saved_run", "latency_seconds": model_evaluation["latency_seconds"]} if model_evaluation else {"deterministic": "live"},
        "retrieval_cases": retrieval, "cases": cases, "failures": failures,
        "limitations": [
            "Author-reviewed synthetic regression set; no factory validation.",
            "Category coverage is not causal accuracy. Historical notes do not establish line-level impact.",
            "Local-model quality uses ten packets and single-author claim review; see the failed model cases and reviewed-claim denominator." if model_evaluation else "Local-model quality has not yet been measured.",
            "The recorded local-model run used incident-v1; its ten evidence packets were checked for exact equality with incident-v2 packets after review fixes.",
            "Ten cases and three retrieval queries are too small for generalization.",
        ],
    }


def _recorded_model_review() -> dict[str, Any] | None:
    folder = Path(__file__).resolve().parents[2] / "evaluation"
    run_file = folder / "local-model-2026-09-28.json"
    review_file = folder / "human-claim-review-2026-09-28.json"
    if not run_file.exists() or not review_file.exists():
        return None
    run = json.loads(run_file.read_text())
    review = json.loads(review_file.read_text())
    labels = {row["id"]: row["supported_claim_indices"] for row in review["cases"]}
    reviewed_cases = [
        {"id": row["id"], "packet": row["packet"], "draft": row["result"]["draft"], "reviewed_supported_claim_indices": labels[row["id"]]}
        for row in run["cases"] if row["id"] in labels and row["result"]["status"] == "DRAFT_NEEDS_REVIEW"
    ]
    measured = evaluate_drafts(reviewed_cases)
    return {
        "model": run["model"], "engine_version": run.get("engine_version", "unrecorded"), "attempted": run["cases_attempted"],
        "packet_compatibility": run.get("packet_compatibility"),
        "valid_drafts": run["valid_drafts"],
        "reviewed_claims": measured["human_reviewed_claims"],
        "supported_claims": measured["human_supported_claims"],
        "latency_seconds": run["latency_seconds"], "hardware": run["hardware"],
        "external_api_expenditure_inr": run["external_api_expenditure_inr"],
        "review_rubric": review["rubric"],
        "failed_cases": [{"id": row["id"], "errors": row["result"].get("errors", [row["result"]["status"]])} for row in run["cases"] if row["result"]["status"] != "DRAFT_NEEDS_REVIEW"],
    }
