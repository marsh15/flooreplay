"""Pinned AI packet construction; provider operations run in the API process."""
from __future__ import annotations

from typing import Any

from .models import IncidentAnalysis


def _packet(analysis: IncidentAnalysis) -> dict[str, Any]:
    report = analysis.report
    evidence = [dict(event) for event in report.get("timeline", [])]
    metrics = report.get("metrics", {}).get("descriptors", [])
    if not metrics:
        unit = report.get("metrics", {}).get("unit", "good units")
        metrics = [{"id": key, "value": value, "unit": "minutes" if key == "blocked_minutes" else unit, "formula": key, "input_refs": report.get("metric_inputs", []), "interval": report.get("window", {})} for key, value in report.get("metrics", {}).items() if key in {"planned", "observed", "shortfall", "variance", "blocked_minutes", "baseline_target"} and isinstance(value, (int, float))]
    return {"incident_id": analysis.incident_id, "revision": analysis.revision, "analysis_digest": analysis.manifest_digest, "scope": report.get("scope"), "cutoff": report.get("cutoff"), "observation_watermark": report.get("observation_watermark"), "evidence": evidence, "metrics": metrics, "hypotheses": report.get("hypotheses", []), "missing_evidence": report.get("capabilities", {}), "action_catalog": report.get("proposals", []), "historical_evidence": [], "retrieval_manifest": {"mode": "evidence_only"}}
