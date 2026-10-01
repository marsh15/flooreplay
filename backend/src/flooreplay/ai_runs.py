"""Durable idempotent bounded execution, with provider calls outside transactions."""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from openai import (
    APIConnectionError,
    APIResponseValidationError,
    APIStatusError,
    APITimeoutError,
    ContentFilterFinishReasonError,
    LengthFinishReasonError,
)
from pydantic import ValidationError
from sqlalchemy import select

from . import openai_provider
from .config import settings
from .db import session_scope
from .domain.hashing import digest
from .incident_ai import TASK_SCHEMAS, validate_output
from .incident_jobs import _packet
from .models import IncidentAnalysis
from .paid_models import AIRun, CorpusRelease, EmbeddingArtifact, SpendEntry, now
from .service import ServiceError
from .spending import cost, lock, reserve, settle, usage_view


def view(run: AIRun) -> dict[str, Any]:
    return {"output_digest": digest(run.result["output"]) if run.status == "COMPLETED" and run.result and run.result.get("output") else None, "id": run.id, "request_key": run.request_key, "analysis_id": run.analysis_id, "task": run.task, "status": run.status, "provider": "openai", "configuration": run.configuration, "packet": run.packet, "attempts": run.attempts, "result": run.result, "created_at": run.created_at.isoformat(), "completed_at": run.completed_at.isoformat() if run.completed_at else None}


def lookup_run(run_id: str, user_id: str, owner: bool = False) -> dict[str, Any]:
    with session_scope() as session:
        run = session.get(AIRun, run_id)
        if run is None or (run.user_id != user_id and not owner):
            raise ServiceError("NOT_FOUND", "AI run not found", 404)
        entry = session.get(SpendEntry, run.reservation_id)
        if run.status == "RUNNING" and entry and entry.expires_at < now():
            run.status = "UNCERTAIN"
            run.completed_at = now()
            run.result = {"errors": ["Execution interrupted; reservation retained because provider billing is uncertain"]}
            settle(session, entry.id, 0, run.result, uncertain=True)
        from .ai_evaluation import AIClaimReview, claim_review_view
        reviews = session.scalars(
            select(AIClaimReview).where(AIClaimReview.run_id == run.id)
            .order_by(AIClaimReview.created_at, AIClaimReview.id)
        ).all()
        return {**view(run), "claim_reviews": [claim_review_view(review) for review in reviews]}


def lookup_request(key: str, user_id: str) -> dict[str, Any]:
    with session_scope() as session:
        run = session.scalar(select(AIRun).where(AIRun.user_id == user_id, AIRun.request_key == key))
        if run is None:
            raise ServiceError("NOT_FOUND", "AI request not found", 404)
        run_id = run.id
    return lookup_run(run_id, user_id)


def capabilities(user_id: str) -> dict[str, Any]:
    from .ai_evaluation import provider_evaluation
    with session_scope() as session:
        usage = usage_view(session)
        evaluation = provider_evaluation(session)
        from .retrieval import embedding_identity
        corpora = session.scalars(select(CorpusRelease)).all()
        indexed = [corpus.id for corpus in corpora if corpus.cards and all(session.get(EmbeddingArtifact, embedding_identity(card["content"], settings.openai_embedding_model)[0]) is not None for card in corpus.cards)]
    reasons = []
    if not user_id:
        reasons.append("NOT_SIGNED_IN")
    if not settings.openai_api_key:
        reasons.append("MISSING_API_CONFIGURATION")
    try:
        openai_provider.configuration(settings.openai_generation_model, settings.openai_embedding_model, settings.openai_embedding_dimensions)
    except ValueError:
        reasons.append("MODEL_CONFIGURATION_UNEVALUATED")
    if usage["active_operations"] >= 2:
        reasons.append("EXECUTION_CAPACITY_FULL")
    if min(usage["available_inr"], usage["purpose_available_inr"]["reviewer"]) < cost(16000, 3000) * settings.openai_inr_per_usd:
        reasons.append("ALLOWANCE_EXHAUSTED")
    return {"provider": "openai", "model": settings.openai_generation_model, "ready": not reasons, "reasons": reasons, "evaluation_status": evaluation["status"], "requires_human_review": True, "index_ready": bool(indexed), "indexed_corpus_ids": indexed, "hybrid_reasons": [] if indexed else ["CORPUS_NOT_INDEXED"]}


