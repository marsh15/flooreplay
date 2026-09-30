"""Immutable cutoff-visible corpus and exact cosine plus lexical reciprocal ranks."""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime
from typing import Any

import tiktoken
from openai import APIConnectionError, APIStatusError, APITimeoutError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import openai_provider
from .config import settings
from .db import session_scope
from .models import IncidentRevision
from .paid_models import CorpusRelease, EmbeddingArtifact, RetrievalRun, SpendEntry, now
from .service import ServiceError
from .spending import cost, lock, reserve, settle

PREPROCESSING = "evidence-card-v2"


def embedding_identity(text: str, model: str = "text-embedding-3-small") -> tuple[str, str]:
    normalized = " ".join(text.split())
    digest = hashlib.sha256(json.dumps([normalized, model, 512, PREPROCESSING]).encode()).hexdigest()
    return digest, normalized


def publish_corpus(session: Session, corpus_id: str, cutoff: datetime) -> dict[str, Any]:
    existing = session.get(CorpusRelease, corpus_id)
    if existing:
        if existing.cutoff != cutoff:
            raise ServiceError("CORPUS_IMMUTABLE", "Corpus release already exists at another cutoff", 409)
        return {"id": existing.id, "digest": existing.digest, "cards": len(existing.cards)}
    revisions = session.scalars(select(IncidentRevision).where(IncidentRevision.cutoff <= cutoff).order_by(IncidentRevision.incident_id, IncidentRevision.revision.desc())).all()
    cards: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in revisions:
        if item.payload.get("dataset_split", "historical") != "historical":
            continue
        lineage = str(item.payload.get("lineage_id", item.incident_id))
        if lineage in seen:
            continue
        seen.add(lineage)
        # Card is already constructed from cutoff-visible observations by incident_service.
        cards.append({"id": item.incident_id, "revision": item.revision, "lineage_id": lineage, "title": item.title, "cutoff": item.cutoff.isoformat(), "content": item.evidence_card, "content_digest": hashlib.sha256(item.evidence_card.encode()).hexdigest(), "source_digest": item.content_digest, "card_schema_version": PREPROCESSING, "embedding_identity": embedding_identity(item.evidence_card, settings.openai_embedding_model)[0], "embedding_model": settings.openai_embedding_model, "embedding_dimensions": 512})
    digest = hashlib.sha256(json.dumps(cards, sort_keys=True).encode()).hexdigest()
    session.add(CorpusRelease(id=corpus_id, cutoff=cutoff, digest=digest, cards=cards))
    return {"id": corpus_id, "digest": digest, "cards": len(cards)}


