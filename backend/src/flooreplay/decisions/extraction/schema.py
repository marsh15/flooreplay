"""The `note-signal-v1` schema: what an extraction may say about one supplier note.

Unlike the v1 incident validator (`incident_ai._numeric_prose`, which rejects any digit
in model output), this validator accepts digits: quantities and lot ids are the point.
It is purely structural. Whether a value is *supported* by the note is decided by the
deterministic checks in `checks.py`, never by the model.

Span offsets are **code-point offsets** into the NFC-normalised note. Python `str`
indices are code points, so `normalize_note(note)[span.start:span.end]` is the span.
A Tamil syllable with combining marks is several code points, and NFD input differs
in length from NFC, so offsets are only meaningful against `normalize_note(note)`.
"""

from __future__ import annotations

import copy
import unicodedata
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    NonNegativeInt,
    StrictStr,
    ValidationError,
    model_validator,
)

from flooreplay.decisions.types import decision_digest

SCHEMA_VERSION = "note-signal-v1"

ISSUES = ("shade_fail", "gsm_fail", "defect")
UNITS = ("kg", "m")
LANGUAGES = ("en", "ta", "tanglish", "mixed")
SIGNAL_FIELDS = ("lot_id", "issue", "qty", "unit", "colour", "fabric_quality")


def normalize_note(note: str) -> str:
    """NFC. All span offsets refer to this form."""
    return unicodedata.normalize("NFC", note)


def note_digest(note: str) -> str:
    """Digest of the NFC note; stable across NFC/NFD spellings of the same text."""
    return decision_digest(normalize_note(note))


class _Strict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class Span(_Strict):
    """`note[start:end] == text`, in code points of the NFC-normalised note."""

    start: NonNegativeInt
    end: NonNegativeInt
    text: StrictStr

    @model_validator(mode="after")
    def _ordered(self) -> Span:
        if self.end < self.start:
            raise ValueError("span end must not precede start")
        return self


class FieldValue(_Strict):
    value: StrictStr | None
    span: Span | None


class NoteSignal(_Strict):
    lot_id: FieldValue
    issue: FieldValue  # value: one of ISSUES (enforced by the checks, constrained in the JSON schema)
    qty: FieldValue  # numeric text, e.g. "1200" or "1200.5"
    unit: FieldValue  # one of UNITS
    colour: FieldValue
    fabric_quality: FieldValue
    language: Literal["en", "ta", "tanglish", "mixed"]


class SignalValidationError(ValueError):
    """The provider payload does not have the note-signal-v1 shape."""


def validate_signal_payload(raw: dict[str, Any]) -> NoteSignal:
    """Structural validation. Accepts digits; rejects unknown keys at every level."""
    if not isinstance(raw, dict):
        raise SignalValidationError("signal payload must be a JSON object")
    try:
        return NoteSignal.model_validate(raw)
    except ValidationError as exc:
        raise SignalValidationError(str(exc)) from exc


def _field_schema(
    value_schema: dict[str, Any],
) -> dict[str, Any]:
    span = {
        "type": "object",
        "properties": {
            "start": {"type": "integer", "minimum": 0},
            "end": {"type": "integer", "minimum": 0},
            "text": {"type": "string", "minLength": 1},
        },
        "required": ["start", "end", "text"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "value": value_schema,
            "span": {"anyOf": [span, {"type": "null"}]},
        },
        "required": ["value", "span"],
        "additionalProperties": False,
    }


def note_signal_json_schema() -> dict[str, Any]:
    """Hand-built JSON Schema for forced structured output (no `$ref`, a fresh copy each call)."""
    text = {"type": ["string", "null"]}
    props: dict[str, Any] = {
        "lot_id": _field_schema(copy.deepcopy(text)),
        "issue": _field_schema({"type": ["string", "null"], "enum": [*ISSUES, None]}),
        "qty": _field_schema(copy.deepcopy(text)),
        "unit": _field_schema({"type": ["string", "null"], "enum": [*UNITS, None]}),
        "colour": _field_schema(copy.deepcopy(text)),
        "fabric_quality": _field_schema(copy.deepcopy(text)),
        "language": {"type": "string", "enum": list(LANGUAGES)},
    }
    return {
        "type": "object",
        "title": SCHEMA_VERSION,
        "properties": props,
        "required": list(props),
        "additionalProperties": False,
    }
