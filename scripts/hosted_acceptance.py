#!/usr/bin/env python3
"""Dated hosted acceptance receipts; never infer protected or restart acceptance.

Public checks always run. The authenticated stage runs only when owner and
reviewer credentials are in the environment and --workspace names a private
workspace the owner belongs to. It creates one synthetic incident there and
records its identity, so a later run with --verify-persisted can confirm those
records survived an API restart. Credentials are never written to the report.
"""
from __future__ import annotations

import argparse
import json
import os
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

CREDENTIALS = {
    'owner': ('FLOORREPLAY_ACCEPTANCE_OWNER', 'FLOORREPLAY_ACCEPTANCE_OWNER_PASSWORD'),
    'reviewer': ('FLOORREPLAY_ACCEPTANCE_REVIEWER', 'FLOORREPLAY_ACCEPTANCE_REVIEWER_PASSWORD'),
}
PUBLIC_PENDING = ['authenticated owner/reviewer login', 'workspace permissions on the deployed build', 'private synthetic imports/reviews/exports', 'hosted restart persistence', 'browser fallback/deep-link rendering']
Fetch = Callable[..., 'dict | None']


def check_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.username or parsed.password or parsed.query or parsed.fragment or not parsed.hostname:
        raise ValueError('Use an origin/API URL without credentials, query or fragment')
    if parsed.scheme != 'https' and not (parsed.scheme == 'http' and parsed.hostname in {'localhost', '127.0.0.1'}):
        raise ValueError('Hosted checks require HTTPS; loopback HTTP is allowed for testing')
    return value.rstrip('/')


def credentials(role: str) -> tuple[str, str] | None:
    user, password = (os.environ.get(name, '') for name in CREDENTIALS[role])
    return (user, password) if user and password else None


def make_fetch(api: str, checks: list[dict]) -> Fetch:
    def fetch(label: str, url: str, expected: tuple[int, ...] = (200,), body: dict | None = None, token: str | None = None) -> dict | None:
        start = time.perf_counter()
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = 'Bearer ' + token
        request = Request(url, data=json.dumps(body).encode() if body is not None else None, headers=headers)
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
    return fetch


def sign_in(fetch: Fetch, api: str, role: str) -> str | None:
    pair = credentials(role)
    if pair is None:
        return None
    session = fetch(f'{role}_sign_in', api + '/auth/login', body={'username': pair[0], 'password': pair[1]})
    token = session.get('token') if session else None
    return token if isinstance(token, str) else None


def public_checks(api: str, frontend: str, expected_build: str, fetch: Fetch, checks: list[dict]) -> tuple[str | None, str | None]:
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
    return build, identity if isinstance(identity, str) else None


