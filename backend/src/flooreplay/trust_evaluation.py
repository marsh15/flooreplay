"""Frozen challenge cases and offline adapters for actual comparison receipts."""
from __future__ import annotations

import fcntl
import json
import math
from hashlib import sha256
from pathlib import Path
from time import perf_counter
from typing import Any

from .incident_engine import analyze_incident

MODES = ("deterministic", "evidence_only", "lexical", "hybrid")


def _digest(value: Any) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def verify_release(release_dir: Path) -> dict[str, Any]:
    manifest: dict[str, Any] = json.loads((release_dir / "manifest.json").read_text())
    if manifest.get("schema") != "flooreplay.fresh-trust.v1" or not manifest.get("frozen"):
        raise ValueError("Expected a frozen fresh-trust manifest")
    for filename, expected in manifest["files"].items():
        if Path(filename).name != filename or sha256((release_dir / filename).read_bytes()).hexdigest() != expected:
            raise ValueError(f"Frozen file digest mismatch: {filename}")
    cases = json.loads((release_dir / "inputs.json").read_text())
    ids = [case["case_id"] for case in cases]
    if len(ids) != manifest["case_count"] or len(ids) != len(set(ids)):
        raise ValueError("Case identity/count mismatch")
    if {case["case_id"]: _digest(case) for case in cases} != manifest["case_digests"]:
        raise ValueError("Frozen case digest mismatch")
    return manifest


def _append(ledger_path: Path, receipt: dict[str, Any]) -> dict[str, Any]:
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    receipt = {**receipt, "receipt_digest": _digest(receipt)}
    with ledger_path.open("a+", encoding="utf-8") as file:
        fcntl.flock(file, fcntl.LOCK_EX)
        file.seek(0)
        for line in file:
            old = json.loads(line)
            if old["case_id"] == receipt["case_id"] and old["mode"] == receipt["mode"]:
                if old == receipt or (receipt["mode"] == "deterministic" and old["run_id"] == receipt["run_id"] and old["output_digest"] == receipt["output_digest"]):
                    return dict(old)
                raise ValueError("Case/mode already has an immutable receipt; use a new comparison ledger")
        file.write(json.dumps(receipt, sort_keys=True) + "\n")
        file.flush()
    return receipt


def _rows(release_dir: Path) -> list[dict[str, Any]]:
    verify_release(release_dir)
    result: list[dict[str, Any]] = json.loads((release_dir / "inputs.json").read_text())
    return result


def run_deterministic(release_dir: Path, ledger_path: Path) -> list[dict[str, Any]]:
    receipts = []
    for case in _rows(release_dir):
        started = perf_counter()
        report = analyze_incident(case["incident"])
        elapsed = (perf_counter() - started) * 1000
        receipts.append(_append(ledger_path, {
            "case_id": case["case_id"], "case_digest": _digest(case), "mode": "deterministic",
            "run_id": f'deterministic:{_digest(case)}', "provider": None, "model": None,
            "output": report, "output_digest": _digest(report), "status": "MEASURED",
            "latency_ms": elapsed, "cost_inr": 0, "source_receipt": None,
            "claim_count": None, "semantic_review": None, "error": None,
        }))
    return receipts


def claim_paths(output: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    for key in ("claims", "findings", "actions", "sentences"):
        if isinstance(output.get(key), list):
            paths.extend(f"{key}.{index}" for index in range(len(output[key])))
    if isinstance(output.get("hypotheses"), list):
        paths.extend(f"hypotheses.{index}.explanation" for index, item in enumerate(output["hypotheses"]) if isinstance(item, dict) and isinstance(item.get("explanation"), dict))
    if isinstance(output.get("assertion"), dict):
        paths.append("assertion")
    return paths


def import_generation(release_dir: Path, ledger_path: Path, receipt_path: Path) -> dict[str, Any]:
    """Import an actual stored generation/error; this function never contacts a provider."""
    manifest = verify_release(release_dir)
    receipt: dict[str, Any] = json.loads(receipt_path.read_text())
    case_id, mode = receipt.get("case_id"), receipt.get("mode")
    if case_id not in manifest["case_digests"] or mode not in MODES[1:]:
        raise ValueError("Unknown case or AI comparison mode")
    if receipt.get("case_digest") != manifest["case_digests"][case_id]:
        raise ValueError("Generation used a different frozen case")
    for field in ("run_id", "provider", "model", "source_receipt"):
        if not receipt.get(field):
            raise ValueError(f"Actual generation requires {field}")
    for field in ("latency_ms", "cost_inr"):
        value = receipt.get(field)
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0):
            raise ValueError(f"{field} must be measured nonnegative numeric data or null")
    output = receipt.get("output")
    if not isinstance(output, dict) and not receipt.get("error"):
        raise ValueError("Provide actual output or a recorded error")
    if receipt.get("semantic_review") is not None:
        raise ValueError("Semantic labels belong in an independent human review file")
    normalized = {**receipt, "source_file_digest": sha256(receipt_path.read_bytes()).hexdigest(),
                  "output_digest": _digest(output), "status": "ERROR" if receipt.get("error") else "MEASURED",
                  "claim_count": len(claim_paths(output)) if isinstance(output, dict) else 0,
                  "semantic_review": None, "latency_ms": receipt.get("latency_ms"),
                  "cost_inr": receipt.get("cost_inr"), "error": receipt.get("error"),
                  "output": output}
    return _append(ledger_path, normalized)


