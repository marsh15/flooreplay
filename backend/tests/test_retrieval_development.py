"""Development-only retrieval observations, never fresh holdout cases."""
from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from flooreplay import ai_runs, openai_provider
from flooreplay.config import settings
from flooreplay.db import session_scope
from flooreplay.domain.hashing import incident_digest
from flooreplay.incident_engine import incident_evidence_card
from flooreplay.incident_service import create_analysis
from flooreplay.models import IncidentAnalysis, IncidentRevision
from flooreplay.paid_models import AIRun, CorpusRelease, RetrievalRun, SpendEntry
from flooreplay.retrieval import hybrid_search, lexical_search, precedent_comparison, publish_corpus
from flooreplay.service import ServiceError


def development_payload(incident_id, cutoff, *, line='DEV-S', lineage=None, split='historical'):
    start = datetime(2026, 9, 20, 9, tzinfo=UTC)
    end = start + timedelta(minutes=15)
    return {'id': incident_id, 'revision': 1, 'title': 'Development material record', 'dataset_split': split, 'lineage_id': lineage or incident_id, 'scope': {'factory': 'Development factory', 'line_id': line, 'order_id': 'DEV-ORD', 'style_id': 'DEV-STYLE', 'stage': 'sewing', 'unit': 'good_units'}, 'window': {'start': start.isoformat(), 'end': end.isoformat()}, 'cutoff': cutoff.isoformat(), 'coverage': {'production': True}, 'plan_buckets': [{'id': 'plan-dev', 'kind': 'baseline_plan', 'start': start.isoformat(), 'end': end.isoformat(), 'quantity': 20, 'unit': 'good_units', 'available_at': (start - timedelta(hours=1)).isoformat()}], 'output_buckets': [{'id': 'output-dev', 'kind': 'final_good_delta', 'start': start.isoformat(), 'end': end.isoformat(), 'quantity': 10, 'unit': 'good_units', 'available_at': end.isoformat()}], 'events': [{'id': 'material-dev', 'type': 'material_readiness', 'summary': 'Development fabric material readiness observation.', 'occurred_at': start.isoformat(), 'available_at': end.isoformat()}]}


def test_precedent_comparison_separates_window_outputs_from_intervention_effects():
    before = development_payload('old', datetime(2026, 9, 20, 10, tzinfo=UTC), line='OLD-S')
    current = development_payload('new', datetime(2026, 9, 20, 11, tzinfo=UTC), line='NEW-S')
    result = precedent_comparison(current, before)
    assert any('Same stage: sewing' in fact for fact in result['comparison_facts'])
    assert any('Different line id' in difference for difference in result['differences'])
    assert any('recorded good output: 10 good_units' in fact for fact in result['comparison_facts'])
    assert any('not an intervention outcome' in fact for fact in result['comparison_facts'])
    assert any('Confirmed causal mechanisms' in item for item in result['missing_information'])
    assert result['historical_prerequisites'] and result['current_prerequisites']
    contradictory = deepcopy(before)
    contradictory['events'] = [{'id': 'block', 'type': 'line_block', 'summary': 'Source establishes a line block.', 'start': before['window']['start'], 'end': before['window']['end'], 'line_blocking': True, 'linked_categories': ['material'], 'available_at': before['cutoff']}, {'id': 'denial', 'type': 'routine_note', 'summary': 'Source disputes the line block.', 'occurred_at': before['window']['start'], 'contradiction_refs': ['block'], 'available_at': before['cutoff']}]
    checked = precedent_comparison(current, contradictory)
    assert not any('Shared established' in item for item in checked['comparison_facts'])


