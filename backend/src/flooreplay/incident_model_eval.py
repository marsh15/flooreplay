"""Run ten pinned synthetic packets through the local Ollama draft path."""

from __future__ import annotations

import json
import math
import platform
import subprocess
import time
from pathlib import Path
from statistics import median
from typing import Any

from .config import settings
from .db import session_scope
from .incident_ai import draft_with_ollama, evaluate_drafts
from .incident_jobs import _packet
from .incident_service import create_analysis

CASES = [("INC-001", 1), ("INC-001", 2), *[(f"INC-{i}", 1) for i in range(101, 109)]]


def run(path: Path) -> dict[str, Any]:
    results = []
    for incident_id, revision in CASES:
        with session_scope() as session:
            analysis = create_analysis(session, incident_id, revision, f"local-model-eval-{incident_id}-{revision}-v1")
            packet = _packet(analysis)
        started = time.monotonic()
        result = draft_with_ollama(packet, model=settings.local_model)
        seconds = round(time.monotonic() - started, 2)
        results.append({"id": f"{incident_id}@{revision}", "packet": packet, "result": result, "elapsed_seconds": seconds})
        print(f"{incident_id}@{revision}: {result['status']} in {seconds}s", flush=True)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(_summary(results), indent=2, ensure_ascii=False) + "\n")
    return _summary(results)


def _summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    valid = [{"id": item["id"], "packet": item["packet"], "draft": item["result"]["draft"]} for item in results if item["result"]["status"] == "DRAFT_NEEDS_REVIEW"]
    metrics = evaluate_drafts(valid)
    elapsed = sorted(item["elapsed_seconds"] for item in results)
    memory_gib = None
    if platform.system() == "Darwin":
        measured = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, check=False)
        if measured.returncode == 0:
            memory_gib = round(int(measured.stdout.strip()) / (1024 ** 3), 1)
    return {
        "schema": "flooreplay.local-model-evaluation.v1", "engine_version": "incident-v2", "model": settings.local_model,
        "hardware": {"machine": platform.machine(), "system": platform.system(), "memory_gib": memory_gib},
        "external_api_expenditure_inr": 0,
        "cases_attempted": len(results), "valid_drafts": len(valid),
        "citation_validation": metrics,
        "latency_seconds": {"p50": round(median(elapsed), 2) if elapsed else None, "p95": elapsed[math.ceil(0.95 * len(elapsed)) - 1] if elapsed else None},
        "limitations": ["Synthetic packets only", "Citation membership does not establish semantic support", "Human claim review is recorded separately"],
        "cases": results,
    }


if __name__ == "__main__":
    run(Path("evaluation/local-model-2026-09-28.json"))
