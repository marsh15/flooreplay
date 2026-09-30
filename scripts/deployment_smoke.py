#!/usr/bin/env python3
"""Read-only deployment checks; no credentials or provider calls are used."""
from __future__ import annotations

import argparse
import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def fetch(url: str, body: dict | None = None) -> tuple[int, bytes]:
    request = Request(url, data=json.dumps(body).encode() if body is not None else None, headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=90) as response:
            return response.status, response.read()
    except HTTPError as response:
        return response.code, response.read()


def cors_check(api: str, origin: str, allowed: bool) -> dict:
    request = Request(api + "/auth/login", method="OPTIONS", headers={
        "Origin": origin,
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "authorization,content-type",
    })
    try:
        response = urlopen(request, timeout=60)
    except HTTPError as error:
        response = error
    with response:
        echoed = response.headers.get("Access-Control-Allow-Origin")
        return {"path": "cors:" + origin, "passed": (response.status == 200 and echoed == origin) if allowed else echoed is None, "status": response.status}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", required=True, help="API base ending /api/v1")
    parser.add_argument("--frontend", required=True)
    parser.add_argument("--check-cors", action="store_true", help="Verify exact frontend-origin access and rejection of another origin")
    args = parser.parse_args()
    api, frontend = args.api.rstrip("/"), args.frontend.rstrip("/")
    checks = []
    if args.check_cors:
        checks.extend([cors_check(api, frontend, True), cors_check(api, "https://untrusted.invalid", False)])
    for path in ("/health/live", "/health/ready", "/incidents", "/capabilities"):
        status, payload = fetch(api + path)
        checks.append({"path": path, "passed": status == 200, "status": status})
        if status == 200:
            json.loads(payload)
    for path, body in (("/analyses/no-access/ai-runs", {"task": "investigation", "idempotency_key": "anonymous-smoke"}), ("/incidents/search/hybrid", {"query": "material", "corpus_id": "no-access", "cutoff": "2026-09-30T12:00:00Z", "idempotency_key": "anonymous-smoke"})):
        status, _ = fetch(api + path, body)
        checks.append({"path": path, "passed": status in (401, 403), "status": status})
    for path in ("/", "/incidents/INC-001"):
        status, payload = fetch(frontend + path)
        checks.append({"path": "frontend" + path, "passed": status == 200 and b'<div id="root"' in payload, "status": status})
    print(json.dumps({"status": "PASSED" if all(check["passed"] for check in checks) else "FAILED", "checks": checks, "paid_calls": 0, "remaining": "Authenticated review, real generation/embedding, restart and browser outage behavior require separate evidence."}, indent=2))
    return 0 if all(check["passed"] for check in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
