"""Shared review is explicit; declarations and conflicts are never erased."""
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from flooreplay.ai_evaluation import AIClaimReview
from flooreplay.api import app
from flooreplay.db import session_scope
from flooreplay.domain.hashing import digest
from flooreplay.paid_models import AIRun
from flooreplay.semantic_review import AIReviewPublication, AIRunAssessment


@pytest.fixture
def draft(owner_headers):
    owner = TestClient(app, headers=owner_headers)
    actor = owner.get('/api/v1/auth/me').json()['id']
    output = {'claims': [{'text': 'The source does not establish a confirmed cause.', 'evidence_ids': ['note-a'], 'metric_ids': [], 'historical_refs': [], 'source_fields': []}], 'abstention_reasons': ['The interval remains incomplete.']}
    with session_scope() as session:
        run = AIRun(user_id=actor, request_key=uuid4().hex, analysis_id='test-pinned-analysis', identity=uuid4().hex, task='question', question='Private question must stay private', status='COMPLETED', packet={'incident_id': 'synthetic-review', 'revision': 1, 'cutoff': '2026-09-20T09:30:00+05:30', 'evidence': [{'id': 'note-a', 'summary': 'Feeder issue observed; impact unknown.'}], 'metrics': [], 'historical_evidence': [], 'private_request': 'must-not-be-shared'}, configuration={'generation_model': 'mock-only'}, attempts=[], result={'output': output}, reservation_id='mock-only')
        session.add(run)
        session.flush()
        run_id = run.id
    yield owner, run_id, digest(output)
    with session_scope() as session:
        for model in (AIClaimReview, AIRunAssessment, AIReviewPublication):
            session.execute(delete(model).where(model.run_id == run_id))
        session.execute(delete(AIRun).where(AIRun.id == run_id))


def test_private_run_deliberate_publication_and_exact_digest(draft, reviewer_headers):
    owner, run_id, fingerprint = draft
    reviewer = TestClient(app, headers=reviewer_headers)
    prefix = f'/api/v1/ai-runs/{run_id}'
    assert TestClient(app).get('/api/v1/ai-runs/review-queue').status_code == 401
    assert reviewer.get(prefix).status_code == 404
    assert reviewer.get(prefix + '/review-packet').status_code == 404
    body = {'output_digest': fingerprint, 'idempotency_key': uuid4().hex}
    assert reviewer.post(prefix + '/publish-review', json=body).status_code == 404
    assert owner.post(prefix + '/publish-review', json={**body, 'output_digest': '0' * 64}).status_code == 409
    publication = owner.post(prefix + '/publish-review', json=body)
    assert publication.status_code == 200, publication.text
    assert owner.post(prefix + '/publish-review', json=body).json() == publication.json()
    assert any(item['id'] == run_id for item in reviewer.get('/api/v1/ai-runs/review-queue').json()['items'])
    packet = reviewer.get(prefix + '/review-packet').json()
    assert packet['output_digest'] == fingerprint and packet['packet']['revision'] == 1
    assert 'question' not in packet and 'request_key' not in packet and 'private_request' not in packet['packet']
    assert reviewer.get(prefix).status_code == 404
    annotation = {'claim_path': 'claims.0', 'output_digest': fingerprint, 'judgment': 'insufficient_evidence', 'flags': ['appropriate_abstention'], 'rationale': 'The cited observation leaves line impact unresolved.', 'reviewer_kind': 'ai_assistant', 'qualifications': 'Test simulation; no manufacturing qualification.', 'independent': True, 'idempotency_key': uuid4().hex}
    result = reviewer.post(prefix + '/claim-review', json=annotation)
    assert result.status_code == 200, result.text
    assert result.json()['supported'] is False and result.json()['judgment'] == 'insufficient_evidence'
    assert reviewer.post(prefix + '/claim-review', json=annotation).json() == result.json()
    assert reviewer.post(prefix + '/claim-review', json={**annotation, 'rationale': 'Changed intent.'}).status_code == 409
    assert reviewer.post(prefix + '/claim-review', json={**annotation, 'idempotency_key': uuid4().hex, 'supported': True}).status_code == 422
    assert reviewer.post(prefix + '/claim-review', json={**annotation, 'idempotency_key': uuid4().hex, 'output_digest': '0' * 64}).status_code == 409
    assert reviewer.post(prefix + '/claim-review', json={**annotation, 'idempotency_key': uuid4().hex, 'claim_path': 'claims.00'}).status_code == 422
    report = reviewer.get(prefix + '/review-report').json()
    assert report['total_claims'] == report['insufficient_evidence_claims'] == 1
    assert report['declared_independent_human_reviewers'] == 0 and report['status'] == 'AWAITING_INDEPENDENT_HUMAN_REVIEW'


def test_disagreements_history_and_run_level_assessment(draft, reviewer_headers):
    owner, run_id, fingerprint = draft
    reviewer = TestClient(app, headers=reviewer_headers)
    prefix = f'/api/v1/ai-runs/{run_id}'
    assert owner.post(prefix + '/publish-review', json={'output_digest': fingerprint, 'idempotency_key': uuid4().hex}).status_code == 200
    body = {'claim_path': 'claims.0', 'output_digest': fingerprint, 'judgment': 'supported', 'rationale': 'This faithfully describes the limited observation.', 'reviewer_kind': 'human', 'qualifications': 'Synthetic test declaration; not an actual practitioner review.', 'independent': True, 'idempotency_key': uuid4().hex}
    assert owner.post(prefix + '/claim-review', json=body).status_code == 422
    assert reviewer.post(prefix + '/claim-review', json={**body, 'qualifications': ''}).status_code == 422
    first = reviewer.post(prefix + '/claim-review', json=body)
    assert first.status_code == 200, first.text
    assert owner.post(prefix + '/claim-review', json={**body, 'judgment': 'unsupported', 'independent': False, 'idempotency_key': uuid4().hex}).status_code == 200
    report = reviewer.get(prefix + '/review-report').json()
    assert report['disagreements'][0]['claim_path'] == 'claims.0'
    assert report['supported_claims'] == report['unsupported_claims'] == 0 and report['status'] == 'PARTIAL_DECLARED_INDEPENDENT_REVIEW'
    assessment = {'output_digest': fingerprint, 'idempotency_key': uuid4().hex, 'reviewer_kind': 'human', 'qualifications': body['qualifications'], 'independent': True, 'usefulness': 'uncertain', 'omitted_contradictions': ['Opposing source needs review.'], 'attribution_errors': [], 'abstention': 'appropriate', 'rationale': 'Value has not been observed with a supervisor.', 'limitations': 'Synthetic test only.'}
    saved = reviewer.post(prefix + '/assessment', json=assessment)
    assert saved.status_code == 200, saved.text
    assert reviewer.post(prefix + '/assessment', json=assessment).json() == saved.json()
    assert reviewer.post(prefix + '/assessment', json={**assessment, 'usefulness': 'useful'}).status_code == 409
    report = reviewer.get(prefix + '/review-report').json()
    assert report['status'] == 'DECLARED_INDEPENDENT_REVIEW_COMPLETE' and report['independent_human_assessments'] == 1
    assert len(report['claim_reviews']) == 2 and len(report['disagreements']) == 1