def _embed_texts(texts: list[str], user_id: str, purpose: str, timeout: float = 55) -> list[str]:
    started = time.monotonic()
    model = settings.openai_embedding_model
    api_key = settings.openai_api_key
    openai_provider.configuration(settings.openai_generation_model, model, settings.openai_embedding_dimensions)
    identities = [embedding_identity(text, model) for text in texts]
    with session_scope() as session:
        lock(session)
        missing = {digest: text for digest, text in identities if session.get(EmbeddingArtifact, digest) is None}
        if not missing:
            return [digest for digest, _ in identities]
        if not settings.openai_api_key:
            raise ServiceError("MISSING_API_CONFIGURATION", "OpenAI key required to construct embeddings", 503)
        tokens = sum(len(tiktoken.get_encoding("cl100k_base").encode(text)) for text in missing.values())
        if tokens > 16000 or len(missing) > 16:
            raise ServiceError("EMBEDDING_LIMIT", "Embedding batch exceeds bounded input", 422)
        # Block duplicate in-flight embeddings across concurrent requests.
        pending_ids = set(missing)
        for pending in session.scalars(select(SpendEntry).where(SpendEntry.status.in_(["RESERVED", "UNCERTAIN"]))):
            if pending_ids.intersection(pending.details.get("embedding_ids", [])):
                raise ServiceError("EMBEDDING_IN_PROGRESS", "Embedding identity is reserved or uncertain; inspect usage before retrying", 409)
        reservation = reserve(session, user_id, purpose, "embedding", cost(tokens, embedding=True))
        reservation.details = {"embedding_ids": list(missing)}
        entry_id = reservation.id
    try:
        response = openai_provider.embed(api_key, model, list(missing.values()), max(0.1, timeout - (time.monotonic() - started)))
    except (TimeoutError, APITimeoutError, APIConnectionError):
        with session_scope() as session:
            settle(session, entry_id, 0, {"embedding_ids": list(missing), "reason": "Ambiguous provider connection failure"}, uncertain=True)
        raise ServiceError("PROVIDER_UNCERTAIN", "Embedding request interrupted; reservation retained", 503) from None
    except ValueError:
        with session_scope() as session:
            settle(session, entry_id, 0, {"embedding_ids": list(missing), "reason": "Provider embedding parsing failed after possible billing"}, uncertain=True)
        raise ServiceError("PROVIDER_UNCERTAIN", "Embedding response invalid; reservation retained", 503) from None
    except APIStatusError as exc:
        with session_scope() as session:
            settle(session, entry_id, 0, {"request_id": exc.request_id, "provider_status": exc.status_code})
        raise ServiceError("PROVIDER_UNAVAILABLE", "Embedding provider unavailable", 503) from None
    with session_scope() as session:
        lock(session)
        for (digest, content), vector in zip(missing.items(), response["vectors"], strict=True):
            if len(vector) != 512:
                raise ServiceError("INVALID_EMBEDDING", "Provider embedding has unexpected dimensions", 502)
            if session.get(EmbeddingArtifact, digest) is None:
                session.add(EmbeddingArtifact(id=digest, model=model, dimensions=512, preprocessing_version=PREPROCESSING, content=content, vector=vector, provider_usage={"input_tokens": response["input_tokens"], "request_id": response["request_id"], "reservation_id": entry_id}))
        settle(session, entry_id, cost(response["input_tokens"], embedding=True), {"embedding_ids": list(missing), "request_id": response["request_id"]})
    return [digest for digest, _ in identities]


def index_corpus(corpus_id: str, user_id: str, purpose: str = "evaluation") -> dict[str, Any]:
    with session_scope() as session:
        corpus = session.get(CorpusRelease, corpus_id)
        if corpus is None:
            raise ServiceError("NOT_FOUND", "Corpus release not found", 404)
        cards = corpus.cards
    indexed = 0
    for offset in range(0, len(cards), 8):
        _embed_texts([card["content"] for card in cards[offset:offset + 8]], user_id, purpose)
        indexed += len(cards[offset:offset + 8])
    return {"corpus_id": corpus_id, "indexed_cards": indexed, "model": settings.openai_embedding_model, "dimensions": 512}


