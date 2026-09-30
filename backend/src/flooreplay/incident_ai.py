"""Historical claim validation and current typed grounding contracts.

Citation checks establish packet membership, not whether prose is true. A human
must review semantic support before any AI claim is presented as established.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

MAX_PACKET_BYTES = 16_000
MAX_RESPONSE_BYTES = 256_000
NUMBER = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?(?![\w.])")
UNREFERENCED_DIGIT = re.compile(r"\d")
NUMBER_WORD = re.compile(r"\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|million|percent)\b", re.I)
SOURCE_TIME = re.compile(r"\b\d{1,2}:\d{2}\b")
SOURCE_CODE = re.compile(r"\b[A-Za-z][A-Za-z0-9-]*\d+\b")

_CLAIM = {
    "type": "object",
    "properties": {
        "text": {"type": "string"},
        "evidence_ids": {"type": "array", "items": {"type": "string"}},
        "metric_ids": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["text", "evidence_ids", "metric_ids"],
    "additionalProperties": False,
}
SCHEMA = {
    "type": "object",
    "properties": {
        "claims": {"type": "array", "items": _CLAIM},
        "limitations": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["claims", "limitations"],
    "additionalProperties": False,
}


def _packet_bytes(packet: dict[str, Any]) -> bytes:
    if not isinstance(packet, dict):
        raise ValueError("Evidence packet must be an object")
    for name, limit in (("evidence", 30), ("metrics", 15), ("precedents", 3)):
        entries = packet.get(name, [])
        if not isinstance(entries, list) or len(entries) > limit:
            raise ValueError(f"{name} exceeds the bounded packet contract")
    encoded = json.dumps(packet, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    if len(encoded) > MAX_PACKET_BYTES:
        raise ValueError("Evidence packet exceeds 16 KB; narrow the task without dropping contradictions")
    return encoded


def validate_draft(draft: Any, packet: dict[str, Any]) -> dict[str, Any]:
    """Fail closed on structure, packet citations and unbacked numeric literals."""
    _packet_bytes(packet)
    errors: list[str] = []
    if not isinstance(draft, dict) or set(draft) != {"claims", "limitations"}:
        return {"valid": False, "errors": ["Invalid draft structure"], "claims": []}
    claims, limitations = draft["claims"], draft["limitations"]
    if not isinstance(claims, list) or len(claims) > 8 or not isinstance(limitations, list) or len(limitations) > 5:
        return {"valid": False, "errors": ["Draft exceeds claim or limitation limits"], "claims": []}
    if any(not isinstance(x, str) or len(x) > 300 for x in limitations):
        errors.append("Invalid limitation")
    evidence_by_id = {str(item["id"]): item for item in packet.get("evidence", []) if isinstance(item, dict) and "id" in item}
    evidence = set(evidence_by_id)
    metrics = {str(item["id"]): item for item in packet.get("metrics", []) if isinstance(item, dict) and "id" in item}
    clean: list[dict[str, Any]] = []
    for index, claim in enumerate(claims):
        if not isinstance(claim, dict) or set(claim) != {"text", "evidence_ids", "metric_ids"}:
            errors.append(f"Claim {index}: invalid structure")
            continue
        claim_text, ids, metric_ids = claim["text"], claim["evidence_ids"], claim["metric_ids"]
        if not isinstance(claim_text, str) or not claim_text.strip() or len(claim_text) > 400:
            errors.append(f"Claim {index}: invalid text")
            continue
        if not isinstance(ids, list) or not isinstance(metric_ids, list) or any(not isinstance(x, str) for x in ids + metric_ids):
            errors.append(f"Claim {index}: invalid references")
            continue
        if not ids and not metric_ids:
            errors.append(f"Claim {index}: uncited")
        if set(ids) - evidence or set(metric_ids) - metrics.keys():
            errors.append(f"Claim {index}: reference outside pinned packet")
        allowed_numbers = set()
        for metric_id in metric_ids:
            metric = metrics.get(metric_id)
            if metric is not None and isinstance(metric.get("value"), (int, float)) and not isinstance(metric["value"], bool):
                allowed_numbers.update(NUMBER.findall(str(metric["value"])))
        # Timestamps and source identifiers are cited observations, not calculated metrics.
        # Strip only exact tokens present in the cited source; quantities still need metric IDs.
        source_text = json.dumps([evidence_by_id[item] for item in ids if item in evidence_by_id], ensure_ascii=False)
        numeric_text = claim_text
        for pattern in (SOURCE_TIME, SOURCE_CODE):
            for match in pattern.findall(claim_text):
                if match in source_text:
                    numeric_text = numeric_text.replace(match, "")
        if set(NUMBER.findall(numeric_text)) - allowed_numbers:
            errors.append(f"Claim {index}: numeric value lacks a matching metric")
        used_metric_ids = [
            metric_id for metric_id in metric_ids
            if metric_id in metrics and str(metrics[metric_id].get("value")) in NUMBER.findall(numeric_text)
        ]
        clean.append({"text": claim_text.strip(), "evidence_ids": ids, "metric_ids": used_metric_ids})
    return {"valid": not errors, "errors": errors, "claims": clean if not errors else []}


def evaluate_drafts(cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Score recorded cases only; semantic evidence precision requires human labels.

    Each case has packet, draft and optional reviewed_supported_claim_indices.
    No model is called and absent human review is reported as unavailable.
    """
    valid = cited = total_claims = reviewed_claims = supported = 0
    failures: list[dict[str, Any]] = []
    for index, case in enumerate(cases):
        draft, packet = case["draft"], case["packet"]
        check = validate_draft(draft, packet)
        valid += int(check["valid"])
        claims = draft.get("claims", []) if isinstance(draft, dict) else []
        total_claims += len(claims) if isinstance(claims, list) else 0
        if check["valid"]:
            cited += len(claims)
        else:
            failures.append({"case": case.get("id", index), "errors": check["errors"]})
        labels = case.get("reviewed_supported_claim_indices")
        if labels is not None:
            if not isinstance(labels, list) or any(not isinstance(i, int) or i < 0 or i >= len(claims) for i in labels):
                raise ValueError("Invalid human review labels")
            reviewed_claims += len(claims)
            supported += len(set(labels))
    return {"cases": len(cases), "valid_drafts": valid, "factual_claims": total_claims,
            "citation_valid_claims": cited, "human_reviewed_claims": reviewed_claims,
            "human_supported_claims": supported,
            "evidence_precision": supported / reviewed_claims if reviewed_claims else None,
            "failures": failures}



class GroundedClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(max_length=600)
    evidence_ids: list[str]
    historical_refs: list[str]
    metric_ids: list[str]
    source_fields: list[str]


class HypothesisDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    explanation: GroundedClaim
    counterevidence_ids: list[str]
    limitations: list[str]
    next_checks: list[str]


class InvestigationDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hypotheses: list[HypothesisDraft]
    unresolved_issues: list[str]


class AnswerDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claims: list[GroundedClaim]
    abstention_reasons: list[str]


class SummaryDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    selected_claims: list[GroundedClaim]
    unresolved_issues: list[str]


class RecoveryProposalDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    catalog_action_id: str
    prerequisites: list[str]
    evidence_ids: list[str]
    owner_role: str


class RecoveryDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    proposals: list[RecoveryProposalDraft]
    limitations: list[str]


class NoteAssertion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    assertion: GroundedClaim
    source_id: str
    source_span: str
    mentioned_entities: list[str]
    uncertainty: str


class NoteDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    assertions: list[NoteAssertion]
    requires_human_confirmation: bool


TASK_SCHEMAS: dict[str, type[BaseModel]] = {"investigation": InvestigationDraft, "question": AnswerDraft, "summary": SummaryDraft, "recovery": RecoveryDraft, "note": NoteDraft}


def validate_output(task: str, raw: dict[str, Any], packet: dict[str, Any]) -> dict[str, Any]:
    """References select app-rendered quantities; prose never supplies calculated numerals."""
    errors: list[str] = []
    evidence = {str(e["id"]): e for e in packet.get("evidence", [])}
    historical = {str(e["id"]): e for e in packet.get("historical_evidence", [])}
    metrics = {str(e["id"]): e for e in packet.get("metrics", [])}
    try:
        parsed = TASK_SCHEMAS[task].model_validate(raw).model_dump()
    except (ValueError, KeyError) as exc:
        return {"valid": False, "errors": [str(exc)], "output": None}

    def inspect(value: Any) -> None:
        if isinstance(value, list):
            if len(value) > 12:
                errors.append("Output list exceeds limit")
            for item in value:
                inspect(item)
        elif isinstance(value, dict):
            if "text" in value:
                if not value["evidence_ids"] and not value["metric_ids"] and not value["historical_refs"]:
                    errors.append("Uncited claim")
                if set(value["evidence_ids"]) - evidence.keys() or set(value["historical_refs"]) - historical.keys() or set(value["metric_ids"]) - metrics.keys():
                    errors.append("Reference outside pinned packet")
                # Only exact cited source fields can carry source times or identifiers.
                prose = value["text"]
                for field in value["source_fields"]:
                    source_id, separator, key = field.partition(".")
                    source = evidence.get(source_id)
                    if not separator or source_id not in value["evidence_ids"] or source is None or key not in {"occurred_at", "start", "end", "source_id", "id", "lot_id", "order_id", "line_id", "style_id"} or key not in source:
                        errors.append("Invalid source field reference")
                    else:
                        prose = prose.replace(str(source[key]), "")
                if UNREFERENCED_DIGIT.search(prose) or NUMBER_WORD.search(prose):
                    errors.append("Numeric prose must use an application-rendered metric reference")
                value["rendered_metrics"] = [metrics[m] for m in value["metric_ids"] if m in metrics]
                value["support_status"] = "UNREVIEWED"
            if "counterevidence_ids" in value and set(value["counterevidence_ids"]) - evidence.keys():
                errors.append("Counterevidence outside pinned packet")
            if "catalog_action_id" in value:
                actions = {str(a["id"]): a for a in packet.get("action_catalog", [])}
                if value["catalog_action_id"] not in actions:
                    errors.append("Recovery action outside catalog")
                if set(value["evidence_ids"]) - evidence.keys():
                    errors.append("Recovery evidence outside packet")
                value["state"] = "DRAFT"
            if "source_span" in value:
                source = evidence.get(value["source_id"])
                if source is None or not value["source_span"] or not any(isinstance(source.get(field), str) and value["source_span"] in source[field] for field in ("summary", "text", "note_text")):
                    errors.append("Note span not present in source")
            for key, item in list(value.items()):
                if key in {"limitations", "next_checks", "unresolved_issues", "abstention_reasons", "prerequisites", "uncertainty"}:
                    prose_items = item if isinstance(item, list) else [item]
                    if any(isinstance(prose_item, str) and (UNREFERENCED_DIGIT.search(prose_item) or NUMBER_WORD.search(prose_item)) for prose_item in prose_items):
                        errors.append("Unsupported numerical claim in prose")
                if key not in {"rendered_metrics", "text", "source_span"}:
                    inspect(item)
        elif isinstance(value, str):
            pass
    inspect(parsed)
    if task == "note" and not parsed["requires_human_confirmation"]:
        errors.append("Extracted notes require human confirmation")
    return {"valid": not errors, "errors": errors, "output": parsed if not errors else None}
