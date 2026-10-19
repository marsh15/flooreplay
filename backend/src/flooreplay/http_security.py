"""Bound request envelopes and apply response policies, including error responses."""
from __future__ import annotations

import asyncio
from collections.abc import Sequence
from uuid import uuid4

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


def response_security_headers(scope: Scope) -> dict[str, str]:
    headers = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "no-referrer",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    }
    if scope["path"].startswith("/api/"):
        headers["Cache-Control"] = "private, no-store"
        headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
    if scope.get("scheme") == "https":
        headers["Strict-Transport-Security"] = "max-age=31536000"
    return headers


def error_response_headers(scope: Scope, allowed_origins: Sequence[str]) -> dict[str, str]:
    headers = response_security_headers(scope)
    origin = Headers(scope=scope).get("origin")
    # These responses are emitted outside CORSMiddleware. Use the same exact allowlist.
    if origin is not None and origin in allowed_origins:
        headers["Access-Control-Allow-Origin"] = origin
        headers["Access-Control-Expose-Headers"] = "X-Request-ID"
        headers["Vary"] = "Origin"
    return headers


class HttpSecurityMiddleware:
    def __init__(self, app: ASGIApp, max_body_bytes: int = 16 * 1024 * 1024, allowed_origins: Sequence[str] = ()) -> None:
        self.app = app
        # Allows JSON escaping overhead for the existing 2 MiB source-text limit.
        self.max_body_bytes = max_body_bytes
        self.allowed_origins = tuple(allowed_origins)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def secure_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.update(response_security_headers(scope))
            await send(message)

        async def refuse(status: int, code: str, message: str) -> None:
            trace = str(uuid4())
            response = JSONResponse({"code": code, "message": message, "trace_id": trace}, status_code=status, headers={**error_response_headers(scope, self.allowed_origins), "X-Request-ID": trace})
            await response(scope, receive, secure_send)

        length = MutableHeaders(scope=scope).get("content-length")
        if length is not None:
            if not length.isascii() or not length.isdecimal():
                await refuse(400, "INVALID_CONTENT_LENGTH", "Invalid request length.")
                return
            if len(length) > 10 or int(length) > self.max_body_bytes:
                await refuse(413, "REQUEST_TOO_LARGE", "The request is too large. Use a smaller source file.")
                return

        buffered = bytearray()
        size = 0
        try:
            async with asyncio.timeout(30):
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return
                    size += len(message.get("body", b""))
                    if size > self.max_body_bytes:
                        await refuse(413, "REQUEST_TOO_LARGE", "The request is too large. Use a smaller source file.")
                        return
                    buffered.extend(message.get("body", b""))
                    if not message.get("more_body", False):
                        break
        except TimeoutError:
            await refuse(408, "REQUEST_TIMEOUT", "The request body took too long to arrive. Please try again.")
            return
        replayed = False

        async def replay_receive() -> Message:
            nonlocal replayed
            if not replayed:
                replayed = True
                message: Message = {"type": "http.request", "body": bytes(buffered), "more_body": False}
                buffered.clear()
                return message
            return await receive()

        await self.app(scope, replay_receive, secure_send)
