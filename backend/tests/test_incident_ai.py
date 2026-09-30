from __future__ import annotations

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


def test_evaluation_reports_real_counts_and_unmeasured_support():
    cases = [{"id": "a", "packet": PACKET, "draft": GOOD}]
    unreviewed = incident_ai.evaluate_drafts(cases)
    assert unreviewed["evidence_precision"] is None
    assert unreviewed["citation_valid_claims"] == 1
    cases[0]["reviewed_supported_claim_indices"] = [0]
    reviewed = incident_ai.evaluate_drafts(cases)
    assert reviewed["human_supported_claims"] == 1
    assert reviewed["evidence_precision"] == 1


def claim(text="The recorded evidence leaves the cause unresolved.", **kwargs):
    return {"text": text, "evidence_ids": ["E1"], "historical_refs": [], "metric_ids": [], "source_fields": [], **kwargs}

def test_typed_answer_renders_metric_values_and_rejects_numeric_prose():
    raw = {"claims": [claim(metric_ids=["M1"])], "abstention_reasons": []}
    checked = incident_ai.validate_output("question", raw, PACKET)
    assert checked["valid"]
    assert checked["output"]["claims"][0]["rendered_metrics"][0]["value"] == 12
    raw["claims"][0]["text"] = "The line lost 12 units."
    assert not incident_ai.validate_output("question", raw, PACKET)["valid"]
    raw["claims"][0]["text"] = "The line lost twelve units."
    # Written quantities must also remain app-rendered.
    assert not incident_ai.validate_output("question", raw, PACKET)["valid"]

def test_historical_citations_are_separate_and_source_fields_are_exact():
    raw = {"claims": [claim(historical_refs=["E1"])], "abstention_reasons": []}
    assert not incident_ai.validate_output("question", raw, PACKET)["valid"]
    packet = {**PACKET, "evidence": [{"id": "E1", "occurred_at": "09:32"}]}
    raw = {"claims": [claim("Arrival was recorded at 09:32.", source_fields=["E1.occurred_at"])], "abstention_reasons": []}
    assert incident_ai.validate_output("question", raw, packet)["valid"]
    raw["claims"][0]["source_fields"] = []
    assert not incident_ai.validate_output("question", raw, packet)["valid"]

def test_recovery_rejects_actions_outside_catalog_and_notes_require_confirmation():
    raw = {"proposals": [{"catalog_action_id": "execute-machine", "prerequisites": [], "evidence_ids": ["E1"], "owner_role": "lead"}], "limitations": []}
    assert not incident_ai.validate_output("recovery", raw, PACKET)["valid"]
    assert not incident_ai.validate_output("note", {"assertions": [], "requires_human_confirmation": False}, PACKET)["valid"]


def test_free_text_source_field_cannot_launder_unsupported_numeric_claim():
    packet = {**PACKET, "evidence": [{"id": "E1", "summary": "The line lost 999 units."}]}
    raw = {"claims": [claim("The line lost 999 units.", source_fields=["E1.summary"])], "abstention_reasons": []}
    assert not incident_ai.validate_output("question", raw, packet)["valid"]
    raw = {"claims": [claim()], "abstention_reasons": ["Shipment will be delayed 3 days"]}
    assert not incident_ai.validate_output("question", raw, packet)["valid"]


def test_all_numeric_prose_and_original_quoted_note_spans():
    for prose in ("Lost 900units from equipment failure", "Lost ١٢units", "Shipment delay is three hundred days"):
        raw = {"claims": [claim(prose)], "abstention_reasons": []}
        assert not incident_ai.validate_output("question", raw, PACKET)["valid"]
    raw = {"claims": [claim()], "abstention_reasons": ["Shipment delay is three hundred days"]}
    assert not incident_ai.validate_output("question", raw, PACKET)["valid"]
    text = 'Operator reported "needle break".\nVerification remains open.'
    packet = {**PACKET, "evidence": [{"id": "E1", "summary": text}]}
    raw = {"assertions": [{"assertion": claim(), "source_id": "E1", "source_span": text, "mentioned_entities": [], "uncertainty": "Verification remains open"}], "requires_human_confirmation": True}
    assert incident_ai.validate_output("note", raw, packet)["valid"]
    raw["assertions"][0]["source_span"] = "E1"
    assert not incident_ai.validate_output("note", raw, packet)["valid"]
