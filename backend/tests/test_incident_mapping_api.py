"""Explicit CSV interpretations survive preview, publication and correction replay."""
from __future__ import annotations

import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from flooreplay.api import app
from flooreplay.db import session_scope
from flooreplay.models import IncidentAnalysis, IncidentRevision, IncidentSourceArtifact

pytestmark = pytest.mark.skipif(os.environ.get('FLOORREPLAY_SKIP_DB') == '1', reason='database not available')


def test_owner_mapping_create_correction_and_replay(owner_headers, reviewer_headers):
    client = TestClient(app, headers=owner_headers)
    incident_id = f'MAP-{uuid4().hex}'
    scope = {'factory': 'Mapped Factory', 'line_id': 'S9', 'order_id': 'M-1', 'style_id': 'M-ST', 'stage': 'sewing', 'unit': 'good_units'}
    raw = 'Ticket,Kind,Known,From,To,Qty,Equal Qty\nplan-m,baseline_plan,2026-09-30T08:00:00,2026-09-30T09:00:00,2026-09-30T09:15:00,20,20\nout-m,final_good_delta,2026-09-30T09:15:00,2026-09-30T09:00:00,2026-09-30T09:15:00,10,10\n'
    mapping = {'id': 'Ticket', 'record_type': 'Kind', 'available_at': 'Known', 'start': 'From', 'end': 'To', 'quantity': 'Qty'}
    defaults = {**scope, 'count_mode': 'delta'}
    inspect = {'raw_text': raw, 'filename': 'mapped.csv', 'profile': 'production-v1'}
    assert TestClient(app).post('/api/v1/incidents/imports/inspect', json=inspect).status_code == 401
    assert TestClient(app, headers=reviewer_headers).post('/api/v1/incidents/imports/inspect', json=inspect).status_code == 403
    inspected = client.post('/api/v1/incidents/imports/inspect', json=inspect)
    assert inspected.status_code == 200 and inspected.json()['sample_rows'][0]['Qty'] == '20'
    request = {'incident_id': incident_id, 'base_revision': 0, 'cutoff': '2026-09-30T09:15:00+05:30', 'scope': scope, **inspect, 'source_system': 'mapped-ledger', 'timezone': 'Asia/Kolkata', 'unit': 'good_units', 'column_mapping': mapping, 'field_defaults': defaults}
    preview = client.post('/api/v1/incidents/imports/preview', json=request)
    assert preview.status_code == 200 and preview.json()['status'] == 'READY'
    create = {'incident_id': incident_id, 'title': 'Explicitly mapped shift output', 'scope': scope, 'window': {'start': '2026-09-30T09:00:00+05:30', 'end': '2026-09-30T09:15:00+05:30'}, 'cutoff': request['cutoff'], 'raw_text': raw, 'source_system': 'mapped-ledger', 'timezone': 'Asia/Kolkata', 'filename': 'mapped.csv', 'preview_digest': preview.json()['preview_digest'], 'column_mapping': mapping, 'field_defaults': defaults, 'idempotency_key': uuid4().hex}
    try:
        changed_map = {**mapping, 'quantity': 'Equal Qty'}
        assert client.post('/api/v1/incidents', json={**create, 'column_mapping': changed_map}).json()['code'] == 'PREVIEW_MISMATCH'
        created = client.post('/api/v1/incidents', json=create)
        assert created.status_code == 200, created.text
        assert client.post('/api/v1/incidents', json=create).json() == created.json()
        assert client.post('/api/v1/incidents', json={**create, 'column_mapping': changed_map}).json()['code'] == 'IDEMPOTENCY_CONFLICT'
        with session_scope() as session:
            artifact = session.scalar(select(IncidentSourceArtifact).where(IncidentSourceArtifact.incident_id == incident_id))
            assert artifact.raw_bytes == raw.encode() and artifact.preview['column_mapping'] == mapping
            assert artifact.preview['field_defaults'] == defaults
        correction_raw = 'Ticket,Kind,Known,From,To,Qty,Corrects\ncorrected-m,final_good_delta,2026-09-30T09:20:00,2026-09-30T09:00:00,2026-09-30T09:15:00,12,out-m\n'
        correction = {**request, 'base_revision': 1, 'cutoff': '2026-09-30T09:25:00+05:30', 'raw_text': correction_raw, 'filename': 'correction.csv', 'column_mapping': {**mapping, 'supersedes_id': 'Corrects'}}
        correction.pop('scope')
        checked = client.post('/api/v1/incidents/imports/preview', json=correction)
        assert checked.status_code == 200 and checked.json()['scope'] == scope and checked.json()['status'] == 'READY'
        publication = {**correction, 'preview_digest': checked.json()['preview_digest'], 'idempotency_key': uuid4().hex}
        assert client.post('/api/v1/incidents/imports/publish', json={**publication, 'field_defaults': {**defaults, 'source_id': 'changed-source'}}).json()['code'] == 'PREVIEW_MISMATCH'
        published = client.post('/api/v1/incidents/imports/publish', json=publication)
        assert published.status_code == 200, published.text
        assert published.json()['revision'] == 2
        assert client.post('/api/v1/incidents/imports/publish', json=publication).json() == published.json()
        assert client.post('/api/v1/incidents/imports/publish', json={**publication, 'field_defaults': {**defaults, 'source_id': 'changed-source'}}).json()['code'] == 'IDEMPOTENCY_CONFLICT'
        old = client.get(f'/api/v1/incidents/{incident_id}/revisions/1').json()
        assert old['output_buckets'][0]['quantity'] == 10
        analysis = client.post(f'/api/v1/incidents/{incident_id}/analyses', json={'revision': 2, 'idempotency_key': uuid4().hex}).json()
        assert analysis['metrics']['shortfall'] == 8
        assert analysis['metrics']['inputs'][0]['output'] == {'id': 'corrected-m', 'quantity': 12}
        assert client.post('/api/v1/incidents/imports/preview', json={**correction, 'scope': {**scope, 'line_id': 'S8'}}).json()['code'] == 'SCOPE_MISMATCH'
    finally:
        with session_scope() as session:
            session.execute(delete(IncidentAnalysis).where(IncidentAnalysis.incident_id == incident_id))
            session.execute(delete(IncidentSourceArtifact).where(IncidentSourceArtifact.incident_id == incident_id))
            session.execute(delete(IncidentRevision).where(IncidentRevision.incident_id == incident_id))