@pytest.fixture
def development_corpus():
    suffix = uuid4().hex
    prefix = f'RETRIEVAL-DEV-{suffix}'
    cutoff = datetime(2026, 9, 20, 10, tzinfo=UTC)
    current = development_payload(prefix + '-current', cutoff + timedelta(hours=1), lineage='current-lineage-' + suffix, split='development')
    payloads = [current, development_payload(prefix + '-old', cutoff), development_payload(prefix + '-future', cutoff + timedelta(hours=2)), development_payload(prefix + '-same-lineage', cutoff, lineage=current['lineage_id']), development_payload(prefix + '-locked', cutoff, split='locked')]
    with session_scope() as session:
        for payload in payloads:
            session.add(IncidentRevision(incident_id=payload['id'], revision=1, title=payload['title'], line_id=payload['scope']['line_id'], cutoff=datetime.fromisoformat(payload['cutoff']), window_start=datetime.fromisoformat(payload['window']['start']), window_end=datetime.fromisoformat(payload['window']['end']), payload=payload, content_digest=incident_digest(payload), evidence_card=incident_evidence_card(payload)))
        session.flush()
        corpus_id = prefix + '-corpus'
        publish_corpus(session, corpus_id, cutoff + timedelta(hours=3))
        # Keep this test's published corpus restricted to its independently authored development cards.
        corpus = session.get(CorpusRelease, corpus_id)
        corpus.cards = [card for card in corpus.cards if card['id'].startswith(prefix)]
        from flooreplay.domain.hashing import digest
        corpus.digest = digest(corpus.cards)
        analysis = create_analysis(session, current['id'], 1, uuid4().hex)
        analysis_id = analysis.id
    yield {'corpus_id': corpus_id, 'current': current, 'old': payloads[1], 'cutoff': cutoff + timedelta(hours=1), 'analysis_id': analysis_id, 'prefix': prefix}
    with session_scope() as session:
        runs = session.scalars(select(AIRun).where(AIRun.analysis_id == analysis_id)).all()
        entries = [run.reservation_id for run in runs]
        session.execute(delete(AIRun).where(AIRun.analysis_id == analysis_id))
        session.execute(delete(SpendEntry).where(SpendEntry.id.in_(entries)))
        session.execute(delete(RetrievalRun).where(RetrievalRun.user_id == prefix))
        session.execute(delete(CorpusRelease).where(CorpusRelease.id == corpus_id))
        session.execute(delete(IncidentAnalysis).where(IncidentAnalysis.incident_id.like(prefix + '%')))
        session.execute(delete(IncidentRevision).where(IncidentRevision.incident_id.like(prefix + '%')))


def test_lexical_unindexed_corpus_uses_no_provider_or_spend_and_preserves_cutoff(development_corpus, monkeypatch):
    case = development_corpus
    monkeypatch.setattr(openai_provider, 'embed', lambda *args, **kwargs: pytest.fail('Lexical retrieval must not embed a query'))
    monkeypatch.setattr(openai_provider, 'generate', lambda *args, **kwargs: pytest.fail('Lexical search must not generate'))
    first = lexical_search('material fabric', case['prefix'], 'local-search', case['corpus_id'], case['cutoff'], case['current']['id'])
    assert [item['id'] for item in first['results']] == [case['old']['id']]
    assert first['manifest']['mode'] == 'lexical' and first['manifest']['query_embedding_id'] is None
    assert first['results'][0]['missing_information']
    assert lexical_search('material fabric', case['prefix'], 'local-search', case['corpus_id'], case['cutoff'], case['current']['id']) == first
    with pytest.raises(ServiceError) as conflict:
        lexical_search('another query', case['prefix'], 'local-search', case['corpus_id'], case['cutoff'], case['current']['id'])
    assert conflict.value.code == 'IDEMPOTENCY_CONFLICT'
    empty = lexical_search('unrelated pneumatic shipment', case['prefix'], 'unrelated-query', case['corpus_id'], case['cutoff'], case['current']['id'])
    assert empty['results'] == [] and empty['status'] == 'NO_USEFUL_PRECEDENT'
    with session_scope() as session:
        assert not session.scalars(select(SpendEntry).where(SpendEntry.user_id == case['prefix'])).all()


