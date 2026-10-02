#!/usr/bin/env python3
"""Exercise compatible API versions on an existing isolated restored test database."""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import secrets
import subprocess
import tarfile
import tempfile
import time
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from recovery_drill import command, snapshot, sql, validate_database

ROOT = Path(__file__).resolve().parents[1]


def validate_restore(name: str) -> str:
    validate_database(name)
    if not name.startswith('flooreplay_recovery_restore_'):
        raise ValueError('Only a dedicated restored drill database is permitted')
    return name


def validate_ref(ref: str) -> str:
    if not re.fullmatch(r'[0-9a-f]{7,40}', ref):
        raise ValueError('Use an explicit Git commit identity')
    resolved = command(['git', 'rev-parse', '--verify', ref + '^{commit}']).decode().strip()
    if subprocess.run(['git', 'merge-base', '--is-ancestor', 'ba91a26', resolved], cwd=ROOT, capture_output=True).returncode:
        raise ValueError('Rollback commit predates the reviewed private workspace boundary')
    if command(['git', 'show', resolved + ':backend/src/flooreplay/workspaces.py']).find(b'allowed_workspaces') < 0:
        raise ValueError('Rollback candidate must preserve the private workspace boundary')
    return resolved


def request(path: str, token: str | None = None, body: dict | None = None) -> tuple[int, dict]:
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    try:
        response = urlopen(Request('http://127.0.0.1:8004/api/v1' + path, data=json.dumps(body).encode() if body is not None else None, headers=headers), timeout=15)
    except HTTPError as error:
        response = error
    with response:
        return response.status, json.loads(response.read())


def launch(ref: str, database: str, directory: Path, resources: ExitStack):
    archive = command(['git', 'archive', ref, 'backend'])
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(directory, filter='data')
    env = dict(os.environ, PYTHONPATH=str(directory / 'backend/src'), FLOORREPLAY_DATABASE_URL=f'postgresql+psycopg://flooreplay_test@127.0.0.1:5435/{database}', FLOORREPLAY_OPENAI_API_KEY='', FLOORREPLAY_BUILD_ID=ref)
    log = resources.enter_context(tempfile.TemporaryFile())  # noqa: SIM115 - caller ExitStack owns the log
    process = subprocess.Popen([str(ROOT / 'backend/.venv/bin/python'), '-m', 'uvicorn', 'flooreplay.api:app', '--host', '127.0.0.1', '--port', '8004'], cwd=directory, env=env, stdout=log, stderr=log)
    started = time.monotonic()
    while time.monotonic() - started < 30:
        if process.poll() is not None:
            raise RuntimeError('Isolated API failed to start; private temporary log retained only in process')
        try:
            if request('/health/ready')[0] == 200:
                return process, log, env, round(time.monotonic() - started, 3)
        except (URLError, TimeoutError):
            pass
        time.sleep(.2)
    process.terminate()
    process.wait(timeout=10)
    raise RuntimeError('Readiness timeout')


def stop(process, log):
    process.terminate()
    process.wait(timeout=15)
    log.close()


