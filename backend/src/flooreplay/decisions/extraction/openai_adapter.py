"""OpenAI adapter satisfying `GenerationProvider`.

The v1 OpenAI path (`flooreplay.openai_provider`) is untouched. This adapter mirrors its
client construction (official SDK, `max_retries=0`, explicit timeout, `store=False`) but
calls the Responses API with the note-signal schema, because the v1 helper is bound to the
incident task schemas.
"""

from __future__ import annotations

import json
from typing import Any

from openai import OpenAI

from flooreplay.config import settings
from flooreplay.decisions.extraction.anthropic_provider import PROMPT_VERSION, SYSTEM_PROMPT
from flooreplay.decisions.extraction.provider import ProviderResult
from flooreplay.decisions.extraction.schema import SCHEMA_VERSION, normalize_note

DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_OUTPUT_TOKENS = 1500


class MissingOpenAIKeyError(RuntimeError):
    """No OpenAI API key is configured; raised before any network call."""


class OpenAIProviderError(RuntimeError):
    """The model reply could not be used as a note signal payload."""


class OpenAIProvider:
    name = "openai"

    def __init__(
        self,
        model: str | None = None,
        *,
        api_key: str | None = None,
        client: Any = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    ) -> None:
        self.model = model if model is not None else settings.openai_generation_model
        self._api_key = api_key
        self._client = client
        self._timeout = timeout
        self._max_output_tokens = max_output_tokens

    def client(self) -> Any:
        if self._client is None:
            key = self._api_key if self._api_key is not None else settings.openai_api_key
            if not key:
                raise MissingOpenAIKeyError("FLOORREPLAY_OPENAI_API_KEY is not configured")
            self._client = OpenAI(api_key=key, max_retries=0, timeout=self._timeout)
        return self._client

    def extract(self, note: str, *, prompt_version: str, schema: dict[str, Any]) -> ProviderResult:
        if prompt_version != PROMPT_VERSION:
            raise ValueError(f"This provider sends prompt {PROMPT_VERSION!r}, not {prompt_version!r}")
        client = self.client()
        response = client.responses.create(
            model=self.model,
            instructions=SYSTEM_PROMPT,
            input=f"<note>\n{normalize_note(note)}\n</note>",
            text={"format": {"type": "json_schema", "name": SCHEMA_VERSION.replace("-", "_"), "schema": schema, "strict": True}},
            max_output_tokens=self._max_output_tokens,
            store=False,
        )
        if getattr(response, "status", "completed") != "completed":
            raise OpenAIProviderError(f"Response status {response.status!r}; no usable signal")
        try:
            raw = json.loads(response.output_text)
        except (ValueError, TypeError) as exc:
            raise OpenAIProviderError("Model reply was not JSON") from exc
        if not isinstance(raw, dict):
            raise OpenAIProviderError("Model reply was not a JSON object")
        usage = response.usage
        if usage is None:
            raise OpenAIProviderError("Response carried no usage; cannot settle spend")
        return ProviderResult(raw=raw, input_tokens=usage.input_tokens, output_tokens=usage.output_tokens, model=self.model)