def test_lexical_generation_attaches_manifest_without_paid_query_embedding(development_corpus, monkeypatch):
    case = development_corpus
    monkeypatch.setattr(settings, 'openai_api_key', 'mock-no-network')
    monkeypatch.setattr(openai_provider, 'embed', lambda *args, **kwargs: pytest.fail('Lexical generation must not embed'))
    def generate(*args):
        return {'provider_verified': True, 'output': {'claims': [{'text': 'One source leaves the cause unresolved.', 'evidence_ids': ['material-dev'], 'historical_refs': [], 'metric_ids': ['shortfall'], 'source_fields': []}], 'abstention_reasons': []}, 'status': 'completed', 'response_id': 'mock-dev', 'request_id': 'mock-dev', 'reported_model': settings.openai_generation_model, 'usage': {'input_tokens': 100, 'output_tokens': 100}}
    monkeypatch.setattr(openai_provider, 'generate', generate)
    result = ai_runs.run_ai(case['analysis_id'], case['prefix'], 'lexical-generation', 'question', 'material fabric', retrieval_mode='lexical', corpus_id=case['corpus_id'])
    assert result['status'] == 'COMPLETED' and result['output_digest']
    assert result['packet']['retrieval_manifest']['mode'] == 'lexical'
    assert result['packet']['historical_evidence']
    again = ai_runs.run_ai(case['analysis_id'], case['prefix'], 'lexical-generation', 'question', 'material fabric', retrieval_mode='lexical', corpus_id=case['corpus_id'])
    assert again['id'] == result['id'] and again['output_digest'] == result['output_digest']


def test_hybrid_empty_eligible_corpus_does_not_construct_query_embedding(development_corpus, monkeypatch):
    case = development_corpus
    monkeypatch.setattr(openai_provider, 'embed', lambda *args, **kwargs: pytest.fail('Empty eligible corpus must not construct embeddings'))
    empty = hybrid_search('material fabric', case['prefix'], 'empty-hybrid', case['corpus_id'], case['cutoff'] - timedelta(days=1), case['current']['id'])
    assert empty['status'] == 'NO_USEFUL_PRECEDENT' and empty['results'] == []
    assert empty['manifest']['query_embedding_id'] is None


def test_hybrid_unrelated_cached_vectors_have_no_useful_precedent(development_corpus, monkeypatch):
    from flooreplay.paid_models import EmbeddingArtifact
    from flooreplay.retrieval import PREPROCESSING, embedding_identity

    case = development_corpus
    query = 'unrelated pneumatic shipment'
    artifact_ids = []
    with session_scope() as session:
        corpus = session.get(CorpusRelease, case['corpus_id'])
        old = next(card for card in corpus.cards if card['id'] == case['old']['id'])
        for text, vector in ((old['content'], [1.0, 0.0] + [0.0] * 510), (query, [0.0, 1.0] + [0.0] * 510)):
            identity, normalized = embedding_identity(text)
            artifact_ids.append(identity)
            if session.get(EmbeddingArtifact, identity) is None:
                session.add(EmbeddingArtifact(id=identity, model=settings.openai_embedding_model, dimensions=512, preprocessing_version=PREPROCESSING, content=normalized, vector=vector, provider_usage={}))
    monkeypatch.setattr(openai_provider, 'embed', lambda *args, **kwargs: pytest.fail('Cached vectors must not cause provider traffic'))
    try:
        result = hybrid_search(query, case['prefix'], 'unrelated-hybrid', case['corpus_id'], case['cutoff'], case['current']['id'])
        assert result['results'] == [] and result['status'] == 'NO_USEFUL_PRECEDENT'
        assert result['manifest']['similarity_gate_is_semantic_validation'] is False
    finally:
        with session_scope() as session:
            session.execute(delete(EmbeddingArtifact).where(EmbeddingArtifact.id.in_(artifact_ids)))
