"""Immutable cutoff-visible corpus and exact cosine plus lexical reciprocal ranks."""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime
from math import isfinite
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


def publish_corpus(session: Session, corpus_id: str, cutoff: datetime, *, workspace_id: str = "public-demo") -> dict[str, Any]:
    existing = session.get(CorpusRelease, corpus_id)
    if existing:
        if existing.cutoff != cutoff or existing.workspace_id != workspace_id:
            raise ServiceError("CORPUS_IMMUTABLE", "Corpus release already exists at another cutoff", 409)
        return {"id": existing.id, "digest": existing.digest, "cards": len(existing.cards)}
    revisions = session.scalars(select(IncidentRevision).where(IncidentRevision.cutoff <= cutoff, IncidentRevision.workspace_id == workspace_id).order_by(IncidentRevision.incident_id, IncidentRevision.revision.desc())).all()
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
    session.add(CorpusRelease(id=corpus_id, workspace_id=workspace_id, cutoff=cutoff, digest=digest, cards=cards))
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
        cards, current = _eligible_cards(session, corpus, cutoff, exclude_id)
        corpus_digest = corpus.digest
        artifact_ids = {card["id"]: embedding_identity(card["content"], settings.openai_embedding_model)[0] for card in cards}
        for identity in artifact_ids.values():
            if session.get(EmbeddingArtifact, identity) is None:
                raise ServiceError("CORPUS_NOT_INDEXED", "Owner must explicitly index this pinned corpus", 409)
    if not cards:
        return {"request_key": request_key, "results": [], "status": "NO_USEFUL_PRECEDENT", "manifest": {"mode": "hybrid", "corpus_id": corpus_id, "corpus_digest": corpus_digest, "cutoff": cutoff.isoformat(), "query_embedding_id": None, "card_schema_version": PREPROCESSING, "excluded_incident": exclude_id, "created_at": now().isoformat()}}
    query_id = _embed_texts([query], user_id, "reviewer", max(0.1, timeout - (time.monotonic() - started)))[0]
    with session_scope() as session:
        query_artifact = session.get(EmbeddingArtifact, query_id)
        assert query_artifact is not None
        distance = EmbeddingArtifact.vector.cosine_distance(query_artifact.vector)
        vector_rows = session.execute(select(EmbeddingArtifact.id, distance.label("distance")).where(EmbeddingArtifact.id.in_(artifact_ids.values())).order_by(distance, EmbeddingArtifact.id).limit(20)).all()
        vector_distances = {identity: float(value) for identity, value in vector_rows if isfinite(float(value))}
        vector_rank = {identity: rank + 1 for rank, (identity, _) in enumerate(vector_rows) if identity in vector_distances and vector_distances[identity] <= 0.35}
        lexical_scores = [(float(session.scalar(select(func.ts_rank_cd(func.to_tsvector("english", card["content"]), func.websearch_to_tsquery("english", query)))) or 0), card) for card in cards]
    lexical = [card for score, card in sorted(lexical_scores, key=lambda item: (-item[0], item[1]["id"])) if score > 0][:20]
    lexical_rank = {card["id"]: rank + 1 for rank, card in enumerate(lexical)}
    results = []
    for card in cards:
        lr, vr = lexical_rank.get(card["id"]), vector_rank.get(artifact_ids[card["id"]])
        if lr is None and vr is None:
            continue
        score = (1 / (60 + lr) if lr else 0) + (1 / (60 + vr) if vr else 0)
        results.append({**card, "score": score, "match_reason": "Lexical and semantic candidate" if lr and vr else "Semantic candidate" if vr else "Lexical candidate", "lexical_rank": lr, "vector_rank": vr, "cosine_distance": vector_distances.get(artifact_ids[card["id"]])})
    results.sort(key=lambda item: (-item["score"], item["id"]))
    with session_scope() as session:
        results = [_candidate_view(session, item, current, corpus_id) for item in results[:5]]
    return {"request_key": request_key, "results": results[:5], "status": "CANDIDATES_FOUND" if results else "NO_USEFUL_PRECEDENT", "manifest": {"mode": "hybrid", "semantic_max_cosine_distance": 0.35, "similarity_gate_is_semantic_validation": False, "corpus_id": corpus_id, "corpus_digest": corpus_digest, "cutoff": cutoff.isoformat(), "query_embedding_id": query_id, "model": settings.openai_embedding_model, "dimensions": 512, "card_schema_version": PREPROCESSING, "fusion_constant": 60, "lexical_candidates": 20, "vector_candidates": 20, "excluded_incident": exclude_id, "created_at": now().isoformat()}}


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
        corpus = session.get(CorpusRelease, corpus_id)
        if corpus is None:
            raise ServiceError("NOT_FOUND", "Corpus release not found", 404)
        run = RetrievalRun(workspace_id=corpus.workspace_id, user_id=user_id, request_key=request_key, identity=identity, status="RUNNING")
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