def main() -> int:
    if not __debug__:
        raise RuntimeError('Run this acceptance harness without Python optimization')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True)
    parser.add_argument('--rollback-ref', default='ba91a26')
    parser.add_argument('--current-ref', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    database = validate_restore(args.database)
    old, current = validate_ref(args.rollback_ref), validate_ref(args.current_ref)
    if old == current:
        raise ValueError('Rollback and current versions must differ')
    try:
        request('/health/live')
    except URLError:
        pass
    else:
        raise ValueError('Port 8004 already occupied; refusing to interact with it')
    before = snapshot('flooreplay-test-db-1', database)
    checks = []
    started = time.monotonic()
    password = secrets.token_urlsafe(32)
    suffix = secrets.token_hex(6)
    names = ['rollback-member-' + suffix, 'rollback-foreign-' + suffix]
    fixture = sql('flooreplay-test-db-1', database, "SELECT a.workspace_id || '|' || a.incident_id || '|' || a.revision FROM incident_analyses a WHERE a.workspace_id <> 'public-demo' AND jsonb_array_length(a.report->'proposals') > 0 AND a.revision=(SELECT max(r.revision) FROM incident_revisions r WHERE r.incident_id=a.incident_id) ORDER BY a.incident_id LIMIT 1").decode().strip().split('|')
    if len(fixture) != 3:
        raise ValueError('Restore must contain a private synthetic incident')
    workspace, incident, revision = fixture
    with tempfile.TemporaryDirectory(prefix='flooreplay-rollback-') as directory, ExitStack() as resources:
        process, log, _, initial_ready = launch(current, database, Path(directory) / 'initial-current', resources)
        try:
            assert request('/capabilities')[1]['build_id'] == current
            checks.append({'check':'initial current release ready before rollback','passed':True})
        finally:
            stop(process, log)
        process, log, env, old_ready = launch(old, database, Path(directory) / 'old', resources)
        try:
            script = """import json,sys
from flooreplay.auth import create_account
from flooreplay.db import session_scope
from flooreplay.workspaces import WorkspaceMember
v=json.load(sys.stdin)
a=[create_account(n,v['password'],'owner') for n in v['names']]
with session_scope() as s:s.add(WorkspaceMember(workspace_id=v['workspace'],account_id=a[0]['id'],role='member'))
"""
            subprocess.run([str(ROOT / 'backend/.venv/bin/python'), '-c', script], input=json.dumps({'password':password,'names':names,'workspace':workspace}).encode(), env=env, cwd=directory, check=True, capture_output=True)
            tokens = []
            for name in names:
                status, payload = request('/auth/login', body={'username':name,'password':password})
                assert status == 200
                tokens.append(payload['token'])
            checks.append({'check':'two HTTP logins','passed':True})
            assert request('/incidents')[0] == 200
            assert request('/capabilities')[1]['build_id'] == old
            assert request(f'/incidents/{incident}/revisions/{revision}', tokens[0])[0] == 200
            status, analysis = request(f'/incidents/{incident}/analyses', tokens[0], {'revision':int(revision),'idempotency_key':'rollback-analysis-'+suffix})
            assert status == 200
            analysis_id = analysis['id']
            proposal = analysis['proposals'][0]['id']
            evidence_id = analysis['timeline'][0]['id']
            status, _ = request(f'/analyses/{analysis_id}/proposals/{proposal}/submit', tokens[0], {'idempotency_key':'rollback-submit-'+suffix,'decision':'PENDING_REVIEW','rationale':'Synthetic rollback persistence check'})
            assert status == 200
            status, review = request(f'/analyses/{analysis_id}/proposals/{proposal}/review', tokens[0], {'idempotency_key':'rollback-review-'+suffix,'decision':'REJECTED','rationale':'Synthetic rollback persistence check'})
            assert status == 200
            assert request(f'/analyses/{analysis_id}/export', tokens[0])[0] == 200
            checks.append({'check':'old application private analysis review export','passed':True})
            for path in [f'/incidents/{incident}/revisions/{revision}',f'/analyses/{analysis_id}',f'/analyses/{analysis_id}/evidence/{evidence_id}',f'/analyses/{analysis_id}/export']:
                assert request(path, tokens[1])[0] == 404
            for path in ['/incidents?limit=200','/incidents/search?q='+incident]:
                assert incident not in json.dumps(request(path,tokens[1])[1])
            checks.append({'check':'old application foreign list search direct evidence export denied','passed':True})
        finally:
            stop(process, log)
        restart = time.monotonic()
        process, log, _, current_ready = launch(current, database, Path(directory) / 'current', resources)
        try:
            assert request('/capabilities')[1]['build_id'] == current
            status, export = request(f'/analyses/{analysis_id}/export', tokens[0])
            assert status == 200 and review['id'] in json.dumps(export)
            for path in [f'/incidents/{incident}/revisions/{revision}',f'/analyses/{analysis_id}',f'/analyses/{analysis_id}/evidence/{evidence_id}',f'/analyses/{analysis_id}/export']:
                assert request(path,tokens[1])[0] == 404
            checks.append({'check':'current restart preserves authenticated review and private boundary','passed':True})
            restart_seconds = round(time.monotonic()-restart,3)
        finally:
            stop(process,log)
    after = snapshot('flooreplay-test-db-1',database)
    protected = ['incident_revisions','embedding_artifacts','spend_entries','ai_claim_reviews']
    assert all(before[table] == after[table] for table in protected)
    assert after['accounts']['rows'] == before['accounts']['rows'] + 2
    assert after['incident_reviews']['rows'] == before['incident_reviews']['rows'] + 2
    report = {'recorded_at':datetime.now(UTC).isoformat(),'database':database,'rollback_ref':old,'current_ref':current,'schema_downgrade':False,'provider_calls':0,'synthetic_accounts_created':2,'checks':checks,'preserved_tables':protected,'initial_current_ready_seconds':initial_ready,'rollback_ready_seconds':old_ready,'current_ready_seconds':current_ready,'current_restart_and_verification_seconds':restart_seconds,'total_seconds':round(time.monotonic()-started,3),'passed':True,'scope':'Isolated local API-component rollback and return to current code; not hosted or frontend asset rollback','components_switched':['API'],'frontend_rollback_exercised':False,'frontend_policy':'Retain the authentication-boundary cache fix in the current frontend; ba91a26 and 61f64ef frontend assets are not approved rollback targets','unsafe_prior_public_release':'04e0466 rejected: lacks private workspace boundary'}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'passed':True,'report':str(args.output)}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
