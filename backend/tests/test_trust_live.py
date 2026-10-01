"""Live execution controls are verified without contacting any provider."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from flooreplay import trust_live
from flooreplay.config import settings


def usage(global_left=100, evaluation_left=100, reviewer_left=100):
    return {'available_inr': global_left, 'purpose_available_inr': {'evaluation': evaluation_left, 'reviewer': reviewer_left}}


def test_budget_envelope_and_category_guards():
    trust_live._budget_guard(100, 0, usage(), False)
    for maximum, committed, available, hybrid in ((0.001, 0, usage(), False), (100, 100, usage(), False), (100, 0, usage(global_left=0), False), (100, 0, usage(evaluation_left=0), False), (100, 0, usage(reviewer_left=0), True)):
        with pytest.raises(ValueError):
            trust_live._budget_guard(maximum, committed, available, hybrid)
    entries = [SimpleNamespace(id='old', status='SETTLED', charged_inr=50, reserved_inr=50), SimpleNamespace(id='new', status='SETTLED', charged_inr=1, reserved_inr=2), SimpleNamespace(id='uncertain', status='UNCERTAIN', charged_inr=0, reserved_inr=3)]
    assert trust_live._committed(entries, ['old']) == 4


def test_live_configuration_refuses_invalid_envelope_and_test_allowance(monkeypatch):
    for amount in (0, -1, float('inf'), float('nan')):
        with pytest.raises(ValueError, match='positive finite'):
            trust_live._configuration('owner', 'corpus', amount, ['evidence_only'])
    monkeypatch.setattr(settings, 'database_url', 'postgresql+psycopg://localhost/flooreplay_test')
    with pytest.raises(ValueError, match='refuses a test database'):
        trust_live._configuration('owner', 'corpus', 10, ['evidence_only'])


def test_same_case_question_contains_recorded_types_without_using_blind_rubric():
    case = {'incident': {'events': [{'type': 'qc_hold'}, {'type': 'machine_interruption'}]}}
    question = trust_live._question(case)
    assert 'qc_hold' in question and 'machine_interruption' in question
    assert question == trust_live._question(case)


def test_guard_failure_never_calls_generation(monkeypatch, tmp_path: Path):
    release = Path('evaluation/ai-trust-fresh-v1')
    monkeypatch.setattr(settings, 'database_url', 'postgresql+psycopg://localhost/flooreplay_test')
    def forbidden(*args, **kwargs):
        raise AssertionError('No provider operation may begin with a test allowance')
    monkeypatch.setattr(trust_live.ai_runs, 'run_ai', forbidden)
    with pytest.raises(ValueError, match='refuses a test database'):
        trust_live.execute(release, tmp_path / 'receipts.jsonl', 'owner', 'corpus', 10, ['evidence_only'])
    assert not (tmp_path / 'receipts.jsonl').exists()


def test_execution_metadata_excludes_holdout_without_changing_frozen_observations(monkeypatch):
    from copy import deepcopy
    from datetime import UTC, datetime
    from uuid import uuid4

    from sqlalchemy import delete

    from flooreplay.db import session_scope
    from flooreplay.incident_fixtures import incident_fixtures
    from flooreplay.models import IncidentRevision
    from flooreplay.paid_models import CorpusRelease

    payload = deepcopy(incident_fixtures()[0])
    payload['id'] = 'TRUST-ADAPTER-' + uuid4().hex
    original = deepcopy(payload)
    corpus_id = 'adapter-' + uuid4().hex
    with session_scope() as session:
        session.add(CorpusRelease(id=corpus_id, digest='test-only', cutoff=datetime.now(UTC), cards=[]))
    monkeypatch.setattr(trust_live, 'create_analysis', lambda *args, **kwargs: SimpleNamespace(id='mock-analysis-no-provider'))
    try:
        assert trust_live._prepare({'case_id': 'test-routing', 'incident': payload}, corpus_id, 'mock-config') == 'mock-analysis-no-provider'
        assert payload == original
        with session_scope() as session:
            row = session.get(IncidentRevision, (payload['id'], payload['revision']))
            assert row.payload['dataset_split'] == 'locked'
            assert row.payload['evaluation_release'] == 'ai-trust-fresh-v1'
            for key in ('scope', 'events', 'plan_buckets', 'output_buckets', 'cutoff', 'window'):
                assert row.payload.get(key) == original.get(key)
        assert trust_live._prepare({'case_id': 'test-routing', 'incident': payload}, corpus_id, 'mock-config') == 'mock-analysis-no-provider'
    finally:
        with session_scope() as session:
            session.execute(delete(IncidentRevision).where(IncidentRevision.incident_id == payload['id']))
            session.execute(delete(CorpusRelease).where(CorpusRelease.id == corpus_id))
