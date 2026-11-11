"""Anthropic and OpenAI extraction providers, per-model pricing. No network, ever."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import httpx2
import pytest

from flooreplay.config import settings
from flooreplay.decisions.extraction.anthropic_provider import (
    DEFAULT_MODEL,
    PROMPT_VERSION,
    AnthropicProvider,
    AnthropicProviderError,
    MissingAnthropicKeyError,
    anthropic_json_schema,
)
from flooreplay.decisions.extraction.openai_adapter import (
    MissingOpenAIKeyError,
    OpenAIProvider,
    OpenAIProviderError,
)
from flooreplay.decisions.extraction.provider import (
    GenerationProvider,
    MockProvider,
    ProviderResult,
)
from flooreplay.decisions.extraction.schema import (
    normalize_note,
    note_signal_json_schema,
)
from flooreplay.spending import (
    MODEL_PRICES,
    PRICE_TABLE,
    PRICE_TABLE_EFFECTIVE_DATE,
    PRICE_TABLE_VERSION,
    UnknownModelPriceError,
    cost,
)

NOTE = "Lot L-221 shade fail 1200 m"


def signal(language: str = "en") -> dict[str, Any]:
    """An opaque provider payload. The providers must not interpret or reshape it."""
    return {"lot_id": {"value": "L-221"}, "language": language}


def message_response(payload: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": DEFAULT_MODEL,
        "content": [{"type": "text", "text": json.dumps(payload)}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 321, "output_tokens": 87},
    }
    body.update(overrides)
    return body


class Recorder:
    """httpx2 MockTransport handler that records every request."""

    def __init__(self, status: int = 200, body: dict[str, Any] | None = None) -> None:
        self.status = status
        self.body = body if body is not None else message_response(signal())
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        return httpx2.Response(self.status, json=self.body)

    def provider(self, **kwargs: Any) -> AnthropicProvider:
        client = httpx2.Client(transport=httpx2.MockTransport(self))
        return AnthropicProvider(api_key="sk-ant-test-not-real", http_client=client, **kwargs)

    def sent(self, index: int = 0) -> dict[str, Any]:
        body = json.loads(self.requests[index].content)
        assert isinstance(body, dict)
        return body


def run(provider: GenerationProvider, note: str = NOTE) -> ProviderResult:
    return provider.extract(note, prompt_version=PROMPT_VERSION, schema=note_signal_json_schema())


# ---- Protocol ---------------------------------------------------------------------


def test_providers_satisfy_the_protocol() -> None:
    assert isinstance(AnthropicProvider(api_key="x"), GenerationProvider)
    assert isinstance(OpenAIProvider(api_key="x"), GenerationProvider)
    assert isinstance(MockProvider({}), GenerationProvider)


def test_default_and_comparison_models() -> None:
    assert DEFAULT_MODEL == "claude-haiku-5-5"
    assert AnthropicProvider(api_key="x").model == "claude-haiku-5-5"
    assert AnthropicProvider(api_key="x", model="claude-sonnet-5-5").model == "claude-sonnet-5-5"
    assert AnthropicProvider(api_key="x").name == "anthropic"
    assert OpenAIProvider(api_key="x").name == "openai"


# ---- Anthropic --------------------------------------------------------------------


def test_anthropic_sends_forced_schema_and_model() -> None:
    recorder = Recorder()
    schema = note_signal_json_schema()
    result = recorder.provider(model="claude-sonnet-5-5").extract(
        NOTE, prompt_version=PROMPT_VERSION, schema=schema
    )
    assert len(recorder.requests) == 1
    assert recorder.requests[0].url.path == "/v1/messages"
    sent = recorder.sent()
    assert sent["model"] == "claude-sonnet-5-5"
    fmt = sent["output_config"]["format"]
    assert fmt["type"] == "json_schema"
    # The schema that was passed in is the one sent (in Anthropic-compatible form).
    assert fmt["schema"] == anthropic_json_schema(schema)
    assert fmt["schema"]["required"] == schema["required"]
    assert fmt["schema"]["additionalProperties"] is False
    # Forced tool_choice is rejected by Sonnet 5.5, so the schema is forced via output_config.
    assert "tool_choice" not in sent
    assert "tools" not in sent
    assert "temperature" not in sent
    assert NOTE in sent["messages"][0]["content"]
    assert result.model == "claude-sonnet-5-5"


def test_anthropic_sends_whatever_schema_it_is_given() -> None:
    recorder = Recorder()
    custom = {
        "type": "object",
        "properties": {"x": {"type": ["string", "null"]}},
        "required": ["x"],
        "additionalProperties": False,
    }
    recorder.provider().extract(NOTE, prompt_version=PROMPT_VERSION, schema=custom)
    sent_schema = recorder.sent()["output_config"]["format"]["schema"]
    assert sent_schema["properties"]["x"]["anyOf"] == [{"type": "string"}, {"type": "null"}]
    assert sent_schema["required"] == ["x"]


def test_anthropic_schema_has_no_type_lists_or_null_enums() -> None:
    def walk(node: Any) -> None:
        if isinstance(node, dict):
            assert not isinstance(node.get("type"), list)
            if "enum" in node:
                assert None not in node["enum"]
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    source = {
        "type": "object",
        "properties": {
            "a": {"type": ["string", "null"], "enum": ["p", "q", None]},
            "b": {"type": ["string", "null"]},
        },
        "required": ["a", "b"],
        "additionalProperties": False,
    }
    converted = anthropic_json_schema(source)
    walk(converted)
    assert converted["properties"]["a"]["anyOf"] == [
        {"type": "string", "enum": ["p", "q"]},
        {"type": "null"},
    ]
    walk(anthropic_json_schema(note_signal_json_schema()))


def test_anthropic_parses_output_and_reports_usage() -> None:
    recorder = Recorder()
    result = run(recorder.provider())
    assert isinstance(result, ProviderResult)
    assert result.raw == signal()
    assert result.input_tokens == 321
    assert result.output_tokens == 87
    assert result.model == "claude-haiku-5-5"


def test_anthropic_ignores_thinking_blocks() -> None:
    body = message_response(
        signal(),
        content=[
            {"type": "thinking", "thinking": "", "signature": "sig"},
            {"type": "text", "text": json.dumps(signal())},
        ],
    )
    assert run(Recorder(body=body).provider()).raw == signal()


def test_anthropic_note_is_nfc_normalised_in_prompt() -> None:
    nfd = "é"  # e + combining acute
    recorder = Recorder()
    run(recorder.provider(), nfd)
    content = recorder.sent()["messages"][0]["content"]
    assert normalize_note(nfd) in content
    assert nfd not in content


def test_prompt_instructions() -> None:
    recorder = Recorder()
    run(recorder.provider())
    system = recorder.sent()["system"]
    text = system if isinstance(system, str) else " ".join(b["text"] for b in system)
    lowered = text.lower()
    for fragment in (
        "literally",
        "exactly",
        "code point",
        "nfc",
        "null",
        "english",
        "tamil",
        "tanglish",
        "evidence",
    ):
        assert fragment in lowered, fragment
    assert PROMPT_VERSION


def test_anthropic_client_uses_no_retries_and_explicit_timeout() -> None:
    recorder = Recorder()
    provider = recorder.provider(timeout=12.5)
    client = provider.client()
    assert client.max_retries == 0
    assert client.timeout == 12.5


def test_anthropic_does_not_retry_server_errors() -> None:
    recorder = Recorder(status=500, body={"type": "error", "error": {"type": "api_error", "message": "boom"}})
    provider = recorder.provider()
    with pytest.raises(Exception) as caught:
        run(provider)
    assert "boom" in str(caught.value) or "500" in str(caught.value)
    assert len(recorder.requests) == 1


def test_missing_key_raises_before_any_call(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    recorder = Recorder()
    client = httpx2.Client(transport=httpx2.MockTransport(recorder))
    provider = AnthropicProvider(http_client=client)
    with pytest.raises(MissingAnthropicKeyError):
        run(provider)
    assert recorder.requests == []


def test_key_comes_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-ant-from-settings")
    recorder = Recorder()
    client = httpx2.Client(transport=httpx2.MockTransport(recorder))
    run(AnthropicProvider(http_client=client))
    assert recorder.requests[0].headers["x-api-key"] == "sk-ant-from-settings"


@pytest.mark.parametrize(
    "overrides",
    [
        {"stop_reason": "refusal"},
        {"stop_reason": "max_tokens"},
        {"stop_reason": "tool_use"},
        {"stop_reason": "pause_turn"},
        {"content": [{"type": "thinking", "thinking": "", "signature": "s"}]},
        {"content": []},
        {"content": [{"type": "text", "text": "not json"}]},
        {"content": [{"type": "text", "text": "[1, 2]"}]},
    ],
)
def test_anthropic_unusable_responses_raise_typed_error(overrides: dict[str, Any]) -> None:
    recorder = Recorder(body=message_response(signal(), **overrides))
    with pytest.raises(AnthropicProviderError):
        run(recorder.provider())


def test_prompt_version_mismatch_is_refused() -> None:
    recorder = Recorder()
    with pytest.raises(ValueError):
        recorder.provider().extract(NOTE, prompt_version="other-v9", schema=note_signal_json_schema())
    assert recorder.requests == []


# ---- OpenAI adapter ---------------------------------------------------------------


class FakeResponses:
    def __init__(self, response: Any) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self.response


def fake_openai(text: str, input_tokens: int = 50, output_tokens: int = 9) -> tuple[Any, FakeResponses]:
    responses = FakeResponses(
        SimpleNamespace(
            output_text=text,
            status="completed",
            model="gpt-4.1-mini-2025-04-14",
            usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
        )
    )
    return SimpleNamespace(responses=responses), responses


def test_openai_adapter_with_fake_client() -> None:
    client, responses = fake_openai(json.dumps(signal("ta")))
    provider = OpenAIProvider(client=client, model="gpt-4.1-mini-2025-04-14")
    result = run(provider)
    assert result.raw == signal("ta")
    assert (result.input_tokens, result.output_tokens) == (50, 9)
    assert result.model == "gpt-4.1-mini-2025-04-14"
    call = responses.calls[0]
    assert call["model"] == "gpt-4.1-mini-2025-04-14"
    assert call["store"] is False
    fmt = call["text"]["format"]
    assert fmt["type"] == "json_schema" and fmt["strict"] is True
    assert fmt["schema"] == note_signal_json_schema()
    assert "tools" not in call
    assert NOTE in call["input"]


def test_openai_adapter_missing_key_raises_before_any_call(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "openai_api_key", "")
    with pytest.raises(MissingOpenAIKeyError):
        run(OpenAIProvider())


def test_openai_adapter_rejects_unusable_output() -> None:
    client, _ = fake_openai("not json")
    with pytest.raises(OpenAIProviderError):
        run(OpenAIProvider(client=client))


def test_openai_adapter_defaults_to_v1_settings_model() -> None:
    assert OpenAIProvider(api_key="x").model == settings.openai_generation_model


# ---- Price table ------------------------------------------------------------------


def test_default_cost_is_unchanged() -> None:
    # Pinned values from the v1 behaviour: $0.40 in / $1.60 out per million, $0.02 embeddings.
    assert cost(16000, 3000) == pytest.approx(0.0112)
    assert cost(1000, 100) == pytest.approx(0.00056)
    assert cost(16000, embedding=True) == pytest.approx(0.00032)
    assert PRICE_TABLE["version"] == "openai-2026-09-30"


def test_v1_model_priced_by_table_matches_default() -> None:
    assert cost(16000, 3000, model="gpt-4.1-mini-2025-04-14") == pytest.approx(cost(16000, 3000))
    assert cost(16000, model="text-embedding-3-small") == pytest.approx(cost(16000, embedding=True))


def test_claude_costs_come_from_the_table() -> None:
    assert cost(100_000, 1_000_000, model="claude-haiku-5-5") == pytest.approx(0.01 + 0.50)
    assert cost(1_000_000, 1_000_000, model="claude-sonnet-5-5") == pytest.approx(2.00 + 10.00)
    assert cost(2000, 500, model="claude-haiku-5-5") == pytest.approx((2000 * 0.10 + 500 * 0.50) / 1e6)
    assert cost(2000, 500, model="claude-sonnet-5-5") == pytest.approx((2000 * 2.0 + 500 * 10.0) / 1e6)


def test_haiku_long_prompt_uses_the_higher_rate_card() -> None:
    assert cost(100_000, 1000, model="claude-haiku-5-5") == pytest.approx((100_000 * 0.10 + 1000 * 0.50) / 1e6)
    assert cost(100_001, 1000, model="claude-haiku-5-5") == pytest.approx((100_001 * 0.50 + 1000 * 2.50) / 1e6)


def test_unknown_model_is_an_explicit_error() -> None:
    with pytest.raises(UnknownModelPriceError):
        cost(10, 10, model="claude-made-up-9")
    with pytest.raises(ValueError):
        cost(10, 10, model="gpt-9000")


def test_price_table_metadata() -> None:
    assert PRICE_TABLE_VERSION and PRICE_TABLE_EFFECTIVE_DATE == "2026-10-20"
    for model in ("claude-haiku-5-5", "claude-sonnet-5-5", "gpt-4.1-mini-2025-04-14"):
        assert model in MODEL_PRICES
