from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from flooreplay.trust_evaluation import (
    compare,
    import_generation,
    run_deterministic,
    verify_release,
)

RELEASE = Path(__file__).parents[1] / "evaluation" / "ai-trust-fresh-v1"


def test_frozen_cases_execute_and_unrequested_ai_is_pending(tmp_path):
    ledger = tmp_path / "receipts.jsonl"
    result = run_deterministic(RELEASE, ledger)
    assert len(result) == 10
    assert run_deterministic(RELEASE, ledger) == result
    comparison = compare(RELEASE, ledger)
    assert comparison["measured"] == 10 and comparison["expected"] == 40
    assert len([row for row in comparison["rows"] if row["status"] == "PENDING"]) == 30
    assert all(row["semantic_review"] is None for row in comparison["rows"])


def test_case_tampering_is_not_accepted(tmp_path):
    copied = tmp_path / "release"
    shutil.copytree(RELEASE, copied)
    path = copied / "inputs.json"
    path.write_text(path.read_text() + " ")
    with pytest.raises(ValueError, match="Frozen file digest"):
        verify_release(copied)


def _receipt(tmp_path):
    manifest = verify_release(RELEASE)
    path = tmp_path / "test-only-receipt.json"
    body = {"case_id": "FRESH-01", "case_digest": manifest["case_digests"]["FRESH-01"],
            "mode": "evidence_only", "run_id": "test-only-run", "provider": "test-double",
            "model": "test-only", "source_receipt": {"id": "test-only"},
            "output": {"claims": [{"text": "Test claim"}]}, "latency_ms": 4,
            "cost_inr": None, "semantic_review": None}
    path.write_text(json.dumps(body))
    return path, body


def test_receipt_import_keeps_unknown_cost_and_support_unknown(tmp_path):
    path, _ = _receipt(tmp_path)
    ledger = tmp_path / "ledger.jsonl"
    result = import_generation(RELEASE, ledger, path)
    assert result["claim_count"] == 1
    assert result["cost_inr"] is None and result["semantic_review"] is None
    assert import_generation(RELEASE, ledger, path) == result
    assert compare(RELEASE, ledger)["measured"] == 1


def test_changed_generation_cannot_replace_saved_result(tmp_path):
    path, body = _receipt(tmp_path)
    ledger = tmp_path / "ledger.jsonl"
    import_generation(RELEASE, ledger, path)
    body["output"] = {"claims": []}
    path.write_text(json.dumps(body))
    with pytest.raises(ValueError, match="immutable receipt"):
        import_generation(RELEASE, ledger, path)


def test_wrong_case_and_fabricated_semantic_labels_rejected(tmp_path):
    path, body = _receipt(tmp_path)
    body["case_digest"] = "wrong"
    path.write_text(json.dumps(body))
    with pytest.raises(ValueError, match="different frozen case"):
        import_generation(RELEASE, tmp_path / "ledger.jsonl", path)
    body["case_digest"] = verify_release(RELEASE)["case_digests"]["FRESH-01"]
    body["semantic_review"] = {"supported": True}
    path.write_text(json.dumps(body))
    with pytest.raises(ValueError, match="independent human"):
        import_generation(RELEASE, tmp_path / "ledger.jsonl", path)


def test_human_packet_preserves_actual_smoke_outputs_and_no_human_labels():
    from flooreplay.domain.hashing import digest

    evaluation = RELEASE.parent
    source = json.loads((evaluation / 'openai-live-evidence-v4/openai-smoke.json').read_text())
    packet = json.loads((evaluation / 'openai-smoke-review-packet-v1/human-review-packet.json').read_text())
    by_id = {case['id']: case for case in source['cases']}
    assert packet['denominators'] == {'cases': 5, 'structured_claims': 4, 'text_units': 28, 'next_checks': 6}
    assert packet['human_reviewed_cases'] == 0 and packet['human_reviewed_claims'] == 0
    for item in packet['cases']:
        original = by_id[item['run_id']]
        assert item['output'] == original['result']['output']
        assert item['output_digest'] == digest(original['result']['output'])
        assert item['packet_digest'] == digest(original['packet'])
        assert item['attempts'] == original['attempts']
        assert item['human_judgments'] is None
        evidence = {record['id']: record for record in original['packet']['evidence']}
        for claim in item['structured_claims']:
            assert claim['cited_records'] == [evidence[ref] for ref in claim['claim']['evidence_ids']]
