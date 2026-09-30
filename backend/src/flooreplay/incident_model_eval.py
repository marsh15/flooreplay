"""Staged explicit owner evaluation through the shared durable paid path."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from . import openai_provider
from .ai_runs import lookup_run, run_ai
from .config import settings
from .dataset_evaluation import evaluate_dataset
from .db import session_scope
from .incident_dataset import build_dataset
from .incident_service import create_analysis


def run(path: Path, user_id: str, stage: str = "smoke", retrieval_mode: str = "evidence_only", corpus_id: str | None = None) -> dict[str, Any]:
    if stage not in {"smoke", "pilot", "locked"}:
        raise ValueError("Unknown evaluation stage")
    dataset = build_dataset()
    if evaluate_dataset(dataset)["status"] != "PASSED":
        raise ValueError("Frozen dataset failed integrity checks")
    config = openai_provider.configuration(settings.openai_generation_model, settings.openai_embedding_model, settings.openai_embedding_dimensions)
    config_digest = hashlib.sha256(json.dumps([config, retrieval_mode, corpus_id], sort_keys=True).encode()).hexdigest()
    previous = "smoke" if stage == "pilot" else "pilot"
    if stage != "smoke":
        previous_path = path.parent / f"openai-{previous}.json"
        if not previous_path.exists():
            raise ValueError(f"Run the {previous} stage before {stage}")
        prior = json.loads(previous_path.read_text())
        required_count = 5 if previous == "smoke" else 10
        counts = prior.get("denominators", {})
        cases = prior.get("cases", [])
        predecessor_complete = (
            prior.get("status") == "MEASURED_STRUCTURAL_ONLY"
            and counts.get("planned_cases") == required_count
            and counts.get("attempted_cases") == required_count
            and counts.get("valid_runs") == required_count
            and len(cases) == required_count
            and all(case.get("status") == "COMPLETED" and any(attempt.get("provider_verified") is True for attempt in case.get("attempts", [])) for case in cases)
        )
        if not predecessor_complete or prior.get("blocking_defects") or prior.get("execution_configuration_digest") != config_digest or prior.get("dataset_manifest") != dataset["manifest"]:
            raise ValueError("Prior stage has blocking defects or differs from frozen execution/dataset configuration")
    split = "locked" if stage == "locked" else "development"
    count = {"smoke": 5, "pilot": 10, "locked": 30}[stage]
    episodes = [episode for episode in dataset["episodes"] if episode["dataset_split"] == split][:count]
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        checkpoint: dict[str, Any] = json.loads(path.read_text())
        if not isinstance(checkpoint, dict):
            raise ValueError("Evaluation checkpoint must be an object")
        if checkpoint.get("stage") != stage or checkpoint.get("execution_configuration_digest") != config_digest or checkpoint.get("dataset_manifest") != dataset["manifest"]:
            raise ValueError("Existing evaluation has another frozen identity; select a new output directory")
        if checkpoint.get("blocking_defects"):
            return checkpoint
        results = checkpoint["cases"]
        evaluation_id = checkpoint["evaluation_id"]
    else:
        results = []
        evaluation_id = str(uuid4())
        checkpoint = {"schema":"flooreplay.openai-evaluation.v2", "stage":stage, "evaluation_id":evaluation_id, "dataset_manifest":dataset["manifest"], "execution_configuration_digest":config_digest, "status":"IN_PROGRESS", "blocking_defects":[], "cases":[]}
        path.write_text(json.dumps(checkpoint, indent=2) + "\n")
    if len(results) == count:
        return checkpoint
    summary: dict[str, Any] = checkpoint
    for episode in episodes[len(results):]:
        with session_scope() as session:
            analysis = create_analysis(session, episode["id"], 1, f"openai-eval-{evaluation_id}-{episode['id']}")
            analysis_id = analysis.id
        result = run_ai(analysis_id, user_id, f"eval-{evaluation_id}-{episode['id']}", "investigation", "Investigate supported explanations, counterevidence, missing observations, and next checks.", "evaluation", retrieval_mode, corpus_id)
        if result["status"] == "RUNNING":
            result = lookup_run(result["id"], user_id)
        results.append(result)
        failures = [item["id"] for item in results if item["status"] != "COMPLETED"]
        summary = {"schema": "flooreplay.openai-evaluation.v2", "stage": stage, "evaluation_id": evaluation_id, "provider": "openai", "status": "BLOCKED" if failures else "MEASURED_STRUCTURAL_ONLY", "dataset_manifest": dataset["manifest"], "execution_configuration": config, "execution_configuration_digest": config_digest, "retrieval_mode": retrieval_mode, "corpus_id": corpus_id, "denominators": {"planned_cases": count, "attempted_cases": len(results), "valid_runs": sum(item["status"] == "COMPLETED" for item in results)}, "blocking_defects": failures, "semantic_support": None, "human_review_status": "PENDING", "limitations": ["Citation membership does not establish semantic support", "Human support labels require separate review", "Dataset generator-author review is not independent semantic review"], "cases": results}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(summary, indent=2) + "\n")
        if failures:
            break
    return summary
