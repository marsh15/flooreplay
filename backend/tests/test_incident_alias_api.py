"""Reviewed identifier aliases survive preview, publication and idempotent retries."""
from __future__ import annotations

import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from flooreplay.api import app
from flooreplay.db import session_scope
from flooreplay.models import IncidentAnalysis, IncidentRevision, IncidentSourceArtifact

pytestmark = pytest.mark.skipif(os.environ.get('FLOORREPLAY_SKIP_DB') == '1', reason='database not available')

SCOPE = {'factory': 'Alias Factory', 'line_id': 'S5', 'order_id': 'A-1', 'style_id': 'A-ST', 'stage': 'sewing', 'unit': 'good_units'}
HEADER = 'id,record_type,available_at,start,end,quantity,unit,count_mode,factory,line_id,order_id,style_id,stage\n'


def test_aliased_line_publishes_with_its_original_identity(owner_headers):
    client = TestClient(app, headers=owner_headers)
    plan = HEADER + 'plan-a,baseline_plan,2026-09-30T08:00:00+05:30,2026-09-30T09:00:00+05:30,2026-09-30T09:15:00+05:30,20,good_units,delta,Alias Factory,S5,A-1,A-ST,sewing\n'
    base = {'incident_id': f'ALIAS-{uuid4().hex}', 'base_revision': 0, 'cutoff': '2026-09-30T09:00:00+05:30', 'scope': SCOPE, 'raw_text': plan, 'filename': 'plan.csv', 'profile': 'production-v1', 'source_system': 'planning', 'timezone': 'Asia/Kolkata', 'unit': 'good_units'}
    preview = client.post('/api/v1/incidents/imports/preview', json=base).json()
    create = {key: base[key] for key in ('incident_id', 'scope', 'cutoff', 'raw_text', 'source_system', 'timezone', 'filename')}
    created = client.post('/api/v1/incidents', json={**create, 'title': 'Alias reconciliation shift', 'window': {'start': '2026-09-30T09:00:00+05:30', 'end': '2026-09-30T09:15:00+05:30'}, 'preview_digest': preview['preview_digest'], 'idempotency_key': uuid4().hex})
    assert created.status_code == 200, created.text
    incident_id = created.json()['id']
    try:
        output = HEADER + 'out-a,final_good_delta,2026-09-30T09:16:00+05:30,2026-09-30T09:00:00+05:30,2026-09-30T09:15:00+05:30,14,good_units,delta,Alias Factory,Line 5,A-1,A-ST,sewing\n'
        request = {**base, 'incident_id': incident_id, 'base_revision': 1, 'cutoff': '2026-09-30T09:20:00+05:30', 'raw_text': output, 'filename': 'mes-output.csv', 'source_system': 'mes'}
        request.pop('scope')
        unaliased = client.post('/api/v1/incidents/imports/preview', json=request).json()
        assert unaliased['status'] == 'READY'
        assert client.post('/api/v1/incidents/imports/publish', json={**request, 'preview_digest': unaliased['preview_digest'], 'idempotency_key': uuid4().hex}).json()['code'] == 'SCOPE_MISMATCH'
        aliased_request = {**request, 'identifier_aliases': {'line_id': {'Line 5': 'S5'}}}
        foreign = client.post('/api/v1/incidents/imports/preview', json={**aliased_request, 'identifier_aliases': {'line_id': {'Line 5': 'S6'}}})
        assert foreign.status_code == 422 and "not this incident's line_id" in foreign.json()['message']
        checked = client.post('/api/v1/incidents/imports/preview', json=aliased_request).json()
        assert checked['status'] == 'READY' and checked['output_buckets'][0]['original_identity'] == {'line_id': 'Line 5'}
        publication = {**aliased_request, 'preview_digest': checked['preview_digest'], 'idempotency_key': uuid4().hex}
        published = client.post('/api/v1/incidents/imports/publish', json=publication)
        assert published.status_code == 200, published.text
        assert client.post('/api/v1/incidents/imports/publish', json=publication).json() == published.json()
        assert client.post('/api/v1/incidents/imports/publish', json={**publication, 'identifier_aliases': {'line_id': {'Line 5': 'S5', 'L5': 'S5'}}}).json()['code'] in {'IDEMPOTENCY_CONFLICT', 'PREVIEW_MISMATCH'}
        bucket = client.get(f'/api/v1/incidents/{incident_id}/revisions/2').json()['output_buckets'][0]
        assert bucket['line_id'] == 'S5' and bucket['original_identity'] == {'line_id': 'Line 5'} and bucket['alias_map_version'] == checked['alias_map_version']
        analysis = client.post(f'/api/v1/incidents/{incident_id}/analyses', json={'revision': 2, 'idempotency_key': uuid4().hex}).json()
        assert analysis['metrics']['shortfall'] == 6
    finally:
        with session_scope() as session:
            session.execute(delete(IncidentAnalysis).where(IncidentAnalysis.incident_id == incident_id))
            session.execute(delete(IncidentSourceArtifact).where(IncidentSourceArtifact.incident_id == incident_id))
            session.execute(delete(IncidentRevision).where(IncidentRevision.incident_id == incident_id))
