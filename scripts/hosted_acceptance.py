#!/usr/bin/env python3
"""Dated public hosted acceptance receipts; never infer protected or restart acceptance."""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
import uuid


def check_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.username or parsed.password or parsed.query or parsed.fragment or not parsed.hostname:
        raise ValueError('Use an origin/API URL without credentials, query or fragment')
    if parsed.scheme != 'https' and not (parsed.scheme == 'http' and parsed.hostname in {'localhost', '127.0.0.1'}):
        raise ValueError('Hosted checks require HTTPS; loopback HTTP is allowed for testing')
    return value.rstrip('/')


def run(api: str, frontend: str, expected_build: str) -> dict:
    api, frontend = check_url(api), check_url(frontend)
    checks = []

    def fetch(label: str, url: str, expected: tuple[int, ...] = (200,), body: dict | None = None) -> dict | None:
        start = time.perf_counter()
        request = Request(url, data=json.dumps(body).encode() if body is not None else None, headers={'Content-Type': 'application/json'})
        try:
            try:
                response = urlopen(request, timeout=90)
            except HTTPError as error:
                response = error
            with response:
                raw = response.read()
                status = response.status
            item = {'check': label, 'status': status, 'passed': status in expected, 'elapsed_ms': round((time.perf_counter() - start) * 1000, 2)}
            result = json.loads(raw) if url.startswith(api) and raw else None
            if isinstance(result, dict) and 'code' in result:
                item['failure_category'] = result['code']
            checks.append(item)
            return result if isinstance(result, dict) else None
        except (URLError, TimeoutError, ValueError):
            checks.append({'check': label, 'passed': False, 'failure_category': 'NETWORK_OR_RESPONSE_INVALID', 'elapsed_ms': round((time.perf_counter() - start) * 1000, 2)})
            return None

    fetch('liveness', api + '/health/live')
    fetch('database_readiness', api + '/health/ready')
    capabilities = fetch('public_capabilities', api + '/capabilities') or {}
    build = capabilities.get('build_id')
    checks.append({'check': 'deployed_build_identity', 'passed': build == expected_build, 'observed_build': build, 'expected_build': expected_build})
    fetch('public_synthetic_library', api + '/incidents')
    for route in ('/', '/incidents/INC-001?revision=2', '/evaluation'):
        fetch('spa_delivery:' + route, frontend + route)
    for route, body in (
        ('/analyses/no-access/ai-runs', {'task': 'investigation', 'idempotency_key': 'acceptance-anonymous'}),
        ('/incidents/search/hybrid', {'query': 'synthetic', 'corpus_id': 'no-access', 'cutoff': '2026-10-01T00:00:00Z', 'idempotency_key': 'acceptance-anonymous'}),
        ('/incidents/imports/preview', {}),
    ):
        fetch('anonymous_denial:' + route, api + route, (401, 403), body)
    report = fetch('deterministic_synthetic_investigation', api + '/incidents/INC-001/analyses', body={'revision': 2, 'idempotency_key': 'hosted-acceptance-' + uuid.uuid4().hex})
    identity = report.get('id') if report else None
    if isinstance(identity, str):
        fetch('saved_report_read', api + '/analyses/' + identity)
        fetch('cited_record_read', api + '/analyses/' + identity + '/evidence/EV-MAT-1')
    return {
        'observed_at_utc': datetime.now(UTC).isoformat(), 'api_url': api, 'frontend_url': frontend,
        'expected_commit': expected_build, 'observed_api_build': build, 'synthetic_analysis_id': identity,
        'status': 'PUBLIC_CHECKS_PASSED_FULL_ACCEPTANCE_PENDING' if all(item['passed'] for item in checks) else 'PUBLIC_CHECKS_FAILED',
        'checks': checks, 'paid_calls': 0,
        'pending': ['authenticated owner/reviewer login', 'workspace permissions on deployed sixth-priority build', 'private synthetic imports/reviews/exports', 'hosted restart persistence', 'browser fallback/deep-link rendering', 'hosted sixth-priority release acceptance'],
        'limitations': ['SPA HTTP delivery does not establish rendered browser behavior.', 'This creates one deterministic synthetic report; no import or paid generation is dispatched.', 'Build identity is server-declared and checked against supplied Git deployment commit.', 'This is an observation of the deployed commit, not acceptance of undeployed local changes.'],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--api', required=True)
    parser.add_argument('--frontend', required=True)
    parser.add_argument('--expected-build', required=True)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    report = run(args.api, args.frontend, args.expected_build)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'status': report['status'], 'checks': len(report['checks']), 'report': str(args.output)}))
    return 0 if report['status'].startswith('PUBLIC_CHECKS_PASSED') else 1


if __name__ == '__main__':
    raise SystemExit(main())
