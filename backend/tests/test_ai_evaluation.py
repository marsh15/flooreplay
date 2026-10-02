"""Provider metrics follow actual run provenance and exact human claim annotations."""
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import delete

from flooreplay import ai_runs, openai_provider
from flooreplay.ai_evaluation import AIClaimReview, provider_evaluation
from flooreplay.api import app
from flooreplay.config import settings
from flooreplay.db import session_scope
from flooreplay.incident_service import create_analysis
from flooreplay.paid_models import AIRun, SpendEntry


def test_recorded_provider_metrics_and_append_only_claim_review(monkeypatch, owner_headers, reviewer_headers):
    client = TestClient(app, headers=owner_headers)
    actor = client.get('/api/v1/auth/me').json()['id']
    monkeypatch.setattr(settings, 'openai_api_key', 'mock')
    def generate(*args):
        return {'provider_verified':True, 'output':{'claims':[{'text':'The recorded shortfall needs investigation.', 'evidence_ids':[], 'metric_ids':['shortfall'], 'historical_refs':[], 'source_fields':[]}], 'abstention_reasons':[]}, 'status':'completed', 'response_id':'test-receipt', 'request_id':'test-request', 'reported_model':settings.openai_generation_model, 'usage':{'input_tokens':100, 'output_tokens':50}}
    monkeypatch.setattr(openai_provider, 'generate', generate)
    with session_scope() as session:
        aid = create_analysis(session, 'INC-001', 2, 'evaluation-proof-' + uuid4().hex).id
    run = ai_runs.run_ai(aid, actor, 'evaluation-proof-' + uuid4().hex, 'question', 'What is known?', purpose='evaluation')
    try:
        with session_scope() as session:
            before = provider_evaluation(session)
            assert before['status'] == 'MEASURED_STRUCTURAL_ONLY'
            assert before['completed'] >= 1
            assert before['human_support_precision'] is None
        body = {'claim_path':'claims.0', 'supported':False, 'rationale':'The sources establish arithmetic, not cause.', 'idempotency_key':'claim-proof-' + uuid4().hex, 'actor':'client-spoof'}
        url = f"/api/v1/ai-runs/{run['id']}/claim-review"
        first = client.post(url, json=body)
        assert first.status_code == 200
        assert first.json()['actor'] == actor
        assert client.post(url, json=body).json()['id'] == first.json()['id']
        assert first.json()['rationale'] == body['rationale']
        assert first.json()['output_digest']
        assert first.json()['created_at']
        recovered = client.get(f"/api/v1/ai-runs/{run['id']}")
        assert recovered.status_code == 200
        assert recovered.json()['claim_reviews'] == [first.json()]
        anonymous = TestClient(app)
        assert anonymous.get(f"/api/v1/ai-runs/{run['id']}").status_code == 401
        other_reviewer = TestClient(app, headers=reviewer_headers)
        assert other_reviewer.get(f"/api/v1/ai-runs/{run['id']}").status_code == 404
        assert other_reviewer.post(url, json=body).status_code == 404
        assert client.post(url, json={**body, 'supported':True}).status_code == 409
        assert client.post(url, json={**body, 'claim_path':'claims.00'}).status_code == 422
        with session_scope() as session:
            after = provider_evaluation(session)
            assert after['status'] == 'MEASURED_WITH_ANNOTATIONS'
            assert after['reviewed_claims'] == 1 and after['supported_claims'] == 0
            assert after['human_support_precision'] is None
            assert after['declared_human_reviewed_claims'] == 0
            assert session.get(AIRun, run['id']).result['output'] == run['result']['output']
        assert client.get('/api/v1/evaluation-reports/incident-core-v1').json()['current_provider']['reviewed_claims'] == 1
        assert client.get('/api/v1/capabilities').json()['ai']['evaluation_status'] == 'MEASURED_WITH_ANNOTATIONS'
    finally:
        with session_scope() as session:
            record = session.get(AIRun, run['id'])
            entry_id = record.reservation_id
            session.execute(delete(AIClaimReview).where(AIClaimReview.run_id == run['id']))
            session.execute(delete(AIRun).where(AIRun.id == run['id']))
            session.execute(delete(SpendEntry).where(SpendEntry.id == entry_id))
