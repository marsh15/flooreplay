"""A minimal sliding-window rate limiter for the public demo.

Free single-instance hosting cannot assume Redis, so the window lives in
process memory and resets on restart. That is the honest trade for a demo:
the limit bounds abuse, it is not an accounting system. Only mutating
execution endpoints use it; reads stay open.
"""

from __future__ import annotations

import time
from collections import deque
from threading import Lock

from fastapi import Request

from .config import settings
from .errors import ServiceError


class SlidingWindowLimiter:
    def __init__(self, max_events: int, window_seconds: float) -> None:
        self.max_events = max_events
        self.window_seconds = window_seconds
        if max_events < 1 or window_seconds <= 0:
            raise ValueError("Rate limits must be positive")
        self._events: dict[str, deque[float]] = {}
        self._lock = Lock()
        self._max_keys = 10_000
        self._next_cleanup = 0.0

    def allow(self, key: str) -> tuple[bool, int]:
        """Return (allowed, retry_after_seconds)."""
        with self._lock:
            now = time.monotonic()
            cutoff = now - self.window_seconds
            if now >= self._next_cleanup:
                self._events = {identity: events for identity, events in self._events.items() if events and events[-1] > cutoff}
                self._next_cleanup = now + min(60.0, self.window_seconds)
            window = self._events.get(key)
            if window is None:
                if len(self._events) >= self._max_keys:
                    return False, max(1, int(self._next_cleanup - now) + 1)
                window = deque()
                self._events[key] = window
            while window and window[0] <= cutoff:
                window.popleft()
            if len(window) >= self.max_events:
                retry_after = max(1, int(window[0] + self.window_seconds - now) + 1)
                return False, retry_after
            window.append(now)
            return True, 0


def client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def make_execution_limiter() -> SlidingWindowLimiter:
    return SlidingWindowLimiter(
        max_events=settings.public_replays_per_hour,
        window_seconds=3600.0,
    )


def enforce(limiter: SlidingWindowLimiter, request: Request) -> None:
    allowed, retry_after = limiter.allow(client_key(request))
    if not allowed:
        raise ServiceError(
            "RATE_LIMITED",
            "The public demo limits replay executions per client. "
            "The latest saved report for this selection remains available.",
            429,
            retry_after=retry_after,
        )


__all__ = [
    "SlidingWindowLimiter",
    "client_key",
    "enforce",
    "make_execution_limiter",
]