def precedent_comparison(current: dict[str, Any] | None, historical: dict[str, Any]) -> dict[str, Any]:
    """Compare available observations; draft actions never become interventions/outcomes."""
    from .incident_engine import analyze_incident

    facts: list[str] = []
    differences: list[str] = ["Historical observations do not establish the current cause or predict recovery."]
    missing: list[str] = []
    old_report = analyze_incident(historical)
    current_report = analyze_incident(current) if current is not None else None
    old_scope = historical.get("scope", {})
    new_scope = current.get("scope", {}) if current is not None else {}
    for field in ("stage", "unit", "factory", "line_id", "order_id", "style_id"):
        old, new = old_scope.get(field), new_scope.get(field)
        label = field.replace("_", " ")
        if old is None or new is None:
            missing.append(f"Comparable {label} is unavailable.")
        elif old == new:
            facts.append(f"Same {label}: {old}.")
        else:
            differences.append(f"Different {label}: historical {old}; current {new}.")
    blocks = sorted(h["category"] for h in old_report["hypotheses"] if h["status"] == "SUPPORTED")
    current_blocks = sorted(h["category"] for h in current_report["hypotheses"] if h["status"] == "SUPPORTED") if current_report else []
    shared = sorted(set(blocks) & set(current_blocks))
    if shared:
        facts.append("Shared established line-block categories: " + ", ".join(shared) + ". Their causal output contribution remains unknown.")
    if blocks != current_blocks:
        differences.append(f"Established block categories differ: historical {', '.join(blocks) or 'none established'}; current {', '.join(current_blocks) or 'none established'}.")
    missing.extend(["Confirmed causal mechanisms are not established by these reports.", "Actions actually taken and source-confirmed interventions are unavailable in the pinned evidence.", "Post-intervention outcomes and causal recovery effects have not been recorded in the pinned evidence."])
    for label, report in (("Historical", old_report), ("Current", current_report)):
        if report is None:
            continue
        metric = report["metrics"]
        if metric["observed"] is not None:
            facts.append(f"{label} recorded good output: {metric['observed']} {metric['unit']}; shortfall {metric['shortfall']}. This is an observed window total, not an intervention outcome.")
        else:
            missing.append(f"{label} complete production comparison is unavailable ({metric['status']}).")
    old_prerequisites = sorted({condition for proposal in old_report["proposals"] for condition in proposal.get("preconditions", [])})
    current_prerequisites = sorted({condition for proposal in current_report["proposals"] for condition in proposal.get("preconditions", [])}) if current_report else []
    missing.append("Proposal prerequisites require separate current-source verification; shared wording does not prove they are satisfied.")
    return {"comparison_version": "observed-precedent-v1", "comparison_facts": facts, "differences": differences, "missing_information": missing, "historical_prerequisites": old_prerequisites, "current_prerequisites": current_prerequisites}


