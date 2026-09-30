"""Provider mocks exercise durable operations without spending API allowance."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import pytest
from openai import APITimeoutError
from sqlalchemy import delete, select

from flooreplay import ai_runs, openai_provider
from flooreplay.ai_evaluation import AIClaimReview
from flooreplay.config import settings
from flooreplay.db import session_scope
from flooreplay.incident_service import create_analysis
from flooreplay.models import IncidentRevision
from flooreplay.paid_models import (
    AIRun,
    EmbeddingArtifact,
    RetrievalRun,
    SpendEntry,
    SpendingAllocation,
    now,
)
from flooreplay.retrieval import embedding_identity, hybrid_search, index_corpus, publish_corpus
from flooreplay.service import ServiceError
from flooreplay.spending import cost, move_allowance, reserve, usage_view


class AsyncClient:
    def __init__(self, **values):
        self.__dict__.update(values)
    async def __aenter__(self):
        return self
    async def __aexit__(self, *args):
        pass


@pytest.fixture(autouse=True)
def clean_paid_tables():
    with session_scope() as session:
        for model in (AIClaimReview, AIRun, RetrievalRun, EmbeddingArtifact, SpendEntry, SpendingAllocation):
            session.execute(delete(model))
    yield


def analysis_id():
    with session_scope() as session:
        return create_analysis(session, "INC-001", 1, "paid-test-" + uuid4().hex).id


def response(text="The evidence leaves the explanation unresolved."):
    return {"output": {"claims": [{"text": text, "evidence_ids": [], "metric_ids": ["shortfall"], "historical_refs": [], "source_fields": []}], "abstention_reasons": []}, "status": "completed", "response_id": "mock-response", "request_id": "mock-request", "reported_model": settings.openai_generation_model, "usage": {"input_tokens": 1000, "output_tokens": 100}}


def test_durable_repair_idempotence_and_conflict(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "mock")
    calls = []
    def generate(*args):
        # Provider boundary must run with no session transaction held.
        calls.append(args)
        return response("It lost 999 units.") if len(calls) == 1 else response()
    monkeypatch.setattr(openai_provider, "generate", generate)
    aid = analysis_id()
    result = ai_runs.run_ai(aid, "user", "repair", "question", "What is supported?")
    assert result["status"] == "COMPLETED"
    assert len(result["attempts"]) == 2
    assert result["result"]["output"]["claims"][0]["rendered_metrics"]
    assert ai_runs.run_ai(aid, "user", "repair", "question", "What is supported?")["id"] == result["id"]
    assert len(calls) == 2
    with pytest.raises(ServiceError) as conflict:
        ai_runs.run_ai(aid, "user", "repair", "summary", "Changed request")
    assert conflict.value.code == "IDEMPOTENCY_CONFLICT"
    with session_scope() as session:
        usage = usage_view(session)
        assert usage["active_operations"] == 0
        assert usage["committed_inr"] == pytest.approx(cost(2000, 200) * settings.openai_inr_per_usd)


def test_ambiguous_timeout_is_not_retried_and_keeps_maximum(monkeypatch):
    import httpx
    monkeypatch.setattr(settings, "openai_api_key", "mock")
    calls = []
    def timeout(*args):
        calls.append(1)
        raise APITimeoutError(request=httpx.Request("POST", "https://api.openai.com"))
    monkeypatch.setattr(openai_provider, "generate", timeout)
    result = ai_runs.run_ai(analysis_id(), "user", "timeout", "question", "Explain")
    assert result["status"] == "UNCERTAIN"
    assert len(calls) == 1
    with session_scope() as session:
        usage = usage_view(session)
        assert usage["active_operations"] == 0
        assert usage["committed_inr"] == pytest.approx(cost(16000, 3000) * settings.openai_inr_per_usd)


def test_atomic_allowance_and_concurrency_survive_expired_operations():
    def operation(index):
        try:
            with session_scope() as session:
                reserve(session, str(index), "development", "generation", 0.05)
            return True
        except ServiceError:
            return False
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(operation, range(4))) == 2
    with session_scope() as session:
        for entry in session.scalars(select(SpendEntry)):
            entry.expires_at = now() - timedelta(seconds=1)
    with session_scope() as session:
        reserve(session, "new", "development", "generation", 0.05)
        assert usage_view(session)["committed_inr"] == pytest.approx(0.15 * settings.openai_inr_per_usd)
        assert sum(entry.status == "UNCERTAIN" for entry in session.scalars(select(SpendEntry))) == 2
        move_allowance(session, "buffer", "reviewer", 10)
        assert sum(usage_view(session)["allocations_inr"].values()) == 500
        with pytest.raises(ServiceError):
            move_allowance(session, "development", "reviewer", 100)


def test_pinned_corpus_index_and_cached_hybrid_query(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "mock")
    calls = []
    def embeddings(key, model, texts, timeout=55):
        calls.append(texts)
        return {"vectors": [[1.0] + [0.0] * 511 for _ in texts], "request_id": "mock-embedding", "input_tokens": len(texts) * 10, "model": model}
    monkeypatch.setattr(openai_provider, "embed", embeddings)
    corpus_id = "mock-corpus-" + uuid4().hex
    with session_scope() as session:
        publish_corpus(session, corpus_id, now())
    index_corpus(corpus_id, "owner")
    before_query = len(calls)
    first = hybrid_search("material readiness", "user", "query-one", corpus_id, now(), "INC-001")
    assert len(first["results"]) <= 5
    assert all(item["id"] != "INC-001" for item in first["results"])
    assert len(calls) == before_query + 1
    # Search uses frozen cards, even after an ordinary source revision changes.
    with session_scope() as session:
        revision = session.scalar(select(IncidentRevision).where(IncidentRevision.incident_id == "INC-101"))
        original = revision.evidence_card
        revision.evidence_card = "A changed card after corpus publication"
    try:
        again = hybrid_search("material readiness", "user", "query-two", corpus_id, now(), "INC-001")
        assert len(calls) == before_query + 1
        assert again["manifest"]["corpus_digest"] == first["manifest"]["corpus_digest"]
        assert all("changed card" not in item["content"] for item in again["results"])
    finally:
        with session_scope() as session:
            revision = session.scalar(select(IncidentRevision).where(IncidentRevision.incident_id == "INC-101"))
            revision.evidence_card = original
    assert embedding_identity("a  b") == embedding_identity("a b")


def test_category_ceiling_rejects_reservation_before_provider_call():
    with session_scope() as session:
        reserve(session, "user", "development", "generation", 1.0)
    with pytest.raises(ServiceError) as failure, session_scope() as session:
        reserve(session, "user", "development", "generation", 0.2)
    assert failure.value.code == "ALLOWANCE_EXHAUSTED"
    with session_scope() as session:
        assert usage_view(session)["committed_inr"] == settings.openai_inr_per_usd


def test_sdk_parse_failure_keeps_reservation_and_run_is_private(monkeypatch):
    from pydantic import BaseModel
    monkeypatch.setattr(settings, "openai_api_key", "mock")
    class Parsed(BaseModel):
        required_field: str
    def fail(*args):
        Parsed.model_validate({})
    monkeypatch.setattr(openai_provider, "generate", fail)
    result = ai_runs.run_ai(analysis_id(), "user", "parse-failure", "question", "Explain")
    assert result["status"] == "UNCERTAIN"
    assert len(result["attempts"]) == 1
    with pytest.raises(ServiceError) as denied:
        ai_runs.lookup_run(result["id"], "other-user")
    assert denied.value.http_status == 404
    assert ai_runs.lookup_run(result["id"], "owner", owner=True)["id"] == result["id"]
    with session_scope() as session:
        assert usage_view(session)["committed_inr"] > 0


def test_generation_uses_official_sdk_structured_response_store_false(monkeypatch):
    from types import SimpleNamespace
    observed = {}
    class FakeResponses:
        async def parse(self, **kwargs):
            observed.update(kwargs)
            return SimpleNamespace(output_parsed=None, id="response", _request_id="request", model=kwargs["model"], status="completed", usage=SimpleNamespace(input_tokens=10, output_tokens=2))
    def sdk(**kwargs):
        observed["sdk"] = kwargs
        return AsyncClient(responses=FakeResponses())
    monkeypatch.setattr(openai_provider, "AsyncOpenAI", sdk)
    config = openai_provider.configuration(settings.openai_generation_model, settings.openai_embedding_model, 512)
    result = openai_provider.generate("mock", config, "question", "Pinned packet", 7)
    assert observed["store"] is False
    assert observed["instructions"] == openai_provider.SYSTEM
    assert "Always return source_fields=[]" in observed["instructions"]
    assert observed["sdk"]["max_retries"] == 0
    assert observed["sdk"]["timeout"] == 7
    assert observed["max_output_tokens"] == 1500
    assert result["request_id"] == "request"


def test_embedding_response_duplicate_indices_fail_closed(monkeypatch):
    from types import SimpleNamespace
    async def create(**kwargs):
        return SimpleNamespace(data=[SimpleNamespace(index=0, embedding=[0.0] * 512), SimpleNamespace(index=0, embedding=[0.0] * 512)], usage=SimpleNamespace(total_tokens=2), model="text-embedding-3-small", _request_id="mock")
    monkeypatch.setattr(openai_provider, "AsyncOpenAI", lambda **kwargs: AsyncClient(embeddings=SimpleNamespace(create=create)))
    with pytest.raises(ValueError, match="index coverage"):
        openai_provider.embed("mock", "text-embedding-3-small", ["one", "two"])


def test_hybrid_deadline_and_generation_configuration_are_pinned(monkeypatch):
    from flooreplay import retrieval
    monkeypatch.setattr(settings, "openai_api_key", "key-before-retrieval")
    clock = [100.0]
    monkeypatch.setattr(ai_runs.time, "monotonic", lambda: clock[0])
    expected_model = settings.openai_generation_model
    def search(*args, **kwargs):
        assert kwargs["timeout"] <= 60
        clock[0] += 25
        monkeypatch.setattr(settings, "openai_generation_model", "changed-after-reservation")
        monkeypatch.setattr(settings, "openai_api_key", "key-after-retrieval")
        return {"results": [{"excerpts": [{"id": "historical-excerpt", "text": "Prior material concern."}]}], "manifest": {"corpus_id": "pinned", "corpus_digest": "digest"}}
    def generate(key, config, task, text, timeout):
        assert key == "key-before-retrieval"
        assert config["generation_model"] == expected_model
        assert timeout <= 35
        return response()
    monkeypatch.setattr(retrieval, "hybrid_search", search)
    monkeypatch.setattr(openai_provider, "generate", generate)
    result = ai_runs.run_ai(analysis_id(), "user", "deadline", "question", "Explain", retrieval_mode="hybrid", corpus_id="pinned")
    assert result["status"] == "COMPLETED"
    assert result["packet"]["retrieval_manifest"]["corpus_digest"] == "digest"
    assert result["configuration"]["generation_model"] == expected_model


def test_provider_deadline_cancels_request_and_closes_client(monkeypatch):
    import asyncio
    closed = []
    class Slow(AsyncClient):
        async def __aexit__(self, *args):
            closed.append(True)
    class Responses:
        async def parse(self, **kwargs):
            await asyncio.sleep(10)
    monkeypatch.setattr(openai_provider, "AsyncOpenAI", lambda **kwargs: Slow(responses=Responses()))
    config = openai_provider.configuration(settings.openai_generation_model, settings.openai_embedding_model, 512)
    with pytest.raises(TimeoutError):
        openai_provider.generate("mock", config, "question", "Packet", 0.01)
    assert closed == [True]