def authenticated(api: str, fetch: Fetch, checks: list[dict], workspace: str) -> dict:
    """Owner/reviewer roles, private-workspace isolation, import, analysis, export and sign-out."""
    owner, reviewer = sign_in(fetch, api, 'owner'), sign_in(fetch, api, 'reviewer')
    if not owner or not reviewer:
        return {}
    me = fetch('owner_identity', api + '/auth/me', token=owner) or {}
    checks.append({'check': 'owner_role', 'passed': me.get('role') == 'owner'})
    reviewer_me = fetch('reviewer_identity', api + '/auth/me', token=reviewer) or {}
    checks.append({'check': 'reviewer_role', 'passed': reviewer_me.get('role') == 'reviewer'})
    memberships = (fetch('owner_workspaces', api + '/workspaces', token=owner) or {}).get('items', [])
    checks.append({'check': 'owner_private_workspace_membership', 'passed': any(item.get('id') == workspace and item.get('visibility') == 'private' for item in memberships)})
    reviewer_member = any(item.get('id') == workspace for item in (fetch('reviewer_workspaces', api + '/workspaces', token=reviewer) or {}).get('items', []))

    stamp = uuid.uuid4().hex[:12]
    scope = {'factory': 'Acceptance synthetic factory', 'line_id': f'ACC-{stamp}', 'order_id': f'ACC-ORD-{stamp}', 'style_id': 'ACC-STYLE', 'stage': 'sewing', 'unit': 'good_units'}
    header = 'id,record_type,available_at,start,end,quantity,unit,count_mode,factory,line_id,order_id,style_id,stage\n'
    tail = ',good_units,delta,' + ','.join(scope[field] for field in ('factory', 'line_id', 'order_id', 'style_id', 'stage')) + '\n'
    plan = header + f'acc-plan-{stamp},baseline_plan,2026-10-01T08:00:00+05:30,2026-10-01T09:00:00+05:30,2026-10-01T09:15:00+05:30,20' + tail
    output = header + f'acc-out-{stamp},final_good_delta,2026-10-01T09:16:00+05:30,2026-10-01T09:00:00+05:30,2026-10-01T09:15:00+05:30,14' + tail
    common = {'workspace_id': workspace, 'profile': 'production-v1', 'source_system': 'hosted-acceptance', 'timezone': 'Asia/Kolkata', 'unit': 'good_units'}
    base = {**common, 'incident_id': f'ACC-{stamp}', 'base_revision': 0, 'cutoff': '2026-10-01T09:00:00+05:30', 'scope': scope, 'raw_text': plan, 'filename': 'acceptance-plan.csv'}
    fetch('reviewer_import_denied', api + '/incidents/imports/preview', (403,), base, reviewer)
    preview = fetch('owner_private_import_preview', api + '/incidents/imports/preview', body=base, token=owner) or {}
    created = fetch('owner_private_incident_create', api + '/incidents', body={
        'workspace_id': workspace, 'incident_id': base['incident_id'], 'title': 'Hosted acceptance synthetic incident', 'scope': scope,
        'window': {'start': '2026-10-01T09:00:00+05:30', 'end': '2026-10-01T09:15:00+05:30'}, 'cutoff': base['cutoff'], 'raw_text': plan,
        'source_system': common['source_system'], 'timezone': common['timezone'], 'filename': base['filename'],
        'preview_digest': preview.get('preview_digest', ''), 'idempotency_key': 'acceptance-create-' + stamp,
    }, token=owner) or {}
    incident = created.get('id')
    if not isinstance(incident, str):
        return {}
    fetch('anonymous_private_revision_hidden', api + f'/incidents/{incident}/revisions/1', (404,))
    append = {**common, 'incident_id': incident, 'base_revision': 1, 'cutoff': '2026-10-01T09:20:00+05:30', 'raw_text': output, 'filename': 'acceptance-output.csv'}
    checked = fetch('owner_private_append_preview', api + '/incidents/imports/preview', body=append, token=owner) or {}
    published = fetch('owner_private_append_publish', api + '/incidents/imports/publish', body={**append, 'preview_digest': checked.get('preview_digest', ''), 'idempotency_key': 'acceptance-append-' + stamp}, token=owner) or {}
    analysis = fetch('owner_private_analysis', api + f'/incidents/{incident}/analyses', body={'revision': 2, 'idempotency_key': 'acceptance-analysis-' + stamp}, token=owner) or {}
    checks.append({'check': 'private_shortfall_value', 'passed': (analysis.get('metrics') or {}).get('shortfall') == 6})
    analysis_id = analysis.get('id')
    if isinstance(analysis_id, str):
        fetch('owner_report_export', api + f'/analyses/{analysis_id}/export', token=owner)
        # A reviewer sees a private report only through workspace membership.
        if reviewer_member:
            fetch('member_reviewer_report_export', api + f'/analyses/{analysis_id}/export', token=reviewer)
        else:
            fetch('nonmember_reviewer_report_hidden', api + f'/analyses/{analysis_id}/export', (404,), token=reviewer)
    fetch('owner_source_health', api + f'/incidents/{incident}/revisions/2/source-health', token=owner)
    for role, token in (('owner', owner), ('reviewer', reviewer)):
        fetch(f'{role}_sign_out', api + '/auth/logout', body={}, token=token)
        fetch(f'{role}_revoked_token_rejected', api + '/auth/me', (401,), token=token)
    return {'workspace_id': workspace, 'reviewer_is_member': reviewer_member, 'incident_id': incident, 'revision': 2, 'content_digest': published.get('content_digest'), 'analysis_id': analysis_id}