def run_ai(analysis_id: str, user_id: str, request_key: str, task: str, question: str, purpose: str = "development", retrieval_mode: str = "evidence_only", corpus_id: str | None = None) -> dict[str, Any]:
    started = time.monotonic()
    key = settings.openai_api_key
    if task not in TASK_SCHEMAS or not question.strip() or len(question) > 1000 or not request_key or len(request_key) > 120:
        raise ServiceError("INVALID_AI_REQUEST", "Invalid task, question or request identity", 422)
    if retrieval_mode not in {"evidence_only", "lexical", "hybrid"} or (retrieval_mode in {"lexical", "hybrid"} and not corpus_id):
        raise ServiceError("RETRIEVAL_MANIFEST_REQUIRED", "Historical generation requires an explicit published corpus", 422)
    identity = hashlib.sha256(json.dumps([analysis_id, task, question, retrieval_mode, corpus_id]).encode()).hexdigest()
    # Recover retrieval by its request identity before reserving generation.
    try:
        config = openai_provider.configuration(settings.openai_generation_model, settings.openai_embedding_model, settings.openai_embedding_dimensions)
    except ValueError:
        raise ServiceError("MODEL_CONFIGURATION_UNEVALUATED", "Model configuration requires a versioned price table and evaluation", 503) from None
    pinned_retrieval = None
    if retrieval_mode in {"lexical", "hybrid"}:
        with session_scope() as session:
            existing = session.scalar(select(AIRun).where(AIRun.user_id == user_id, AIRun.request_key == request_key))
            if existing:
                if existing.identity != identity:
                    raise ServiceError("IDEMPOTENCY_CONFLICT", "Request identity already used", 409)
                return view(existing)
            pinned_analysis = session.get(IncidentAnalysis, analysis_id)
            if pinned_analysis is None:
                raise ServiceError("NOT_FOUND", "Analysis not found", 404)
            pinned_cutoff = pinned_analysis.report.get("cutoff")
            incident_id = pinned_analysis.incident_id
        from datetime import datetime

        from .retrieval import hybrid_search, lexical_search
        if not isinstance(pinned_cutoff, str):
            raise ServiceError("INVALID_ANALYSIS", "Analysis cutoff is missing", 422)
        assert corpus_id is not None
        search = lexical_search if retrieval_mode == "lexical" else hybrid_search
        pinned_retrieval = search(question, user_id, "retrieval-" + hashlib.sha256(request_key.encode()).hexdigest(), corpus_id, datetime.fromisoformat(pinned_cutoff), incident_id, timeout=max(0.1, 60 - (time.monotonic() - started)))
    with session_scope() as session:
        lock(session)
        existing = session.scalar(select(AIRun).where(AIRun.user_id == user_id, AIRun.request_key == request_key))
        if existing:
            if existing.identity != identity:
                raise ServiceError("IDEMPOTENCY_CONFLICT", "Request identity already used for another operation", 409)
            return view(existing)
        analysis = session.get(IncidentAnalysis, analysis_id)
        if analysis is None:
            raise ServiceError("NOT_FOUND", "Analysis not found", 404)
        if not key:
            raise ServiceError("MISSING_API_CONFIGURATION", "Configure the backend OpenAI key to enable generation", 503)
        packet = _packet(analysis)
        if pinned_retrieval is not None:
            packet["retrieval_manifest"] = pinned_retrieval["manifest"]
            packet["historical_evidence"] = [excerpt for item in pinned_retrieval["results"] for excerpt in item["excerpts"]]
        text = openai_provider.prompt(packet, question)
        reservation = reserve(session, user_id, purpose, "generation", cost(16000, 3000))
        run = AIRun(user_id=user_id, request_key=request_key, analysis_id=analysis_id, identity=identity, task=task, question=question, status="RUNNING", packet=packet, configuration=config, reservation_id=reservation.id)
        session.add(run)
        session.flush()
        run_id, entry_id = run.id, reservation.id
    # api_key is captured once; execution config has already been persisted.
    attempts: list[dict[str, Any]] = []
    total_usd = 0.0
    terminal = "INVALID"
    final: dict[str, Any] = {}
    uncertain = False
    repair: list[str] | None = None
    for _ in range(2):
        remaining = 60 - (time.monotonic() - started)
        if remaining <= 0:
            break
        try:
            text = openai_provider.prompt(packet, question, repair)
            response = openai_provider.generate(key, config, task, text, remaining)
            attempts.append(response)
            total_usd += cost(response["usage"]["input_tokens"], response["usage"]["output_tokens"])
            if response["status"] != "completed":
                terminal, final = "INCOMPLETE", {"errors": ["Provider response incomplete"]}
                break
            if response["output"] is None:
                terminal, final = "REFUSED", {"errors": ["Provider declined to return a structured draft"]}
                break
            check = validate_output(task, response["output"], packet)
            final = {"output": check["output"], "validation": {"valid": check["valid"], "errors": check["errors"]}, "requires_human_review": True}
            if check["valid"]:
                terminal = "COMPLETED"
                break
            repair = check["errors"]
        except (TimeoutError, APITimeoutError, APIConnectionError, APIResponseValidationError, ContentFilterFinishReasonError, LengthFinishReasonError, ValidationError):
            terminal, uncertain = "UNCERTAIN", True
            final = {"errors": ["Provider connection interrupted; retained reservation, no automatic retry"]}
            attempts.append({"status": terminal})
            break
        except APIStatusError as exc:
            terminal = "UNAVAILABLE"
            final = {"errors": ["MODEL_ACCESS_UNAVAILABLE" if exc.status_code in {401, 403, 404} else "PROVIDER_TEMPORARILY_UNAVAILABLE"], "provider_status": exc.status_code}
            attempts.append({"status": terminal, "request_id": exc.request_id})
            break
        except (ValueError, TypeError):
            terminal, final = "INVALID", {"errors": ["Provider output or packet failed the bounded contract"]}
            break
    with session_scope() as session:
        final_run = session.get(AIRun, run_id)
        assert final_run is not None
        final["elapsed_seconds"] = round(time.monotonic() - started, 6)
        final_run.status, final_run.attempts, final_run.result, final_run.completed_at = terminal, attempts, final, now()
        settle(session, entry_id, total_usd, {"attempts": attempts, "run_id": run_id}, uncertain=uncertain)
        return view(final_run)
