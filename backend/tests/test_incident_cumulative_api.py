"""Cumulative counter exports publish derived deltas and keep every reading traceable."""
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

SCOPE = {'factory': 'Counter Factory', 'line_id': 'S7', 'order_id': 'C-1', 'style_id': 'C-ST', 'stage': 'sewing', 'unit': 'good_units'}
MAPPING = {'id': 'Ticket', 'record_type': 'Kind', 'available_at': 'Known', 'start': 'From', 'end': 'To', 'quantity': 'Counter'}


def _publish_readings(client: TestClient, incident_id: str, raw: str, cutoff: str) -> dict:
    request = {'incident_id': incident_id, 'base_revision': 1, 'cutoff': cutoff, 'raw_text': raw, 'filename': 'counter.csv', 'profile': 'production-v1', 'source_system': 'line-counter', 'timezone': 'Asia/Kolkata', 'unit': 'good_units', 'column_mapping': MAPPING, 'field_defaults': {**SCOPE, 'count_mode': 'cumulative'}}
    preview = client.post('/api/v1/incidents/imports/preview', json=request)
    assert preview.status_code == 200 and preview.json()['status'] == 'READY', preview.text
    published = client.post('/api/v1/incidents/imports/publish', json={**request, 'preview_digest': preview.json()['preview_digest'], 'idempotency_key': uuid4().hex})
    assert published.status_code == 200, published.text
    return preview.json()


def test_cumulative_counter_export_produces_a_complete_shortfall(owner_headers):
    client = TestClient(app, headers=owner_headers)
    plan = 'Ticket,Kind,Known,From,To,Qty\nplan-1,baseline_plan,2026-09-30T08:00:00,2026-09-30T09:00:00,2026-09-30T09:15:00,20\nplan-2,baseline_plan,2026-09-30T08:00:00,2026-09-30T09:15:00,2026-09-30T09:30:00,20\n'
    plan_mapping = {**MAPPING, 'quantity': 'Qty'}
    base = {'incident_id': f'CUM-{uuid4().hex}', 'base_revision': 0, 'cutoff': '2026-09-30T09:00:00+05:30', 'scope': SCOPE, 'raw_text': plan, 'filename': 'plan.csv', 'profile': 'production-v1', 'source_system': 'planning', 'timezone': 'Asia/Kolkata', 'unit': 'good_units', 'column_mapping': plan_mapping, 'field_defaults': {**SCOPE, 'count_mode': 'delta'}}
    preview = client.post('/api/v1/incidents/imports/preview', json=base).json()
    create = {key: base[key] for key in ('incident_id', 'scope', 'cutoff', 'raw_text', 'source_system', 'timezone', 'filename', 'column_mapping', 'field_defaults')}
    created = client.post('/api/v1/incidents', json={**create, 'title': 'Counter export shift', 'window': {'start': '2026-09-30T09:00:00+05:30', 'end': '2026-09-30T09:30:00+05:30'}, 'preview_digest': preview['preview_digest'], 'idempotency_key': uuid4().hex})
    assert created.status_code == 200, created.text
    incident_id = created.json()['id']
    try:
        # The 08:45 reading anchors the counter so the first planned interval can be derived.
        readings = 'Ticket,Kind,Known,From,To,Counter\nr0,final_good_delta,2026-09-30T09:01:00,2026-09-30T08:45:00,2026-09-30T09:00:00,100\nr1,final_good_delta,2026-09-30T09:16:00,2026-09-30T09:00:00,2026-09-30T09:15:00,112\nr2,final_good_delta,2026-09-30T09:31:00,2026-09-30T09:15:00,2026-09-30T09:30:00,130\n'
        checked = _publish_readings(client, incident_id, readings, '2026-09-30T09:35:00+05:30')
        assert [entry['disposition'] for entry in checked['cumulative_readings']] == ['ANCHOR', 'DERIVED', 'DERIVED']
        revision = client.get(f'/api/v1/incidents/{incident_id}/revisions/2').json()
        assert [(row['id'], row['quantity'], row['cumulative_reading']) for row in revision['output_buckets']] == [('r1', 12, 112), ('r2', 18, 130)]
        analysis = client.post(f'/api/v1/incidents/{incident_id}/analyses', json={'revision': 2, 'idempotency_key': uuid4().hex}).json()
        assert analysis['metrics']['status'] == 'COMPLETE'
        assert (analysis['metrics']['planned'], analysis['metrics']['observed'], analysis['metrics']['shortfall']) == (40, 30, 10)
        with session_scope() as session:
            artifact = session.scalar(select(IncidentSourceArtifact).where(IncidentSourceArtifact.incident_id == incident_id, IncidentSourceArtifact.revision == 2))
            # The anchor reading is not evidence of interval output, but its original bytes and disposition stay with the revision.
            assert artifact.raw_bytes == readings.encode()
            assert artifact.preview['cumulative_readings'][0]['id'] == 'r0'
    finally:
        with session_scope() as session:
            session.execute(delete(IncidentAnalysis).where(IncidentAnalysis.incident_id == incident_id))
            session.execute(delete(IncidentSourceArtifact).where(IncidentSourceArtifact.incident_id == incident_id))
            session.execute(delete(IncidentRevision).where(IncidentRevision.incident_id == incident_id))
