"""Envelope and response policies apply before application handlers."""
from __future__ import annotations

import asyncio
import json

from starlette.types import Message

from flooreplay.http_security import HttpSecurityMiddleware


def exchange(chunks: list[bytes], *, limit: int = 8, declared: str | None = None, origin: str | None = None):
    messages: list[Message] = []
    handled = []
    requests = iter({"type": "http.request", "body": chunk, "more_body": index < len(chunks) - 1} for index, chunk in enumerate(chunks))

    async def receive():
        return next(requests, {"type": "http.disconnect"})

    async def send(message):
        messages.append(message)

    async def app(scope, receive, send):
        body = b""
        while True:
            message = await receive()
            body += message.get("body", b"")
            if not message.get("more_body", False):
                break
        handled.append(body)
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": body})

    headers = [(b"content-length", declared.encode())] if declared is not None else []
    if origin:
        headers.append((b"origin", origin.encode()))
    asyncio.run(HttpSecurityMiddleware(app, max_body_bytes=limit, allowed_origins=["https://frontend.example"])({"type": "http", "path": "/api/v1/example", "scheme": "https", "headers": headers}, receive, send))
    return messages, handled


def test_streamed_body_limit_rejects_without_entering_application():
    messages, handled = exchange([b"12345", b"6789"])
    assert handled == []
    assert messages[0]["status"] == 413
    assert json.loads(messages[1]["body"])["code"] == "REQUEST_TOO_LARGE"
    assert dict(messages[0]["headers"])[b"cache-control"] == b"private, no-store"


def test_exact_limit_replays_original_body_and_adds_security_headers():
    messages, handled = exchange([b"1234", b"5678"], declared="8")
    assert handled == [b"12345678"]
    headers = dict(messages[0]["headers"])
    assert headers[b"x-frame-options"] == b"DENY"
    assert headers[b"strict-transport-security"] == b"max-age=31536000"
    assert headers[b"content-security-policy"].startswith(b"default-src 'none'")


def test_declared_and_actual_sizes_are_both_checked():
    assert exchange([b"unused"], declared="9")[0][0]["status"] == 413
    assert exchange([b"123456789"], declared="1")[0][0]["status"] == 413
    assert exchange([b"unused"], declared="-1")[0][0]["status"] == 400


def test_early_errors_are_readable_only_by_configured_frontend_origins():
    messages, _ = exchange([b"unused"], declared="9", origin="https://frontend.example")
    assert dict(messages[0]["headers"])[b"access-control-allow-origin"] == b"https://frontend.example"
    messages, _ = exchange([b"unused"], declared="9", origin="https://untrusted.example")
    assert b"access-control-allow-origin" not in dict(messages[0]["headers"])