def compare(release_dir: Path, ledger_path: Path) -> dict[str, Any]:
    manifest = verify_release(release_dir)
    measured = {}
    if ledger_path.exists():
        for line in ledger_path.read_text().splitlines():
            row = json.loads(line)
            digest = row.pop("receipt_digest")
            if _digest(row) != digest or row["case_digest"] != manifest["case_digests"].get(row["case_id"]):
                raise ValueError("Receipt ledger integrity mismatch")
            identity = (row["case_id"], row["mode"])
            if row["mode"] not in MODES or row["output_digest"] != _digest(row.get("output")):
                raise ValueError("Invalid mode or output digest")
            if identity in measured:
                raise ValueError("Duplicate comparison receipt")
            measured[identity] = {**row, "receipt_digest": digest}
    rows = [{"case_id": case_id, "mode": mode, **measured.get((case_id, mode), {
        "status": "PENDING", "run_id": None, "latency_ms": None, "cost_inr": None,
        "claim_count": None, "semantic_review": None,
    })} for case_id in manifest["case_digests"] for mode in MODES]
    summaries = {}
    for mode in MODES:
        selected = [row for row in rows if row["mode"] == mode]
        executed = [row for row in selected if row["status"] != "PENDING"]
        latencies = [row["latency_ms"] for row in executed if row.get("latency_ms") is not None]
        costs = [row["cost_inr"] for row in executed if row.get("cost_inr") is not None]
        counts = [row["claim_count"] for row in executed if row.get("claim_count") is not None]
        summaries[mode] = {
            "executed": len(executed), "planned": len(selected),
            "errors": sum(row["status"] == "ERROR" for row in executed),
            "latency_measured_runs": len(latencies),
            "mean_latency_ms": sum(latencies) / len(latencies) if latencies else None,
            "cost_measured_runs": len(costs), "known_cost_total_inr": sum(costs) if costs else None,
            "claim_denominator": sum(counts) if counts else None,
            "human_reviewed_claims": 0, "semantic_support_rate": None,
        }
    return {"schema": "flooreplay.trust-comparison.v1", "release": manifest["release"],
            "manifest_digest": sha256((release_dir / "manifest.json").read_bytes()).hexdigest(),
            "rows": rows, "by_mode": summaries,
            "measured": sum(row["status"] != "PENDING" for row in rows),
            "expected": len(rows), "semantic_review": None,
            "limitation": "Recorded structure and receipts do not establish semantic support; AI modes remain pending until actual receipts are imported."}



def review_packet(release_dir: Path, ledger_path: Path) -> dict[str, Any]:
    """Prepare exact outputs and current evidence for independent human assessment."""
    cases = {case["case_id"]: case for case in _rows(release_dir)}
    comparison = compare(release_dir, ledger_path)
    items = []
    for row in comparison["rows"]:
        if row["mode"] == "deterministic" or row["status"] == "PENDING":
            continue
        items.append({
            "case_id": row["case_id"], "case_digest": row["case_digest"],
            "mode": row["mode"], "run_id": row["run_id"], "provider": row["provider"],
            "model": row["model"], "output_digest": row["output_digest"],
            "output": row.get("output"), "error": row.get("error"),
            "claim_paths": claim_paths(row["output"]) if isinstance(row.get("output"), dict) else [],
            "current_evidence": cases[row["case_id"]]["incident"],
            "source_receipt": row["source_receipt"],
            "reviewer_identity": None, "reviewer_qualifications": None,
            "judgments": None,
        })
    return {"schema": "flooreplay.human-review-packet.v1", "release": comparison["release"],
            "manifest_digest": comparison["manifest_digest"], "items": items,
            "blind_rubric_included": False, "human_review_status": "PENDING",
            "instructions": "Inspect each exact claim and cited current/historical records. Preserve independent judgments, qualifications and disagreements. No human labels are supplied."}


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["verify", "deterministic", "import", "report", "review-packet"])
    parser.add_argument("--release", type=Path, default=Path("evaluation/ai-trust-fresh-v1"))
    parser.add_argument("--ledger", type=Path, default=Path("evaluation/ai-trust-fresh-v1/results.jsonl"))
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    if args.operation == "verify":
        result: Any = verify_release(args.release)
    elif args.operation == "deterministic":
        result = run_deterministic(args.release, args.ledger)
    elif args.operation == "import":
        if args.receipt is None:
            parser.error("import requires --receipt")
        result = import_generation(args.release, args.ledger, args.receipt)
    elif args.operation == "review-packet":
        result = review_packet(args.release, args.ledger)
    else:
        result = compare(args.release, args.ledger)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
