from __future__ import annotations

import json
from urllib.error import URLError

from flooreplay import incident_ai

PACKET = {
    "incident_id": "hero",
    "cutoff": "2026-09-28T11:00:00+05:30",
    "evidence": [{"id": "E1", "text": "Line start recorded late."}],
    "metrics": [{"id": "M1", "value": 12, "unit": "good units", "formula": "plan - output"}],
    "contradictions": ["Maintenance note was recorded after cutoff."],
}
GOOD = {"claims": [{"text": "The shortfall is 12 good units.", "evidence_ids": [], "metric_ids": ["M1"]}], "limitations": ["The reason for the shortfall is unresolved."]}


def test_citation_and_numeric_guards():
    assert incident_ai.validate_draft(GOOD, PACKET)["valid"]
    fabricated = {"claims": [{"text": "The line lost 20 units.", "evidence_ids": ["E1"], "metric_ids": ["M1"]}], "limitations": []}
    assert not incident_ai.validate_draft(fabricated, PACKET)["valid"]
    assert not incident_ai.validate_draft({"claims": "not a list", "limitations": []}, PACKET)["valid"]
    fabricated["claims"][0] = {"text": "Line started late.", "evidence_ids": ["E2"], "metric_ids": []}
    assert not incident_ai.validate_draft(fabricated, PACKET)["valid"]
    fabricated["claims"][0]["evidence_ids"] = []
    assert not incident_ai.validate_draft(fabricated, PACKET)["valid"]


def test_cited_source_time_and_lot_code_are_not_metrics():
    packet = {**PACKET, "evidence": [{"id": "E1", "summary": "Lot F-218 arrived at 09:32."}]}
    draft = {"claims": [{"text": "Lot F-218 arrived at 09:32.", "evidence_ids": ["E1"], "metric_ids": []}], "limitations": []}
    assert incident_ai.validate_draft(draft, packet)["valid"]
    draft["claims"][0]["metric_ids"] = ["M1"]
    assert incident_ai.validate_draft(draft, packet)["claims"][0]["metric_ids"] == []


def test_local_drafting_and_single_repair(monkeypatch):
    calls = []

    def fake_post(path, payload, *, endpoint, timeout):
        calls.append(payload)
        assert path == "/api/chat"
        assert payload["think"] is False
        assert payload["options"]["num_ctx"] == 4096
        assert timeout > 0
        if len(calls) == 1:
            return {"message": {"content": json.dumps({"claims": [{"text": "Fabric caused 20 lost units", "evidence_ids": ["E404"], "metric_ids": []}], "limitations": []})}}
        return {"model": "qwen3:4b", "message": {"content": json.dumps(GOOD)}, "prompt_eval_count": 150, "eval_count": 30}

    monkeypatch.setattr(incident_ai, "_post_local", fake_post)
    monkeypatch.setattr(incident_ai, "_model_digest", lambda *args, **kwargs: "sha256:123")
    result = incident_ai.draft_with_ollama(PACKET)
    assert result["status"] == "DRAFT_NEEDS_REVIEW"
    assert result["attempts"] == 2
    assert result["validation"]["valid"]
    assert result["model_digest"] == "sha256:123"
    assert "contradictions" in calls[0]["messages"][1]["content"]


def test_local_failure_does_not_return_a_draft(monkeypatch):
    def fail(*args, **kwargs):
        raise URLError("offline")

    monkeypatch.setattr(incident_ai, "_post_local", fail)
    result = incident_ai.draft_with_ollama(PACKET)
    assert result["status"] == "AI_UNAVAILABLE"
    assert "draft" not in result


def test_packet_limit_fails_before_model_call(monkeypatch):
    def unexpected(*args, **kwargs):
        raise AssertionError("Model should not receive oversized packet")

    monkeypatch.setattr(incident_ai, "_post_local", unexpected)
    oversized = {**PACKET, "evidence": [{"id": "E1", "text": "x" * 17_000}]}
    try:
        incident_ai.draft_with_ollama(oversized)
    except ValueError as exc:
        assert "narrow the task" in str(exc)
    else:
        raise AssertionError("Oversized packet accepted")


def test_endpoint_is_loopback_only():
    try:
        incident_ai._post_local("/api/chat", {}, endpoint="https://api.example.com", timeout=1)
    except ValueError as exc:
        assert "local HTTP" in str(exc)
    else:
        raise AssertionError("Remote endpoint accepted")


def test_evaluation_reports_real_counts_and_unmeasured_support():
    cases = [{"id": "a", "packet": PACKET, "draft": GOOD}]
    unreviewed = incident_ai.evaluate_drafts(cases)
    assert unreviewed["evidence_precision"] is None
    assert unreviewed["citation_valid_claims"] == 1
    cases[0]["reviewed_supported_claim_indices"] = [0]
    reviewed = incident_ai.evaluate_drafts(cases)
    assert reviewed["human_supported_claims"] == 1
    assert reviewed["evidence_precision"] == 1