def verify_persisted(api: str, fetch: Fetch, checks: list[dict], probe: dict) -> None:
    """After an API restart, the private records from an earlier run must read back unchanged."""
    owner = sign_in(fetch, api, 'owner')
    if not owner or not probe.get('incident_id'):
        checks.append({'check': 'restart_persistence', 'passed': False, 'failure_category': 'NO_OWNER_OR_PROBE'})
        return
    revision = fetch('persisted_private_revision', api + f"/incidents/{probe['incident_id']}/revisions/{probe['revision']}", token=owner) or {}
    checks.append({'check': 'restart_persistence', 'passed': bool(probe.get('content_digest')) and revision.get('content_digest') == probe['content_digest']})
    if probe.get('analysis_id'):
        fetch('persisted_private_analysis', api + f"/analyses/{probe['analysis_id']}", token=owner)
    fetch('owner_sign_out', api + '/auth/logout', body={}, token=owner)


def run(api: str, frontend: str, expected_build: str, workspace: str | None = None, persisted: dict | None = None) -> dict:
    api, frontend = check_url(api), check_url(frontend)
    checks: list[dict] = []
    fetch = make_fetch(api, checks)
    build, identity = public_checks(api, frontend, expected_build, fetch, checks)
    probe: dict = {}
    pending = PUBLIC_PENDING
    if persisted is not None:
        verify_persisted(api, fetch, checks, persisted)
        pending = ['browser fallback/deep-link rendering']
    elif workspace and credentials('owner') and credentials('reviewer'):
        probe = authenticated(api, fetch, checks, workspace)
        if not probe:
            checks.append({'check': 'authenticated_stage', 'passed': False, 'failure_category': 'SIGN_IN_OR_CREATE_FAILED'})
        pending = ['hosted restart persistence: restart the API, then rerun with --verify-persisted pointing at this report', 'browser fallback/deep-link rendering']
    stage = 'RESTART_PERSISTENCE' if persisted is not None else 'AUTHENTICATED' if workspace and credentials('owner') else 'PUBLIC'
    passed = all(item['passed'] for item in checks)
    return {
        'observed_at_utc': datetime.now(UTC).isoformat(), 'api_url': api, 'frontend_url': frontend,
        'expected_commit': expected_build, 'observed_api_build': build, 'synthetic_analysis_id': identity,
        'status': (f'{stage}_CHECKS_PASSED_FULL_ACCEPTANCE_PENDING' if pending else f'{stage}_CHECKS_PASSED') if passed else f'{stage}_CHECKS_FAILED',
        'checks': checks, 'paid_calls': 0, 'persistence_probe': probe or persisted or None, 'pending': pending,
        'limitations': [
            'SPA HTTP delivery does not establish rendered browser behavior.',
            'The public stage creates one deterministic synthetic report. The authenticated stage also creates one synthetic private incident with two revisions. Neither dispatches paid generation.',
            'Build identity is server-declared and checked against the supplied Git deployment commit.',
            'This is an observation of the deployed commit, not acceptance of undeployed local changes.',
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--api', required=True)
    parser.add_argument('--frontend', required=True)
    parser.add_argument('--expected-build', required=True)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--workspace', help='Private workspace ID for the authenticated stage; credentials come from FLOORREPLAY_ACCEPTANCE_* variables')
    parser.add_argument('--verify-persisted', type=Path, help='Earlier authenticated report whose private records must survive an API restart')
    args = parser.parse_args()
    persisted = json.loads(args.verify_persisted.read_text()).get('persistence_probe') if args.verify_persisted else None
    if args.verify_persisted and not persisted:
        parser.error('The earlier report has no persistence_probe; run the authenticated stage first')
    report = run(args.api, args.frontend, args.expected_build, args.workspace, persisted)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'status': report['status'], 'checks': len(report['checks']), 'report': str(args.output)}))
    return 0 if '_CHECKS_PASSED' in report['status'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
