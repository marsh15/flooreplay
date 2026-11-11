"""The `note-signal-v2` schema: what an extraction may say about one supplier note.

The model returns, per field, a `value` and `evidence` (text copied exactly from the note)
and **no offsets**. Code locates the evidence in the NFC-normalised note
(`checks.locate_evidence`): exactly one occurrence yields the stored `Span`, none or several
fail the field. Unlike the v1 incident validator (`incident_ai._numeric_prose`, which
rejects any digit in model output), this validator accepts digits: quantities and lot ids
are the point. It is purely structural. Whether a value is *supported* by the note is
decided by the deterministic checks in `checks.py`, never by the model.

`Span` offsets are **code-point offsets** into the NFC-normalised note. Python `str`
indices are code points, so `normalize_note(note)[span.start:span.end]` is the span. A
Tamil syllable with combining marks is several code points, and NFD input differs in
length from NFC, so offsets are only meaningful against `normalize_note(note)`.
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
    field_validator,
    model_validator,
)

from flooreplay.decisions.types import decision_digest

SCHEMA_VERSION = "note-signal-v2"

ISSUES = ("shade_fail", "gsm_fail", "defect")
UNITS = ("kg", "m")
LANGUAGES = ("en", "ta", "tanglish", "mixed")
SIGNAL_FIELDS = ("lot_id", "issue", "qty", "unit", "colour", "fabric_quality")
# A fabric_qc fact needs all of these; the rest are optional (null is fine, present must pass).
REQUIRED_FIELDS = ("lot_id", "issue", "qty", "unit")
OPTIONAL_FIELDS = ("colour", "fabric_quality")


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
    """One extracted field. Both null means absent; the checks decide what a half-filled
    pair (value without evidence, evidence without value) is: a failed claim."""

    value: StrictStr | None
    evidence: StrictStr | None


class NoteSignal(_Strict):
    lot_id: FieldValue
    issue: FieldValue  # value: one of ISSUES (enforced by the checks, constrained in the schema)
    qty: FieldValue  # numeric text, e.g. "1200" or "1200.5"
    unit: FieldValue  # one of UNITS
    colour: FieldValue
    fabric_quality: FieldValue
    language: Literal["en", "ta", "tanglish", "mixed"]

    @field_validator(*SIGNAL_FIELDS, mode="before")
    @classmethod
    def _null_field_is_absent(cls, v: Any) -> Any:
        # The provider schema makes each field nullable as a whole (one union per field).
        return {"value": None, "evidence": None} if v is None else v


class SignalValidationError(ValueError):
    """The provider payload does not have the note-signal-v2 shape."""


def validate_signal_payload(raw: dict[str, Any]) -> NoteSignal:
    """Structural validation. Accepts digits; rejects unknown keys at every level."""
    if not isinstance(raw, dict):
        raise SignalValidationError("signal payload must be a JSON object")
    try:
        return NoteSignal.model_validate(raw)
    except ValidationError as exc:
        raise SignalValidationError(str(exc)) from exc


_FIELD_HELP = {
    "lot_id": "The lot id exactly as written in the note, e.g. L-221.",
    "issue": "The fabric problem the note states.",
    "qty": "The quantity number exactly as written in the note (digits, optional decimal point).",
    "unit": "The unit the note states for the quantity.",
    "colour": "The colour word exactly as written in the note.",
    "fabric_quality": "The fabric quality words exactly as written in the note.",
}


def _field_schema(field: str, value_schema: dict[str, Any]) -> dict[str, Any]:
    """Nullable as a whole: one union per field keeps the provider union count low."""
    value = {"type": "string", "description": _FIELD_HELP[field], **value_schema}
    obj = {
        "type": "object",
        "properties": {
            "value": value,
            "evidence": {
                "type": "string",
                "description": "The words copied exactly from the note that support the value.",
            },
        },
        "required": ["value", "evidence"],
        "additionalProperties": False,
    }
    return {
        "anyOf": [obj, {"type": "null"}],
        "description": f"{_FIELD_HELP[field]} Copy the exact words from the note; null if absent.",
    }


def note_signal_json_schema() -> dict[str, Any]:
    """Hand-built JSON Schema for forced structured output (no `$ref`, a fresh copy each call).

    OpenAI-strict compatible: every object lists all its properties as required and forbids
    extras, there is no `minimum`/`minLength`/`title`, and only the six field unions are
    nullable (6 <= 8).
    """
    props: dict[str, Any] = {
        "lot_id": _field_schema("lot_id", {}),
        "issue": _field_schema("issue", {"enum": list(ISSUES)}),
        "qty": _field_schema("qty", {}),
        "unit": _field_schema("unit", {"enum": list(UNITS)}),
        "colour": _field_schema("colour", {}),
        "fabric_quality": _field_schema("fabric_quality", {}),
        "language": {
            "type": "string",
            "enum": list(LANGUAGES),
            "description": "Language of the note as a whole.",
        },
    }
    return copy.deepcopy(
        {
            "type": "object",
            "properties": props,
            "required": list(props),
            "additionalProperties": False,
        }
    )