def _eligible_cards(session: Session, corpus: CorpusRelease, cutoff: datetime, exclude_id: str | None) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
        raise ServiceError("INVALID_CUTOFF", "Historical retrieval requires a timezone-aware cutoff", 422)
    current = session.scalar(select(IncidentRevision).where(IncidentRevision.incident_id == exclude_id, IncidentRevision.cutoff <= cutoff).order_by(IncidentRevision.revision.desc()).limit(1)) if exclude_id else None
    excluded_lineages = {str(item.payload.get("lineage_id", exclude_id)) for item in session.scalars(select(IncidentRevision).where(IncidentRevision.incident_id == exclude_id))} if exclude_id else set()
    cards = []
    for card in corpus.cards:
        if datetime.fromisoformat(card["cutoff"]) > cutoff or card["id"] == exclude_id or card["lineage_id"] in excluded_lineages:
            continue
        source = session.get(IncidentRevision, (card["id"], card["revision"]))
        if source is None or source.workspace_id != corpus.workspace_id or source.content_digest != card.get("source_digest"):
            continue
        if source.payload.get("dataset_split", "historical") != "historical":
            continue
        if source is not None and current is not None and source.payload["scope"].get("stage") != current.payload["scope"].get("stage"):
            continue
        cards.append(card)
    return cards, current.payload if current is not None else None


def _candidate_view(session: Session, card: dict[str, Any], current: dict[str, Any] | None, corpus_id: str) -> dict[str, Any]:
    source = session.get(IncidentRevision, (card["id"], card["revision"]))
    comparison = precedent_comparison(current, source.payload) if source is not None and source.content_digest == card.get("source_digest") else {"comparison_facts": [], "differences": ["Historical context does not establish the current cause."], "missing_information": ["Pinned source metadata is unavailable; only the frozen excerpt can be inspected."]}
    return {**card, **comparison, "excerpts": [{"id": f"{corpus_id}:{card['id']}@{card['revision']}", "text": card["content"]}]}


def lexical_search(query: str, user_id: str, request_key: str, corpus_id: str, cutoff: datetime, exclude_id: str | None = None, timeout: float = 60) -> dict[str, Any]:
    """Pinned local full-text retrieval. Never reserve spend or construct embeddings."""
    if not query.strip() or len(query) > 1000 or not request_key or len(request_key) > 120:
        raise ServiceError("INVALID_QUERY", "Query and request identity must be bounded", 422)
    started = time.monotonic()
    identity = hashlib.sha256(json.dumps(["lexical-v1", query, corpus_id, cutoff.isoformat(), exclude_id]).encode()).hexdigest()
    with session_scope() as session:
        lock(session)
        existing = session.scalar(select(RetrievalRun).where(RetrievalRun.user_id == user_id, RetrievalRun.request_key == request_key))
        if existing:
            if existing.identity != identity:
                raise ServiceError("IDEMPOTENCY_CONFLICT", "Search identity already used", 409)
            if existing.status != "COMPLETED" or existing.result is None:
                raise ServiceError("RETRIEVAL_PENDING", "Search has no completed result", 409)
            return existing.result
        corpus = session.get(CorpusRelease, corpus_id)
        if corpus is None:
            raise ServiceError("NOT_FOUND", "Corpus release not found", 404)
        cards, current = _eligible_cards(session, corpus, cutoff, exclude_id)
        ranked = []
        for card in cards:
            if time.monotonic() - started >= timeout:
                raise ServiceError("RETRIEVAL_TIMEOUT", "Local retrieval exceeded its bounded execution time", 503)
            score = float(session.scalar(select(func.ts_rank_cd(func.to_tsvector("english", card["content"]), func.websearch_to_tsquery("english", query)))) or 0)
            ranked.append((score, card))
        matched = [(score, card) for score, card in sorted(ranked, key=lambda item: (-item[0], item[1]["id"])) if score > 0][:5]
        results = [{**_candidate_view(session, card, current, corpus_id), "score": score, "match_reason": "Lexical candidate from pinned cutoff-visible observations", "lexical_rank": rank + 1, "vector_rank": None} for rank, (score, card) in enumerate(matched)]
        result = {"request_key": request_key, "results": results, "status": "CANDIDATES_FOUND" if results else "NO_USEFUL_PRECEDENT", "manifest": {"mode": "lexical", "corpus_id": corpus_id, "corpus_digest": corpus.digest, "cutoff": cutoff.isoformat(), "card_schema_version": PREPROCESSING, "query_embedding_id": None, "excluded_incident": exclude_id, "created_at": now().isoformat()}}
        session.add(RetrievalRun(workspace_id=corpus.workspace_id, user_id=user_id, request_key=request_key, identity=identity, status="COMPLETED", result=result))
        session.flush()
        return result
