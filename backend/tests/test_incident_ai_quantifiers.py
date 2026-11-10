from __future__ import annotations

import pytest

from flooreplay import incident_ai

NUMERIC_ERROR = "Numeric prose must use an application-rendered metric reference"
QUANTIFIER_PROSE = {
    "couple": "The line lost a couple of days.",
    "dozen": "The line lost a dozen units.",
    "double": "Recovery would double output.",
    "few": "The line lost a few units.",
    "half": "The repair took half an hour.",
    "multiple": "The line lost multiple units.",
    "quarter": "The repair took a quarter hour.",
    "several": "The line lost several units.",
    "single": "The line lost a single unit.",
    "third": "The stop lasted a third of the shift.",
    "triple": "The line ran triple shifts.",
}


def _packet(source_value: str) -> dict:
    return {"incident_id": "hero", "evidence": [{"id": "E1", "source_id": source_value}], "metrics": []}


def _question(text: str, source_fields: list[str]) -> dict:
    claim = {"text": text, "evidence_ids": ["E1"], "historical_refs": [], "metric_ids": [], "source_fields": source_fields}
    return {"claims": [claim], "abstention_reasons": []}


@pytest.mark.parametrize("quantifier", sorted(QUANTIFIER_PROSE))
def test_quantifier_used_as_source_id_cannot_launder_quantity(quantifier):
    prose = QUANTIFIER_PROSE[quantifier]
    packet = _packet(quantifier)
    assert not incident_ai.validate_output("question", _question(prose, []), packet)["valid"]
    linked = incident_ai.validate_output("question", _question(prose, ["E1.source_id"]), packet)
    assert not linked["valid"]
    assert NUMERIC_ERROR in linked["errors"]


@pytest.mark.parametrize(
    "label, prose",
    [
        ("half", "The label half was recorded for the line."),
        ("double", "Entry double-checked by the lead."),
    ],
)
def test_non_quantity_label_spelled_like_a_quantifier_is_accepted(label, prose):
    result = incident_ai.validate_output("question", _question(prose, ["E1.source_id"]), _packet(label))
    assert result["valid"], result["errors"]
    assert result["output"]["claims"][0]["rendered_source_fields"] == [{"ref": "E1.source_id", "value": label}]


def test_digit_identifier_is_still_removed_from_prose():
    result = incident_ai.validate_output("question", _question("Recorded for S4.", ["E1.source_id"]), _packet("S4"))
    assert result["valid"], result["errors"]
