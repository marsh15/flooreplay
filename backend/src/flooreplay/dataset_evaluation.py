"""Offline release integrity and independently declared arithmetic expectations."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .domain.hashing import digest
from .incident_dataset import build_dataset
from .incident_engine import analyze_incident


def evaluate_dataset(dataset: dict[str, Any] | None = None) -> dict[str, Any]:
    dataset = dataset or build_dataset()
    manifest = dataset["manifest"]
    episodes = dataset["episodes"]
    labels = dataset["labels"]
    by_id = {row["id"]: row for row in episodes}
    problems = []
    counts = {split: sum(row["dataset_split"] == split for row in episodes) for split in ("historical", "development", "locked")}
    if counts != {"historical": 120, "development": 30, "locked": 30}:
        problems.append("Split counts differ from release contract")
    if len(by_id) != 180 or len(labels) != 60:
        problems.append("Expected 180 unique episodes and 60 investigation labels")
    split_templates = {split: {row["template_id"] for row in episodes if row["dataset_split"] == split} for split in counts}
    split_lineages = {split: {row["lineage_id"] for row in episodes if row["dataset_split"] == split} for split in counts}
    for left, right in (("historical", "development"), ("historical", "locked"), ("development", "locked")):
        if split_templates[left] & split_templates[right] or split_lineages[left] & split_lineages[right]:
            problems.append(f"Template or lineage leakage between {left} and {right}")
    if any(set(row) & {"hidden_truth", "later_resolution", "evaluation_labels", "category_status", "relevant_incident_ids"} for row in episodes):
        problems.append("Hidden labels or world state entered runtime observations")
    if manifest["labels_digest"] != digest(labels) or manifest["observations_digest"] != digest(episodes):
        problems.append("Frozen release content digest differs")
    checked = 0
    for label in labels:
        episode = by_id[label["id"]]
        report = analyze_incident(episode)
        actual_category = next((item["status"] for item in report["hypotheses"] if item["category"] == label["category"]), "ABSENT")
        if (report["metrics"]["status"], report["metrics"]["shortfall"], actual_category) != (label["production_status"], label["shortfall"], label["category_status"]):
            problems.append(f"Accounting/hypothesis expectation failed: {label['id']}")
        if label["no_precedent"] and label["relevant_incident_ids"]:
            problems.append(f"Negative precedent case has relevance labels: {label['id']}")
        for precedent in label["relevant_incident_ids"]:
            candidate = by_id.get(precedent)
            if candidate is None or candidate["dataset_split"] != "historical" or candidate["cutoff"] >= episode["cutoff"]:
                problems.append(f"Ineligible precedent: {label['id']} -> {precedent}")
        checked += 1
    return {"release": manifest["release"], "status": "PASSED" if not problems else "FAILED", "split_counts": counts, "authored_templates": len(manifest["templates"]), "arithmetic_and_structure_cases_checked": checked, "leakage_audit": "template/lineage identities and hidden-field separation; semantic paraphrase audit remains pending", "problems": problems, "limitations": manifest["limitations"]}


def export_dataset(directory: Path) -> dict[str, Any]:
    dataset = build_dataset()
    validation = evaluate_dataset(dataset)
    if validation["problems"]:
        raise ValueError("Dataset validation failed: " + "; ".join(validation["problems"]))
    directory.mkdir(parents=True, exist_ok=True)
    for name, value in (("manifest", dataset["manifest"]), ("observations", dataset["episodes"]), ("labels", dataset["labels"]), ("hidden-world-state", dataset["hidden_truth"]), ("validation", validation)):
        (directory / f"{name}.json").write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    return validation


validate_dataset = evaluate_dataset
