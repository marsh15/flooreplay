"""Operational receipts preserve correlation without request/source disclosure."""
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import delete

from flooreplay.db import session_scope
from flooreplay.operations import (
    OperationalEvent,
    install_operational_monitoring,
    operational_report,
)
from flooreplay.paid_models import AIRun, SpendEntry


def test_injected_failure_is_searchable_and_actor_scoped():
    actor, other = uuid4().hex, uuid4().hex
    app = FastAPI()
    install_operational_monitoring(app)

    @app.get('/imports/{private_id}')
    def fail(request: Request, private_id: str):
        from fastapi.responses import JSONResponse
        request.state.actor_id = actor
        request.state.failure_category = 'IMPORT_SOURCE_INVALID'
        return JSONResponse({'detail': 'simulated failure'}, status_code=503)

    response = TestClient(app).get('/imports/private-factory-secret?token=secret')
    request_id = response.headers['X-Request-ID']
    report = operational_report(actor, request_id)
    assert report['events'][0]['failure_category'] == 'IMPORT_SOURCE_INVALID'
    assert report['events'][0]['route'] == '/imports/{private_id}'
    assert report['alerts'][0]['request_id'] == request_id
    assert 'private-factory-secret' not in str(report) and 'token=secret' not in str(report)
    assert operational_report(other, request_id)['events'] == []
    with session_scope() as session:
        session.execute(delete(OperationalEvent).where(OperationalEvent.actor_id == actor))


def test_stale_generation_remains_uncertain_without_dispatch_or_release():
    actor = uuid4().hex
    with session_scope() as session:
        entry = SpendEntry(user_id=actor, purpose='development', operation='generation', status='RESERVED', reserved_inr=5, charged_inr=0, charged_usd=0, price_table={'inr_per_usd': 90}, details={}, expires_at=datetime.now(UTC) - timedelta(seconds=5))
        session.add(entry)
        session.flush()
        run = AIRun(user_id=actor, request_key=uuid4().hex, analysis_id='ops-test', identity=uuid4().hex, task='question', question='private secret question', status='RUNNING', packet={'incident_id': 'private-factory-ops-test'}, configuration={'request_id': 'correlated-test'}, attempts=[], reservation_id=entry.id)
        session.add(run)
        session.flush()
        run_id, entry_id = run.id, entry.id
    first = operational_report(actor)
    second = operational_report(actor)
    assert first['operations'][0]['status'] == second['operations'][0]['status'] == 'UNCERTAIN'
    assert first['alerts'][0]['code'] == 'UNCERTAIN_PROVIDER_CHARGE'
    assert 'private secret question' not in str(first)
    assert operational_report(uuid4().hex)['operations'] == []
    with session_scope() as session:
        stored = session.get(SpendEntry, entry_id)
        assert stored and stored.status == 'UNCERTAIN' and stored.reserved_inr == 5
        session.execute(delete(AIRun).where(AIRun.id == run_id))
        session.execute(delete(SpendEntry).where(SpendEntry.id == entry_id))


def test_unhandled_failure_has_same_correlation_and_scrubbed_logs(caplog):
    import logging
    app = FastAPI()
    install_operational_monitoring(app)
    actor = uuid4().hex

    @app.get('/unexpected/{source_id}')
    def fail(request: Request, source_id: str):
        request.state.actor_id = actor
        raise RuntimeError('confidential-source-payload')

    with caplog.at_level(logging.INFO, logger='flooreplay.operations'):
        response = TestClient(app).get('/unexpected/private-id?q=private-query')
    assert response.status_code == 503
    assert response.json()['trace_id'] == response.headers['X-Request-ID']
    assert 'confidential-source-payload' not in response.text + caplog.text
    assert 'private-query' not in caplog.text
    assert logging.getLogger('uvicorn.access').disabled
    report = operational_report(actor, response.headers['X-Request-ID'])
    assert report['events'][0]['failure_category'] == 'UNAVAILABLE'
    with session_scope() as session:
        session.execute(delete(OperationalEvent).where(OperationalEvent.actor_id == actor))
