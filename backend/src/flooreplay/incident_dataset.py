"""Frozen synthetic release: observations are separate from truth and evaluation labels."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from .domain.hashing import digest

RELEASE = "incident-synthetic-180-v1"
CATEGORIES = {
    "material": "material_readiness", "machine": "machine_interruption",
    "staffing": "staffing_event", "quality": "qc_hold",
    "changeover": "setup_changeover", "planning_reporting": "reporting_correction",
}
# Authored evidence structures, rather than paraphrases of a causal explanation.
STRUCTURES = {
    "historical": ("documented-block", "unsuccessful-intervention"),
    "development": ("unconfirmed-source-assertion",),
    "locked": ("conflicting-observation",),
}


def _stamp(day: int, minute: int) -> str:
    return (datetime(2026, 6, 1, 9, tzinfo=UTC) + timedelta(days=day, minutes=minute)).isoformat()


def build_dataset() -> dict[str, Any]:
    episodes: list[dict[str, Any]] = []
    labels: list[dict[str, Any]] = []
    truth: list[dict[str, Any]] = []
    templates: list[dict[str, Any]] = []
    serial = 0
    for category, event_type in CATEGORIES.items():
        for split, structures in STRUCTURES.items():
            count = 10 if split == "historical" else 5
            for structure in structures:
                template_id = f"{split}-{category}-{structure}"
                templates.append({"id": template_id, "category": category, "split": split, "structure": structure, "review": "generator author structural review; independent semantic review pending"})
                for variant in range(count):
                    serial += 1
                    incident_id = f"REL-{serial:03d}"
                    # Distinct lots, counts, reporting delays, block shapes, and source availability.
                    day = serial % 25
                    target = 20 + variant * 2
                    actual = [target - (variant % 4 + 2), target - 7, target, target - 1]
                    scope = {"factory": "Synthetic Factory Release", "line_id": "S4", "order_id": f"ORDER-{serial}", "style_id": f"STYLE-{variant % 3}", "stage": "sewing", "unit": "good_units"}
                    plans = [{"id": f"{incident_id}-p{i}", "kind": "baseline_plan", "start": _stamp(day, 15 * i), "end": _stamp(day, 15 * (i + 1)), "available_at": _stamp(day, -60), "quantity": target} for i in range(4)]
                    outputs = [{**plan, "id": f"{incident_id}-o{i}", "kind": "final_good_delta", "quantity": actual[i], "available_at": _stamp(day, 15 * (i + 1) + variant % 3)} for i, plan in enumerate(plans)]
                    event_id = f"{incident_id}-event"
                    event = {"id": event_id, "type": event_type, "lane": category, "summary": f"Source reports {category.replace('_', ' ')} concern affecting order {serial}; line effect needs verification.", "start": _stamp(day, 5 + variant), "end": _stamp(day, 20 + variant), "available_at": _stamp(day, 25), "source_id": f"{incident_id}-shift-log", "assertion": True}
                    events: list[dict[str, Any]] = [event]
                    mode = variant % 5
                    cutoff_minute = 65
                    expected_status = "COMPLETE"
                    expected_shortfall: int | None = sum(target - q for q in actual)
                    expected_category_status = "PLAUSIBLE"
                    if structure in {"documented-block", "unsuccessful-intervention"}:
                        events.append({"id": f"{incident_id}-block", "type": "line_block", "lane": "production", "summary": f"Supervisor recorded an explicit line stop while checking {category.replace('_', ' ')} readiness.", "start": _stamp(day, 5), "end": _stamp(day, 15 + variant), "available_at": _stamp(day, 25), "line_blocking": True, "source_id": f"{incident_id}-block-log", "hypothesis_links": [{"category": category, "relation": "SUPPORTS", "source_id": f"{incident_id}-block-log"}]})
                        expected_category_status = "SUPPORTED"
                        if structure == "unsuccessful-intervention":
                            events.append({"id": f"{incident_id}-action", "type": "routine_note", "lane": "notes", "summary": "A previous intervention was attempted without restoring the planned output rate; its prerequisites differ from the current order.", "occurred_at": _stamp(day, 35), "available_at": _stamp(day, 36), "source_id": f"{incident_id}-action-log", "action_outcome": "UNSUCCESSFUL", "action_prerequisites": ["different order and material lot", "maintenance/QC clearance"]})
                    elif structure == "conflicting-observation":
                        events.append({"id": f"{incident_id}-counter", "type": "routine_note", "lane": "notes", "summary": f"Independent source disputes the {category.replace('_', ' ')} observation; verification remains open.", "occurred_at": _stamp(day, 18), "available_at": _stamp(day, 30), "source_id": f"{incident_id}-counter-log", "contradiction_refs": [event_id]})
                        expected_category_status = "CONTRADICTED"
                    # Variation changes available evidence shape, not only names.
                    no_precedent = False
                    if mode == 0 and split != "historical":
                        # Healthy negative case with irrelevant historical context.
                        outputs = [{**output, "quantity": target} for output in outputs]
                        events = [{**event, "start": _stamp(day, -50), "end": _stamp(day, -30), "available_at": _stamp(day, -20), "summary": "Prior resolved issue; no current-window concern reported."}]
                        if split == "locked":
                            events = []
                        expected_shortfall = 0
                        expected_category_status = "ABSENT"
                        no_precedent = True
                    elif mode == 1:
                        # Missing output is a gap, never an inferred zero.
                        outputs.pop(1)
                        expected_status = "PARTIAL"
                        expected_shortfall = None
                    elif mode == 2:
                        # Early cutoff excludes final bucket and its later availability.
                        cutoff_minute = 47
                        expected_shortfall = sum(target - q for q in actual[:3])
                        events.append({"id": f"{incident_id}-later", "type": "maintenance_note", "lane": "notes", "summary": "Later resolution cannot enter the earlier investigation.", "occurred_at": _stamp(day, 15), "available_at": _stamp(day, 90), "source_id": f"{incident_id}-late-log"})
                    elif mode == 3:
                        # Valid correction preserves raw count history.
                        outputs.append({**outputs[0], "id": f"{incident_id}-corrected", "supersedes_id": outputs[0]["id"], "quantity": target - 1, "available_at": _stamp(day, 40)})
                        expected_shortfall = 1 + sum(target - q for q in actual[1:])
                    elif mode == 4:
                        # Competing corrections prevent a definitive accounting result.
                        outputs.extend({**outputs[0], "id": f"{incident_id}-competing-{n}", "supersedes_id": outputs[0]["id"], "quantity": target - n, "available_at": _stamp(day, 40 + n)} for n in (1, 2))
                        expected_status = "CONFLICTING"
                        expected_shortfall = None
                    episode = {"id": incident_id, "revision": 1, "title": f"Synthetic {category.replace('_', ' ')} investigation {serial}", "scope": scope, "window": {"start": _stamp(day, 0), "end": _stamp(day, 60)}, "cutoff": _stamp(day, cutoff_minute), "plan_buckets": plans, "output_buckets": outputs, "events": events, "coverage": {"production": True, "operations": True}, "dataset_split": split, "lineage_id": f"lineage-{incident_id}", "template_id": template_id, "dataset_release": RELEASE, "provenance": "authored synthetic generator; no factory observations"}
                    episodes.append(episode)
                    truth.append({"id": incident_id, "underlying_category": category if not no_precedent else None, "later_resolution": "Synthetic world state only; withheld from available observations", "structure": structure})
                    if split != "historical":
                        labels.append({"id": incident_id, "split": split, "production_status": expected_status, "shortfall": expected_shortfall, "category": category, "category_status": expected_category_status, "no_precedent": no_precedent, "relevant_incident_ids": [], "query": "healthy normal production without unresolved concerns" if no_precedent else f"{category.replace('_', ' ')} line readiness concern", "review": "generator author arithmetic/structure review; semantic support review pending"})
    for label in labels:
        if not label["no_precedent"]:
            label["relevant_incident_ids"] = [episode["id"] for episode in episodes if episode["dataset_split"] == "historical" and episode["template_id"].split("-", 2)[1] == label["category"] and episode["cutoff"] < next(item["cutoff"] for item in episodes if item["id"] == label["id"])]
    manifest = {"release": RELEASE, "splits": {split: [{"id": row["id"], "lineage_id": row["lineage_id"], "template_id": row["template_id"], "digest": digest(row)} for row in episodes if row["dataset_split"] == split] for split in STRUCTURES}, "templates": templates, "labels_digest": digest(labels), "observations_digest": digest(episodes), "locked_labels_frozen": True, "limitations": ["Synthetic scenarios with authored procedural generation, not real manufacturing data", "Generator author review only; no manufacturing expert annotation", "Independent semantic support review pending", "Category-level retrieval labels test precedent topic relevance, not transferability of historical actions"]}
    return {"manifest": manifest, "episodes": episodes, "labels": labels, "hidden_truth": truth}


def dataset_fixtures() -> list[dict[str, Any]]:
    episodes: list[dict[str, Any]] = build_dataset()["episodes"]
    return episodes
