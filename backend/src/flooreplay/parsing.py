"""AI note extraction: one narrow parser interface, two implementations.

The model (when a key is configured) produces a DRAFT, never an event.
Deterministic resolution maps mentions to canonical operators and
operations by exact id or curated alias; multiple matches stay ambiguous
and fuzzy matching is never used to silently select a person.

Two providers:
- RuleBaselineParser: the documented exact-ID/rule baseline. Deterministic,
  offline, always available. This is the demo default; capabilities reports
  the live parser as unavailable when no key is configured.
- OpenAIStructuredParser: pinned gpt-4.1-mini-2025-04-14 with structured
  outputs over raw httpx (no SDK, so no hidden retries). A 15-second total
  budget owns at most one transient-failure retry.

Budget: 2,000 characters of input. English notes only; anything the parser
cannot confidently categorize returns UNSUPPORTED and the manual entry path
takes over.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Protocol

from .domain.types import Catalog

MAX_NOTE_CHARS = 2000
PARSER_SCHEMA_VERSION = 1

OPERATOR_ID_RE = re.compile(r"\bO\d{3}\b")
TIME_RE = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b")
ISO_TIME_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}")
UNAVAILABLE_PATTERNS = (
    "unavailable",
    "not able",
    "cannot",
    "can't",
    "won't be in",
    "will not be in",
    "on leave",
    "absent",
    "called in sick",
    "reported sick",
)
UNCERTAINTY_WORDS = ("might", "may", "possibly", "not sure", "i think", "probably")
UNSUPPORTED_HINTS = ("reschedule the line", "move the order", "change the plan", "reorder fabric")


class ParserUnavailable(RuntimeError):
    """The live provider could not be reached within budget. Manual entry
    remains available; this is never a domain outcome."""


@dataclass(frozen=True)
class MentionResolution:
    raw: str
    resolved_id: str | None = None
    status: str = "UNKNOWN"  # RESOLVED | AMBIGUOUS | UNKNOWN
    candidates: tuple[str, ...] = ()


@dataclass(frozen=True)
class DraftExtraction:
    event_category: str  # OPERATOR_UNAVAILABLE | UNSUPPORTED
    subject_mentions: tuple[str, ...] = ()
    operation_mentions: tuple[str, ...] = ()
    polarity: str = "REPORTED_UNAVAILABLE"
    uncertainty_phrase: str | None = None
    raw_temporal_expressions: tuple[str, ...] = ()
    ambiguity_notes: tuple[str, ...] = ()
    parser_kind: str = "rule-baseline"
    model: str | None = None
    prompt_digest: str = ""
    usage: dict[str, int] = field(default_factory=dict)


class NoteParser(Protocol):
    kind: str

    def parse(self, note_text: str, catalog: Catalog) -> DraftExtraction: ...


# ---------------------------------------------------------------------------
# Deterministic entity resolution (shared by every parser)
# ---------------------------------------------------------------------------


def _alias_index(catalog: Catalog) -> dict[str, tuple[str, ...]]:
    index: dict[str, tuple[str, ...]] = {}
    for operator in catalog.operators:
        names = {operator.id, operator.display_name, *operator.aliases}
        for name in names:
            key = name.strip().lower()
            index.setdefault(key, ())
            if operator.id not in index[key]:
                index[key] = (*index[key], operator.id)
    return index


def resolve_operator(mention: str, catalog: Catalog) -> MentionResolution:
    """Exact id or exact alias match only. A mention matching multiple
    operators stays ambiguous; resolution never guesses."""
    index = _alias_index(catalog)
    key = mention.strip().lower()
    if not key:
        return MentionResolution(raw=mention)
    hits = index.get(key, ())
    if len(hits) == 1:
        return MentionResolution(raw=mention, resolved_id=hits[0], status="RESOLVED")
    if len(hits) > 1:
        return MentionResolution(raw=mention, status="AMBIGUOUS", candidates=hits)
    return MentionResolution(raw=mention)


def resolve_operation(mention: str, catalog: Catalog) -> MentionResolution:
    index: dict[str, tuple[str, ...]] = {}
    for operation in catalog.operations:
        for name in {operation.id, operation.name, operation.name.lower()}:
            index.setdefault(name.strip().lower(), ())
            if operation.id not in index[name.strip().lower()]:
                index[name.strip().lower()] = (*index[name.strip().lower()], operation.id)
    key = mention.strip().lower()
    hits = index.get(key, ())
    if len(hits) == 1:
        return MentionResolution(raw=mention, resolved_id=hits[0], status="RESOLVED")
    if len(hits) > 1:
        return MentionResolution(raw=mention, status="AMBIGUOUS", candidates=hits)
    return MentionResolution(raw=mention)


def resolve_draft(draft: DraftExtraction, catalog: Catalog) -> dict[str, object]:
    return {
        "operators": [
            {
                "raw": r.raw,
                "resolved_id": r.resolved_id,
                "status": r.status,
                "candidates": list(r.candidates),
            }
            for r in (resolve_operator(m, catalog) for m in draft.subject_mentions)
        ],
        "operations": [
            {
                "raw": r.raw,
                "resolved_id": r.resolved_id,
                "status": r.status,
                "candidates": list(r.candidates),
            }
            for r in (resolve_operation(m, catalog) for m in draft.operation_mentions)
        ],
    }


# ---------------------------------------------------------------------------
# Rule baseline (offline, deterministic)
# ---------------------------------------------------------------------------


class RuleBaselineParser:
    kind = "rule-baseline"
    model = None

    def parse(self, note_text: str, catalog: Catalog) -> DraftExtraction:
        text = note_text.strip()
        lowered = text.lower()
        if any(hint in lowered for hint in UNSUPPORTED_HINTS):
            return DraftExtraction(
                event_category="UNSUPPORTED",
                parser_kind=self.kind,
                ambiguity_notes=("Request type is outside the supported coverage workflow.",),
            )

        subjects: list[str] = []
        for match in OPERATOR_ID_RE.findall(text):
            if match not in subjects and any(op.id == match for op in catalog.operators):
                subjects.append(match)

        operations: list[str] = []
        for operation in catalog.operations:
            for name in {operation.name, operation.id}:
                if name.lower() in lowered and operation.id not in operations:
                    operations.append(operation.id)

        polarity = "REPORTED_UNAVAILABLE" if any(
            pattern in lowered for pattern in UNAVAILABLE_PATTERNS
        ) else "REPORTED"

        uncertainty = next(
            (word for word in UNCERTAINTY_WORDS if word in lowered), None
        )

        temporal = list(ISO_TIME_RE.findall(text)) or [
            m.group(0) for m in TIME_RE.finditer(text)
        ]

        if not subjects and polarity == "REPORTED_UNAVAILABLE":
            return DraftExtraction(
                event_category="UNSUPPORTED",
                parser_kind=self.kind,
                ambiguity_notes=("No known operator id mentioned; resolve manually.",),
            )

        return DraftExtraction(
            event_category="OPERATOR_UNAVAILABLE" if polarity == "REPORTED_UNAVAILABLE" else "UNSUPPORTED",
            subject_mentions=tuple(subjects),
            operation_mentions=tuple(operations),
            polarity=polarity,
            uncertainty_phrase=uncertainty,
            raw_temporal_expressions=tuple(dict.fromkeys(temporal)),
            parser_kind=self.kind,
        )


# ---------------------------------------------------------------------------
# OpenAI structured output (only when a key is configured)
# ---------------------------------------------------------------------------

OPENAI_MODEL = "gpt-4.1-mini-2025-04-14"
_TOTAL_BUDGET_SECONDS = 15.0

_EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "event_category": {
            "type": "string",
            "enum": ["OPERATOR_UNAVAILABLE", "UNSUPPORTED"],
        },
        "subject_mentions": {"type": "array", "items": {"type": "string"}},
        "operation_mentions": {"type": "array", "items": {"type": "string"}},
        "polarity": {
            "type": "string",
            "enum": ["REPORTED_UNAVAILABLE", "REPORTED", "DENIED", "UNKNOWN"],
        },
        "uncertainty_phrase": {"type": ["string", "null"]},
        "raw_temporal_expressions": {"type": "array", "items": {"type": "string"}},
        "ambiguity_notes": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "event_category",
        "subject_mentions",
        "operation_mentions",
        "polarity",
        "raw_temporal_expressions",
        "ambiguity_notes",
    ],
    "additionalProperties": False,
}

_PROMPT_TEMPLATE = (
    "Extract a draft operational event from this floor note. Report only what "
    "the note says; do not resolve names to ids, judge feasibility, or propose "
    "coverage. If the note describes anything other than an operator being "
    "unable to cover an operation, return UNSUPPORTED. Note: {note}"
)


class OpenAIStructuredParser:
    kind = "openai-structured"
    model = OPENAI_MODEL

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def parse(self, note_text: str, catalog: Catalog) -> DraftExtraction:
        import hashlib
        import time

        import httpx

        prompt = _PROMPT_TEMPLATE.format(note=note_text)
        prompt_digest = "sha256:" + hashlib.sha256(prompt.encode()).hexdigest()
        deadline = time.monotonic() + _TOTAL_BUDGET_SECONDS

        body = {
            "model": OPENAI_MODEL,
            "input": prompt,
            "text": {"format": {"type": "json_schema", "name": "draft_extraction", "schema": _EXTRACTION_SCHEMA}},
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}

        last_error: Exception | None = None
        for attempt in (1, 2):  # at most one retry for transient failures
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                response = httpx.post(
                    "https://api.openai.com/v1/responses",
                    json=body,
                    headers=headers,
                    timeout=min(remaining, 12.0),
                )
                if response.status_code in (429, 500, 502, 503, 504) and attempt == 1:
                    last_error = RuntimeError(f"transient provider status {response.status_code}")
                    continue
                response.raise_for_status()
                payload = response.json()
                raw = payload["output"][0]["content"][0]["text"]
                parsed = json.loads(raw)
                return DraftExtraction(
                    event_category=parsed["event_category"],
                    subject_mentions=tuple(parsed.get("subject_mentions", ())),
                    operation_mentions=tuple(parsed.get("operation_mentions", ())),
                    polarity=parsed.get("polarity", "UNKNOWN"),
                    uncertainty_phrase=parsed.get("uncertainty_phrase"),
                    raw_temporal_expressions=tuple(parsed.get("raw_temporal_expressions", ())),
                    ambiguity_notes=tuple(parsed.get("ambiguity_notes", ())),
                    parser_kind=self.kind,
                    model=OPENAI_MODEL,
                    prompt_digest=prompt_digest,
                    usage={
                        "input_tokens": payload.get("usage", {}).get("input_tokens", 0),
                        "output_tokens": payload.get("usage", {}).get("output_tokens", 0),
                    },
                )
            except (httpx.HTTPError, KeyError, IndexError, json.JSONDecodeError) as exc:
                last_error = exc
                if attempt == 2:
                    break
        raise ParserUnavailable(
            f"live parser did not answer within its {_TOTAL_BUDGET_SECONDS:.0f}s budget"
            + (f": {last_error}" if last_error else "")
        )


def get_parser(api_key: str | None) -> NoteParser:
    if api_key:
        return OpenAIStructuredParser(api_key)
    return RuleBaselineParser()
