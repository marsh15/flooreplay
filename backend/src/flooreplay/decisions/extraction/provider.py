"""Generation provider Protocol plus deterministic doubles. No SDK imports here.

Real providers (Anthropic, the OpenAI adapter) live in their own modules (T18).
"""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable

from flooreplay.decisions.extraction.schema import (
    LANGUAGES,
    SIGNAL_FIELDS,
    normalize_note,
    note_digest,
)
from flooreplay.decisions.types import FrozenModel


class ProviderResult(FrozenModel):
    raw: dict[str, Any]
    input_tokens: int
    output_tokens: int
    model: str


@runtime_checkable
class GenerationProvider(Protocol):
    """Turns one note into a raw `note-signal-v2` payload (`value` + `evidence` per field).

    Contract: the caller passes `normalize_note(note)` (NFC), and the provider sends exactly
    that text to the model. Evidence is located in the NFC note by `checks.locate_evidence`;
    a provider that sent NFD text would have its evidence rejected as `span_not_found`.
    Providers return the model's JSON untouched: offsets are never asked for, and nothing is
    trusted until the deterministic checks have run.
    """

    name: str
    model: str

    def extract(
        self, note: str, *, prompt_version: str, schema: dict[str, Any]
    ) -> ProviderResult: ...


class ProviderCalledError(RuntimeError):
    """A provider was called where the code path promised it never would."""


def empty_signal_raw(language: str = LANGUAGES[0]) -> dict[str, Any]:
    """A schema-valid signal with every field null (the provider schema's nullable fields)."""
    raw: dict[str, Any] = {f: None for f in SIGNAL_FIELDS}
    raw["language"] = language
    return raw


class MockProvider:
    """Table-driven and deterministic: note digest -> canned raw payload.

    Unknown notes yield the empty-field signal. Token counts derive from the note and
    payload lengths, so they are stable too.
    """

    def __init__(
        self,
        table: Mapping[str, dict[str, Any]],
        *,
        name: str = "mock",
        model: str = "mock-extractor-1",
    ) -> None:
        self.name = name
        self.model = model
        self._table = {k: copy.deepcopy(v) for k, v in table.items()}

    def extract(self, note: str, *, prompt_version: str, schema: dict[str, Any]) -> ProviderResult:
        canned = self._table.get(note_digest(note))
        raw = copy.deepcopy(canned) if canned is not None else empty_signal_raw()
        out_len = len(json.dumps(raw, sort_keys=True, ensure_ascii=False))
        return ProviderResult(
            raw=raw,
            input_tokens=max(1, len(normalize_note(note)) // 4),
            output_tokens=max(1, out_len // 4),
            model=self.model,
        )


class RaisingProvider:
    """Raises on any call; proves a code path (replay) never reaches a provider."""

    name = "raising"
    model = "raising-1"

    def extract(self, note: str, *, prompt_version: str, schema: dict[str, Any]) -> ProviderResult:
        raise ProviderCalledError("a provider must not be called on this path")
