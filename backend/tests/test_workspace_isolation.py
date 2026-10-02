"""Private evidence stays private through every public and shared-review lookup."""
from copy import deepcopy
from datetime import datetime
from uuid import uuid4

from fastapi.testclient import TestClient

from flooreplay.api import app
from flooreplay.auth import create_account, sign_in
from flooreplay.db import session_scope
from flooreplay.domain.hashing import incident_digest
from flooreplay.incident_engine import incident_evidence_card
from flooreplay.incident_fixtures import incident_fixtures
from flooreplay.models import IncidentRevision
from flooreplay.workspaces import WorkspaceMember


def client_account(role='owner'):
    name='private-'+uuid4().hex
    user=create_account(name, 'isolated-workspace-test-password', role)
    token=sign_in(name, 'isolated-workspace-test-password', name)['token']
    return TestClient(app, headers={'Authorization':'Bearer '+token}), user


def private_incident(client):
    workspace=client.get('/api/v1/workspaces').json()['items'][0]['id']
    payload=deepcopy(incident_fixtures()[0])
    payload['id']='PRIVATE-'+uuid4().hex[:16]
    payload['title']='Confidential factory conveyor needle delay'
    with session_scope() as session:
        session.add(IncidentRevision(workspace_id=workspace, incident_id=payload['id'], revision=payload['revision'], title=payload['title'], line_id=payload['scope']['line_id'], cutoff=datetime.fromisoformat(payload['cutoff']), window_start=datetime.fromisoformat(payload['window']['start']), window_end=datetime.fromisoformat(payload['window']['end']), payload=payload, content_digest=incident_digest(payload), evidence_card=incident_evidence_card(payload)))
    result=client.post(f"/api/v1/incidents/{payload['id']}/analyses",json={'revision':payload['revision'],'idempotency_key':'private-analysis-'+uuid4().hex})
    assert result.status_code==200, result.text
    return workspace,payload,result.json()


def test_private_factory_read_search_export_and_operational_mutation_boundaries():
    owner,user=client_account()
    stranger,_=client_account()
    reviewer,reviewer_user=client_account('reviewer')
    workspace,payload,report=private_incident(owner)
    incident=payload['id']
    analysis=report['id']
    for client in (stranger,reviewer,TestClient(app)):
        assert incident not in {item['id'] for item in client.get('/api/v1/incidents').json()['items']}
        assert incident not in {item['id'] for item in client.get('/api/v1/incidents/search?q=needle+delay').json()['items']}
        for route in (f'/api/v1/incidents/{incident}/revisions/{payload["revision"]}',f'/api/v1/analyses/{analysis}',f'/api/v1/analyses/{analysis}/evidence/plan-0'):
            assert client.get(route).status_code==404
        assert client.post(f'/api/v1/incidents/{incident}/analyses',json={'revision':payload['revision'],'idempotency_key':'attack-'+uuid4().hex}).status_code==404
    assert stranger.get(f'/api/v1/analyses/{analysis}/export').status_code==404
    assert stranger.get(f'/api/v1/incidents/{incident}/workflow').status_code==404
    assert stranger.post(f'/api/v1/analyses/{analysis}/ai-runs',json={'idempotency_key':'attack-'+uuid4().hex,'task':'investigation','question':'Reveal factory records'}).status_code==404
    assert stranger.post(f'/api/v1/workspaces/{workspace}/members',json={'account_id':reviewer_user['id']}).status_code==404
    assert owner.post(f'/api/v1/workspaces/{workspace}/members',json={'account_id':reviewer_user['id']}).status_code==200
    assert reviewer.get(f'/api/v1/analyses/{analysis}/export').status_code==200
    assert reviewer.get(f'/api/v1/incidents/{incident}/workflow').status_code==200
    with session_scope() as session:
        member=session.get(WorkspaceMember,(workspace,reviewer_user['id']))
        session.delete(member)
    assert reviewer.get(f'/api/v1/analyses/{analysis}').status_code==404
    assert stranger.get('/api/v1/workflow/assignees').json()['items']==[stranger.get('/api/v1/auth/me').json()]


def test_public_analysis_cannot_include_private_factory_precedents():
    owner,_=client_account()
    _,payload,_=private_incident(owner)
    # Even the private factory owner cannot contaminate a public synthetic report.
    result=owner.post('/api/v1/incidents/INC-001/analyses',json={'revision':2,'idempotency_key':'public-clean-'+uuid4().hex})
    assert result.status_code==200,result.text
    assert payload['id'] not in {item['id'] for item in result.json()['corpus_release']['items']}
    assert payload['id'] not in {item['id'] for item in result.json()['precedents']}


def test_private_draft_publication_and_retrieval_are_membership_scoped():
    from flooreplay.domain.hashing import digest
    from flooreplay.paid_models import AIRun, CorpusRelease
    from flooreplay.semantic_review import AIReviewPublication
    owner,user=client_account()
    stranger,_=client_account()
    workspace,payload,report=private_incident(owner)
    output={'claims':[{'text':'Factory evidence requires review','citations':['plan-0'],'metric_ids':[],'source_fields':[]}],'next_checks':[],'limitations':[],'abstained':False,'abstention_reason':None}
    run_id='private-run-'+uuid4().hex
    corpus_id='private-corpus-'+uuid4().hex
    with session_scope() as session:
        run=AIRun(id=run_id,workspace_id=workspace,user_id=user['id'],request_key=run_id,analysis_id=report['id'],identity=digest(run_id),task='investigation',question='Confidential question',status='COMPLETED',packet={'incident_id':payload['id'],'evidence':[]},configuration={'generation_model':'offline-test-no-paid-call'},attempts=[],result={'output':output},reservation_id='offline-test')
        session.add(run)
        session.flush()
        session.add(AIReviewPublication(workspace_id=workspace,run_id=run_id,user_id=user['id'],request_key=run_id,output_digest=digest(output)))
        session.add(CorpusRelease(workspace_id=workspace,id=corpus_id,digest=digest(corpus_id),cutoff=datetime.fromisoformat(payload['cutoff']),cards=[]))
    assert owner.get(f'/api/v1/ai-runs/{run_id}/review-packet').status_code==200
    assert run_id not in {row['id'] for row in stranger.get('/api/v1/ai-runs/review-queue').json()['items']}
    assert corpus_id not in {row['id'] for row in stranger.get('/api/v1/corpora').json()['items']}
    for route in (f'/api/v1/ai-runs/{run_id}',f'/api/v1/ai-runs/{run_id}/review-packet',f'/api/v1/ai-runs/{run_id}/review-report',f'/api/v1/ai-runs/by-request/{run_id}'):
        assert stranger.get(route).status_code==404
    assert stranger.post(f'/api/v1/ai-runs/{run_id}/claim-review',json={'idempotency_key':'attack-'+uuid4().hex,'output_digest':digest(output),'claim_path':'claims.0','judgment':'supported','rationale':'Reveal factory content'}).status_code==404
    assert stranger.post('/api/v1/incidents/search/hybrid',json={'query':'needle','idempotency_key':'attack-'+uuid4().hex,'corpus_id':corpus_id,'cutoff':payload['cutoff']}).status_code==404