def _hybrid_search(query: str, user_id: str, request_key: str, corpus_id: str, cutoff: datetime, exclude_id: str | None = None, timeout: float = 60) -> dict[str, Any]:
    started = time.monotonic()
    if not query.strip() or len(query) > 1000 or not request_key or len(request_key) > 120:
        raise ServiceError("INVALID_QUERY", "Query and request identity must be bounded", 422)
    with session_scope() as session:
        corpus = session.get(CorpusRelease, corpus_id)
        if corpus is None:
            raise ServiceError("NOT_FOUND", "Corpus release not found", 404)
        excluded_lineages = {str(item.payload.get("lineage_id", exclude_id)) for item in session.scalars(select(IncidentRevision).where(IncidentRevision.incident_id == exclude_id))} if exclude_id else set()
        cards = [card for card in corpus.cards if datetime.fromisoformat(card["cutoff"]) <= cutoff and card["id"] != exclude_id and card["lineage_id"] not in excluded_lineages]
        corpus_digest = corpus.digest
        artifact_ids = {card["id"]: embedding_identity(card["content"], settings.openai_embedding_model)[0] for card in cards}
        for identity in artifact_ids.values():
            if session.get(EmbeddingArtifact, identity) is None:
                raise ServiceError("CORPUS_NOT_INDEXED", "Owner must explicitly index this pinned corpus", 409)
    query_id = _embed_texts([query], user_id, "reviewer", max(0.1, timeout - (time.monotonic() - started)))[0]
    with session_scope() as session:
        query_artifact = session.get(EmbeddingArtifact, query_id)
        assert query_artifact is not None
        vector_ids = session.scalars(select(EmbeddingArtifact.id).where(EmbeddingArtifact.id.in_(artifact_ids.values())).order_by(EmbeddingArtifact.vector.cosine_distance(query_artifact.vector), EmbeddingArtifact.id).limit(20)).all()
        vector_rank = {identity: rank + 1 for rank, identity in enumerate(vector_ids)}
        lexical_scores = [(float(session.scalar(select(func.ts_rank_cd(func.to_tsvector("english", card["content"]), func.websearch_to_tsquery("english", query)))) or 0), card) for card in cards]
    lexical = [card for score, card in sorted(lexical_scores, key=lambda item: (-item[0], item[1]["id"])) if score > 0][:20]
    lexical_rank = {card["id"]: rank + 1 for rank, card in enumerate(lexical)}
    results = []
    for card in cards:
        lr, vr = lexical_rank.get(card["id"]), vector_rank.get(artifact_ids[card["id"]])
        if lr is None and vr is None:
            continue
        score = (1 / (60 + lr) if lr else 0) + (1 / (60 + vr) if vr else 0)
        results.append({**card, "score": score, "match_reason": "Lexical and semantic candidate" if lr and vr else "Semantic candidate" if vr else "Lexical candidate", "differences": ["Historical evidence is context; it does not establish the current cause"], "excerpts": [{"id": f"{corpus_id}:{card['id']}@{card['revision']}", "text": card["content"]}], "lexical_rank": lr, "vector_rank": vr})
    results.sort(key=lambda item: (-item["score"], item["id"]))
    return {"request_key": request_key, "results": results[:5], "manifest": {"corpus_id": corpus_id, "corpus_digest": corpus_digest, "cutoff": cutoff.isoformat(), "query_embedding_id": query_id, "model": settings.openai_embedding_model, "dimensions": 512, "card_schema_version": PREPROCESSING, "fusion_constant": 60, "lexical_candidates": 20, "vector_candidates": 20, "excluded_incident": exclude_id, "created_at": now().isoformat()}}


def hybrid_search(query: str, user_id: str, request_key: str, corpus_id: str, cutoff: datetime, exclude_id: str | None = None, timeout: float = 60) -> dict[str, Any]:
    identity = hashlib.sha256(json.dumps([query, corpus_id, cutoff.isoformat(), exclude_id]).encode()).hexdigest()
    with session_scope() as session:
        lock(session)
        existing = session.scalar(select(RetrievalRun).where(RetrievalRun.user_id == user_id, RetrievalRun.request_key == request_key))
        if existing:
            if existing.identity != identity:
                raise ServiceError("IDEMPOTENCY_CONFLICT", "Search identity already used", 409)
            if existing.status == "COMPLETED":
                assert existing.result is not None
                return existing.result
            raise ServiceError("RETRIEVAL_PENDING", "Search is pending or interrupted; no automatic paid retry", 409)
        run = RetrievalRun(user_id=user_id, request_key=request_key, identity=identity, status="RUNNING")
        session.add(run)
        session.flush()
        run_id = run.id
    try:
        result = _hybrid_search(query, user_id, request_key, corpus_id, cutoff, exclude_id, timeout)
    except Exception:
        with session_scope() as session:
            failed = session.get(RetrievalRun, run_id)
            assert failed is not None
            failed.status = "FAILED"
        raise
    with session_scope() as session:
        complete = session.get(RetrievalRun, run_id)
        assert complete is not None
        complete.status, complete.result = "COMPLETED", result
    return result
