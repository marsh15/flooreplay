"""Shared service-layer error type.

Leaf module: it must not import anything from the package, so any module can
depend on it without creating an import cycle.
"""

from __future__ import annotations


class ServiceError(Exception):
    def __init__(
        self, code: str, message: str, http_status: int = 400, retry_after: int | None = None
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.retry_after = retry_after
