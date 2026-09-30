"""HTTP surface. Thin: it validates, delegates to the service, and shapes
responses. Domain blocks (NEEDS_CONTEXT and friends) are successful
executions, never HTTP server errors."""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, StrictBool
from sqlalchemy import select, text

from .ai_evaluation import review_claim
from .ai_runs import capabilities as provider_capabilities
from .ai_runs import lookup_request, lookup_run, run_ai
from .auth import (
    Account,
    current_user,
    enforce_access_limit,
    require_owner,
    require_reviewer,
    sign_in,
    sign_out,
    user_view,
)
from .config import settings
from .db import session_scope
from .fixtures import CATALOG, CONFIGURATIONS
from .importing import ImportStructuralError, preview_import
from .incident_evaluation import evaluation_report
from .incident_import import preview_incident_import
from .incident_service import (
    analysis_evidence,
    analysis_view,
    create_analysis,
    create_incident_from_source,
    incident_detail,
    incident_list,
    publish_source,
    review_proposal,
    search_incidents,
)
from .models import (
    ComparisonReport,
    ExecutionConfiguration,
    IncidentAnalysis,
    ParserCall,
    ReplayAttempt,
    ReviewCheck,
    ScenarioRevision,
    SourceSnapshot,
    SuiteRevision,
)
from .parsing import (
    ParserUnavailable,
    get_parser,
    resolve_draft,
)
from .ratelimit import enforce, make_execution_limiter
from .retrieval import hybrid_search
from .service import (
    ServiceError,
    confirm_event_and_fork,
    execute_replay,
    fork_scenario,
    latest_attempt_summaries,
    latest_saved_attempt,
    publish_import,
    recover_interrupted,
    replay_export,
    review_check,
    run_comparison,
)
from .spending import usage_view

logger = logging.getLogger("flooreplay.api")


class ErrorEnvelope(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    trace_id: str


class ReplayRequest(BaseModel):
    scenario_id: str
    scenario_revision: int
    configuration_id: str
    idempotency_key: str = Field(min_length=8, max_length=120)


class ImportRequestBody(BaseModel):
    profile_id: str
    csv_text: str
    declared_evidence_at: str
    coverage_complete: bool = True
    scope: str | None = None


class PublishRequestBody(ImportRequestBody):
    preview_digest: str


class ForkRequest(BaseModel):
    snapshot_id: str


class ComparisonRequest(BaseModel):
    suite_id: str
    baseline_config_id: str
    candidate_config_id: str
    idempotency_key: str = Field(min_length=8, max_length=120)


class NoteParseRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class NoteConfirmRequest(BaseModel):
    scenario_id: str
    scenario_revision: int
    subject_operator_id: str
    observed_at: str
    summary: str = Field(min_length=3, max_length=400)
    source_kind: str = "note"  # note | manual
    parser_call_id: str | None = None
    corrections: dict[str, Any] | None = None


class ReviewCheckRequest(BaseModel):
    original_replay_id: str
    target_scenario_id: str
    target_scenario_revision: int


class IncidentAnalysisRequest(BaseModel):
    revision: int
    idempotency_key: str = Field(min_length=8, max_length=120)


class IncidentReviewRequest(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=120)
    rationale: str = Field(min_length=3, max_length=1000)
    decision: str


class IncidentDraftRequest(BaseModel):
    corpus_id: str | None = None
    task: str = Field(default="question", pattern="^(question|investigation|summary|recovery|note)$")
    retrieval_mode: str = Field(default="evidence_only", pattern="^(evidence_only|hybrid)$")
    question: str = Field(default="Summarize the incident and next checks.", min_length=3, max_length=500)
    idempotency_key: str = Field(min_length=8, max_length=120)


class IncidentImportRequest(BaseModel):
    scope: dict[str, str] | None = None
    incident_id: str = Field(min_length=1, max_length=64)
    base_revision: int = Field(ge=0)
    cutoff: str = Field(min_length=10, max_length=64)
    raw_text: str = Field(min_length=1, max_length=2 * 1024 * 1024)
    profile: str = Field(min_length=1, max_length=32)
    source_system: str = Field(min_length=1, max_length=64)
    timezone: str = Field(min_length=1, max_length=64)
    filename: str = Field(min_length=1, max_length=120)
    unit: str | None = None


class IncidentPublishRequest(IncidentImportRequest):
    preview_digest: str
    idempotency_key: str = Field(min_length=8, max_length=120)


class IncidentCreateRequest(BaseModel):
    incident_id: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=3, max_length=200)
    scope: dict[str, str]
    window: dict[str, str]
    cutoff: str
    raw_text: str = Field(min_length=1, max_length=2 * 1024 * 1024)
    source_system: str = Field(min_length=1, max_length=64)
    timezone: str = Field(min_length=1, max_length=64)
    filename: str = Field(min_length=1, max_length=120)
    preview_digest: str
    idempotency_key: str = Field(min_length=8, max_length=120)


class AIClaimReviewRequest(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=120)
    claim_path: str = Field(min_length=1, max_length=120)
    supported: StrictBool
    rationale: str = Field(min_length=3, max_length=1000)


class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=120)
    password: str = Field(min_length=1, max_length=256)


class HybridRequest(BaseModel):
    query: str = Field(min_length=1, max_length=200)
    corpus_id: str
    cutoff: str
    exclude_id: str | None = None
    idempotency_key: str = Field(min_length=8, max_length=120)


def ai_capabilities(user: Account | None) -> dict[str, Any]:
    from .paid_models import CorpusRelease, EmbeddingArtifact
    from .retrieval import embedding_identity
    try:
        result = provider_capabilities(user.id if user else "")
        with session_scope() as session:
            corpora = session.scalars(select(CorpusRelease)).all()
            index_ready = any(row.cards and all(session.get(EmbeddingArtifact, embedding_identity(card["content"], settings.openai_embedding_model)[0]) is not None for card in row.cards) for row in corpora)
        reasons = result.get("reasons", [])
        return {**result, "generation_available": result["ready"], "reason": reasons[0] if reasons else None, "index_ready": index_ready}
    except Exception:
        return {"provider": "openai", "model": settings.openai_generation_model, "generation_available": False, "reason": "DATABASE_UNAVAILABLE", "index_ready": False, "evaluation_status": "OPENAI_NOT_EVALUATED"}


def create_app(mode: str | None = None) -> FastAPI:
    effective_mode = mode or settings.mode
    limiter = make_execution_limiter()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        # A process that died mid-execution leaves RUNNING rows behind
        # (execute_replay commits the attempt before executing). Mark them
        # INTERRUPTED once at startup; the suite's "interrupted never passes"
        # rule then applies to them everywhere.
        try:
            with session_scope() as session:
                recovered = recover_interrupted(session)
            if recovered:
                logger.warning(
                    "Startup recovery marked %d RUNNING replay attempt(s) INTERRUPTED",
                    recovered,
                )
        except Exception:
            logger.exception(
                "Startup recovery could not reach the database; "
                "/health/ready reports the live database state."
            )
        yield

    app = FastAPI(title="FloorReplay API", version="0.1.0", lifespan=lifespan)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_origins),
            allow_methods=["*"],
            allow_headers=["*"],
        )

    def limit_public_execution(request: Request) -> None:
        if effective_mode == "public":
            enforce(limiter, request)

    @app.exception_handler(ParserUnavailable)
    async def parser_unavailable_handler(request: Request, exc: ParserUnavailable) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content=ErrorEnvelope(
                code="PARSER_UNAVAILABLE",
                message=f"{exc} Manual structured entry remains available.",
                trace_id=str(uuid.uuid4()),
            ).model_dump(),
        )

    @app.exception_handler(ImportStructuralError)
    async def import_error_handler(request: Request, exc: ImportStructuralError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=ErrorEnvelope(
                code=exc.code, message=exc.message, details=exc.details, trace_id=str(uuid.uuid4())
            ).model_dump(),
        )

    @app.exception_handler(ServiceError)
    async def service_error_handler(request: Request, exc: ServiceError) -> JSONResponse:
        headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else None
        return JSONResponse(
            status_code=exc.http_status,
            content=ErrorEnvelope(
                code=exc.code, message=exc.message, trace_id=str(uuid.uuid4())
            ).model_dump(),
            headers=headers,
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content=ErrorEnvelope(
                code="UNAVAILABLE",
                message="The request could not be completed.",
                details={"error": type(exc).__name__},
                trace_id=str(uuid.uuid4()),
            ).model_dump(),
        )

    @app.post("/api/v1/auth/login")
    def login(body: LoginRequest, request: Request) -> dict[str, Any]:
        return sign_in(body.username, body.password, request.client.host if request.client else "unknown")

    @app.get("/api/v1/auth/me")
    def identity(user: Annotated[Account, Depends(require_reviewer)]) -> dict[str, str]:
        return user_view(user)

    @app.post("/api/v1/auth/logout")
    def logout(request: Request, user: Annotated[Account, Depends(require_reviewer)]) -> dict[str, bool]:
        sign_out(request)
        return {"logged_out": True}

    @app.get("/api/v1/capabilities")
    def capabilities(user: Annotated[Account | None, Depends(current_user)]) -> dict[str, Any]:
        return {
            "mode": effective_mode,
            "imports_enabled": bool(user and user.role == "owner"),
            "reviews_enabled": user is not None,
            "export_enabled": user is not None,
            "user": user_view(user) if user else None,
            "ai": ai_capabilities(user),
            "build_id": settings.build_id,
            "live_parser_available": False,
            "parser_kind": "rule-baseline",
            "execution_limits": {
                "replays_per_hour_per_client": (
                    settings.public_replays_per_hour if effective_mode == "public" else None
                ),
                "comparison_execution": "local_only" if effective_mode == "public" else "open",
                "saved_report_fallback": "/api/v1/replays/latest",
            },
            "configurations": [
                {"id": c["id"], "name": c["name"], "known_limitation": c["known_limitation"]}
                for c in CONFIGURATIONS
            ],
        }

    @app.get("/api/v1/health/live")
    def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/v1/health/ready")
    def ready() -> dict[str, str]:
        try:
            with session_scope() as session:
                revision = session.scalar(text("SELECT version_num FROM alembic_version"))
                if revision != "20260930_claim_reviews":
                    raise ServiceError("MIGRATION_REQUIRED", "Database migration must finish before serving traffic", 503)
        except ServiceError:
            raise
        except Exception as exc:  # pragma: no cover - infra failure path
            raise ServiceError("DATABASE_UNAVAILABLE", "Database is unavailable or migrations have not run", 503) from exc
        return {"status": "ready"}

    @app.get("/api/v1/incidents")
    def list_incidents() -> dict[str, Any]:
        with session_scope() as session:
            return {"items": incident_list(session)}

    @app.get("/api/v1/evaluation-reports/incident-release-v1")
    def release_eval_report() -> dict[str, Any]:
        from .ai_evaluation import provider_evaluation
        from .dataset_evaluation import evaluate_dataset
        with session_scope() as session:
            provider = provider_evaluation(session)
        return {**evaluate_dataset(), "provider": "openai", "provider_status": provider["status"], "human_support_precision": None, "independent_semantic_review_status": "PENDING"}

    @app.get("/api/v1/evaluation-reports/incident-core-v1")
    def incident_eval_report() -> dict[str, Any]:
        with session_scope() as session:
            return evaluation_report(session)

    @app.get("/api/v1/incidents/search")
    def incident_search(q: str = "") -> dict[str, Any]:
        with session_scope() as session:
            return {"items": search_incidents(session, q), "execution_kind": "live_lexical"}

    @app.get("/api/v1/incidents/{incident_id}/saved-draft")
    def saved_incident_draft(incident_id: str) -> dict[str, Any]:
        if incident_id != "INC-001":
            raise ServiceError("SAVED_DRAFT_UNKNOWN", "No saved local draft for this incident", 404)
        path = Path(__file__).resolve().parents[2] / "evaluation" / "hero-saved-ai.json"
        if not path.exists():
            raise ServiceError("SAVED_DRAFT_UNKNOWN", "Saved local draft is not installed", 404)
        saved = json.loads(path.read_text())
        if not isinstance(saved, dict):
            raise ServiceError("SAVED_DRAFT_INVALID", "Saved draft artifact is invalid", 503)
        return saved

    @app.get("/api/v1/incidents/{incident_id}/revisions/{revision}")
    def get_incident(incident_id: str, revision: int) -> dict[str, Any]:
        with session_scope() as session:
            return incident_detail(session, incident_id, revision)

    @app.post("/api/v1/incidents/{incident_id}/analyses")
    def run_incident_analysis(incident_id: str, body: IncidentAnalysisRequest, _limits: None = Depends(limit_public_execution)) -> dict[str, Any]:
        with session_scope() as session:
            analysis = create_analysis(session, incident_id, body.revision, body.idempotency_key)
            return analysis_view(session, analysis)

    @app.get("/api/v1/analyses/{analysis_id}")
    def get_incident_analysis(analysis_id: str) -> dict[str, Any]:
        with session_scope() as session:
            analysis = session.get(IncidentAnalysis, analysis_id)
            if analysis is None:
                raise ServiceError("ANALYSIS_UNKNOWN", "Unknown analysis", 404)
            return analysis_view(session, analysis)

    @app.get("/api/v1/analyses/{analysis_id}/evidence/{evidence_id}")
    def get_incident_evidence(analysis_id: str, evidence_id: str) -> dict[str, Any]:
        with session_scope() as session:
            analysis = session.get(IncidentAnalysis, analysis_id)
            if analysis is None:
                raise ServiceError("ANALYSIS_UNKNOWN", "Unknown analysis", 404)
            return analysis_evidence(session, analysis, evidence_id)

    @app.get("/api/v1/analyses/{analysis_id}/export")
    def export_incident_analysis(analysis_id: str, user: Annotated[Account, Depends(require_reviewer)]) -> dict[str, Any]:
        with session_scope() as session:
            analysis = session.get(IncidentAnalysis, analysis_id)
            if analysis is None:
                raise ServiceError("ANALYSIS_UNKNOWN", "Unknown analysis", 404)
            return {"schema": "flooreplay.incident-report.v1", "report": analysis_view(session, analysis)}

    @app.post("/api/v1/incidents")
    def create_incident(body: IncidentCreateRequest, user: Annotated[Account, Depends(require_owner)]) -> dict[str, Any]:
        with session_scope() as session:
            return create_incident_from_source(session, **body.model_dump())

    @app.post("/api/v1/incidents/imports/preview")
    def preview_incident_source(body: IncidentImportRequest, user: Annotated[Account, Depends(require_owner)]) -> dict[str, Any]:
        try:
            return preview_incident_import(body.raw_text.encode("utf-8"), profile=body.profile, source_system=body.source_system, timezone=body.timezone, filename=body.filename, unit=body.unit, scope=body.scope)
        except ValueError as exc:
            raise ServiceError("INVALID_IMPORT", str(exc), 422) from exc

    @app.post("/api/v1/incidents/imports/publish")
    def publish_incident_source(body: IncidentPublishRequest, user: Annotated[Account, Depends(require_owner)]) -> dict[str, Any]:
        with session_scope() as session:
            return publish_source(session, **body.model_dump(exclude={"scope"}))

    @app.post("/api/v1/analyses/{analysis_id}/proposals/{proposal_id}/submit")
    def submit_incident_proposal(analysis_id: str, proposal_id: str, body: IncidentReviewRequest, user: Annotated[Account, Depends(require_reviewer)]) -> dict[str, Any]:
        with session_scope() as session:
            analysis = session.get(IncidentAnalysis, analysis_id)
            if analysis is None:
                raise ServiceError("ANALYSIS_UNKNOWN", "Unknown analysis", 404)
            review = review_proposal(session, analysis, proposal_id, "PENDING_REVIEW", user.id, body.rationale, body.idempotency_key)
            return {"id": review.id, "state": review.state, "analysis_id": review.analysis_id, "proposal_id": review.proposal_id}

    @app.post("/api/v1/analyses/{analysis_id}/proposals/{proposal_id}/review")
    def decide_incident_proposal(analysis_id: str, proposal_id: str, body: IncidentReviewRequest, user: Annotated[Account, Depends(require_reviewer)]) -> dict[str, Any]:
        if body.decision not in ("APPROVED", "REJECTED"):
            raise ServiceError("REVIEW_DECISION", "Decision must be APPROVED or REJECTED", 422)
        with session_scope() as session:
            analysis = session.get(IncidentAnalysis, analysis_id)
            if analysis is None:
                raise ServiceError("ANALYSIS_UNKNOWN", "Unknown analysis", 404)
            review = review_proposal(session, analysis, proposal_id, body.decision, user.id, body.rationale, body.idempotency_key)
            return {"id": review.id, "state": review.state, "analysis_id": review.analysis_id, "proposal_id": review.proposal_id}

    @app.post("/api/v1/analyses/{analysis_id}/ai-runs")
    def create_ai_run(analysis_id: str, body: IncidentDraftRequest, user: Annotated[Account, Depends(require_reviewer)]) -> dict[str, Any]:
        enforce_access_limit("paid:" + user.id, 30, 3600)
        return run_ai(analysis_id, user.id, body.idempotency_key, body.task, body.question, purpose="reviewer", retrieval_mode=body.retrieval_mode, corpus_id=body.corpus_id)

    @app.get("/api/v1/ai-runs/by-request/{request_key}")
    def get_ai_request(request_key: str, user: Annotated[Account, Depends(require_reviewer)]) -> dict[str, Any]:
        return lookup_request(request_key, user.id)

    @app.get("/api/v1/ai-runs/{run_id}")
    def get_ai_run(run_id: str, user: Annotated[Account, Depends(require_reviewer)]) -> dict[str, Any]:
        return lookup_run(run_id, user.id, owner=user.role == "owner")

    @app.post("/api/v1/ai-runs/{run_id}/claim-review")
    def annotate_ai_claim(run_id: str, body: AIClaimReviewRequest, user: Annotated[Account, Depends(require_reviewer)]) -> dict[str, Any]:
        return review_claim(run_id, user.id, body.idempotency_key, body.claim_path, body.supported, body.rationale, owner=user.role == "owner")

    @app.get("/api/v1/usage")
    def get_usage(user: Annotated[Account, Depends(require_owner)]) -> dict[str, Any]:
        with session_scope() as session:
            return usage_view(session)

    @app.get("/api/v1/corpora")
    def corpora() -> dict[str, Any]:
        from .paid_models import CorpusRelease
        with session_scope() as session:
            return {"items": [{"id": row.id, "cutoff": row.cutoff.isoformat(), "digest": row.digest, "card_count": len(row.cards)} for row in session.scalars(select(CorpusRelease)).all()]}

    @app.post("/api/v1/incidents/search/hybrid")
    def hybrid(body: HybridRequest, user: Annotated[Account, Depends(require_reviewer)]) -> dict[str, Any]:
        enforce_access_limit("paid:" + user.id, 30, 3600)
        return hybrid_search(body.query, user.id, body.idempotency_key, body.corpus_id, datetime.fromisoformat(body.cutoff), exclude_id=body.exclude_id)

    @app.get("/api/v1/scenarios")
    def list_scenarios() -> dict[str, Any]:
        with session_scope() as session:
            rows = session.execute(
                select(ScenarioRevision).order_by(ScenarioRevision.scenario_id, ScenarioRevision.revision)
            ).scalars().all()
            return {
                "items": [
                    {
                        "scenario_id": r.scenario_id,
                        "revision": r.revision,
                        "title": r.title,
                        "tags": r.tags,
                        "defect_statement": r.defect_statement,
                        "decision_at": r.decision_at.isoformat(),
                    }
                    for r in rows
                ],
                "latest_attempts": latest_attempt_summaries(session),
            }

    @app.get("/api/v1/scenarios/{scenario_id}/revisions/{revision}")
    def scenario_detail(scenario_id: str, revision: int) -> dict[str, Any]:
        with session_scope() as session:
            row = session.get(ScenarioRevision, (scenario_id, revision))
            if row is None:
                raise ServiceError("SCENARIO_UNKNOWN", "Unknown scenario revision", 404)
            return {
                "scenario_id": row.scenario_id,
                "revision": row.revision,
                "title": row.title,
                "tags": row.tags,
                "defect_statement": row.defect_statement,
                "decision_at": row.decision_at.isoformat(),
                "event": row.event,
                "target": row.target,
                "catalog_revision_id": row.catalog_revision_id,
                "pinned_snapshot_ids": row.pinned_snapshot_ids,
            }

    @app.get("/api/v1/snapshots/{snapshot_id}")
    def snapshot_detail(snapshot_id: str) -> dict[str, Any]:
        with session_scope() as session:
            row = session.get(SourceSnapshot, snapshot_id)
            if row is None:
                raise ServiceError("SNAPSHOT_UNKNOWN", "Unknown snapshot", 404)
            return {
                "id": row.id,
                "kind": row.kind,
                "source_system": row.source_system,
                "scope": row.scope,
                "declared_evidence_at": row.declared_evidence_at.isoformat(),
                "coverage_complete": row.coverage_complete,
                "content_digest": row.content_digest,
                "payload": row.payload,
            }

    @app.get("/api/v1/configurations")
    def configurations() -> dict[str, Any]:
        with session_scope() as session:
            rows = session.execute(
                select(ExecutionConfiguration).order_by(ExecutionConfiguration.id)
            ).scalars().all()
            return {
                "items": [
                    {
                        "id": r.id,
                        "name": r.name,
                        "policy_kind": r.policy_kind,
                        "settings": r.settings,
                        "known_limitation": r.known_limitation,
                    }
                    for r in rows
                ]
            }

    @app.post("/api/v1/replays")
    def create_replay(
        body: ReplayRequest, _limits: None = Depends(limit_public_execution)
    ) -> dict[str, Any]:
        with session_scope() as session:
            attempt = execute_replay(
                session,
                body.scenario_id,
                body.scenario_revision,
                body.configuration_id,
                body.idempotency_key,
            )
            return attempt_report(attempt)

    @app.get("/api/v1/replays/latest")
    def latest_replay(
        scenario_id: str, scenario_revision: int, configuration_id: str
    ) -> dict[str, Any]:
        with session_scope() as session:
            attempt = latest_saved_attempt(
                session, scenario_id, scenario_revision, configuration_id
            )
            return attempt_report(attempt)

    @app.get("/api/v1/replays/{attempt_id}")
    def replay_detail(attempt_id: str) -> dict[str, Any]:
        with session_scope() as session:
            attempt = session.get(ReplayAttempt, attempt_id)
            if attempt is None:
                raise ServiceError("REPLAY_UNKNOWN", "Unknown replay attempt", 404)
            return attempt_report(attempt)

    def _preview_body(body: ImportRequestBody) -> dict[str, Any]:
        preview = preview_import(
            body.profile_id,
            body.csv_text,
            body.declared_evidence_at,
            body.coverage_complete,
            body.scope,
        )
        issues_by_row: dict[int, list[dict[str, Any]]] = {}
        for issue in preview.issues:
            issues_by_row.setdefault(issue.row, []).append(
                {
                    "code": issue.code,
                    "severity": issue.severity,
                    "column": issue.column,
                    "raw_value": issue.raw_value,
                    "message": issue.message,
                }
            )
        return {
            "profile_id": preview.profile_id,
            "snapshot_kind": preview.snapshot_kind,
            "headers": list(preview.headers),
            "ignored_columns": list(preview.ignored_columns),
            "declared_evidence_at": preview.declared_evidence_at,
            "coverage_complete": preview.coverage_complete,
            "scope": preview.scope,
            "preview_digest": preview.preview_digest,
            "raw_digest": preview.raw_digest,
            "counts": {
                "rows": len(preview.rows),
                "blocking": preview.blocking_count,
                "warning": preview.warning_count,
            },
            "rows": [
                {
                    "row": row.row,
                    "raw": row.raw,
                    "normalized": row.normalized,
                    "normalizations": list(row.normalizations),
                    "issues": issues_by_row.get(row.row, []),
                }
                for row in preview.rows
            ],
            "file_issues": issues_by_row.get(0, []),
        }

    @app.post("/api/v1/review-checks")
    def create_review_check(
        body: ReviewCheckRequest, _limits: None = Depends(limit_public_execution)
    ) -> dict[str, Any]:
        with session_scope() as session:
            return review_check(
                session,
                body.original_replay_id,
                body.target_scenario_id,
                body.target_scenario_revision,
            )

    @app.get("/api/v1/review-checks")
    def list_review_checks(replay_id: str | None = None) -> dict[str, Any]:
        with session_scope() as session:
            query = select(ReviewCheck).order_by(ReviewCheck.created_at.desc()).limit(20)
            if replay_id:
                query = query.where(ReviewCheck.original_replay_id == replay_id)
            rows = session.execute(query).scalars().all()
            return {
                "items": [
                    {
                        "id": r.id,
                        "original_replay_id": r.original_replay_id,
                        "target_scenario_id": r.target_scenario_id,
                        "target_scenario_revision": r.target_scenario_revision,
                        "outcome": r.outcome,
                        "changed_paths": r.changed_paths,
                        "reason_codes": r.reason_codes,
                        "created_at": r.created_at.isoformat(),
                    }
                    for r in rows
                ]
            }

    @app.get("/api/v1/replays/{attempt_id}/export")
    def export_replay(attempt_id: str) -> dict[str, Any]:
        with session_scope() as session:
            return replay_export(session, attempt_id)

    if effective_mode == "local":
        @app.post("/api/v1/imports/preview")
        def import_preview(body: ImportRequestBody, user: Annotated[Account, Depends(require_owner)]) -> dict[str, Any]:
            return _preview_body(body)

        @app.post("/api/v1/imports/publish")
        def import_publish(body: PublishRequestBody, user: Annotated[Account, Depends(require_owner)]) -> dict[str, Any]:
            preview = preview_import(
                body.profile_id,
                body.csv_text,
                body.declared_evidence_at,
                body.coverage_complete,
                body.scope,
            )
            if preview.preview_digest != body.preview_digest:
                raise ServiceError(
                    "PREVIEW_MISMATCH",
                    "The CSV or metadata changed since the preview was computed; preview again.",
                    409,
                )
            with session_scope() as session:
                return publish_import(session, preview, body.csv_text)

        @app.post("/api/v1/notes/parse")
        def parse_note(body: NoteParseRequest, user: Annotated[Account, Depends(require_owner)]) -> dict[str, Any]:
            parser = get_parser(None)
            draft = parser.parse(body.text, CATALOG)
            resolution = resolve_draft(draft, CATALOG)
            with session_scope() as session:
                call = ParserCall(
                    note_text=body.text,
                    note_digest="sha256:" + sha256(body.text.encode()).hexdigest(),
                    parser_kind=draft.parser_kind,
                    model=draft.model,
                    prompt_digest=draft.prompt_digest,
                    schema_version=1,
                    response={
                        "event_category": draft.event_category,
                        "subject_mentions": list(draft.subject_mentions),
                        "operation_mentions": list(draft.operation_mentions),
                        "polarity": draft.polarity,
                        "uncertainty_phrase": draft.uncertainty_phrase,
                        "raw_temporal_expressions": list(draft.raw_temporal_expressions),
                        "ambiguity_notes": list(draft.ambiguity_notes),
                    },
                    resolution=resolution,
                    usage=draft.usage,
                )
                session.add(call)
                session.commit()
                return {
                    "parser_call_id": call.id,
                    "parser_kind": draft.parser_kind,
                    "live": draft.parser_kind == "openai-structured",
                    "draft": call.response,
                    "resolution": resolution,
                }

        @app.post("/api/v1/notes/confirm")
        def confirm_note(body: NoteConfirmRequest, user: Annotated[Account, Depends(require_owner)]) -> dict[str, Any]:
            with session_scope() as session:
                source_ref = f"{body.source_kind}:{body.parser_call_id or 'entry'}"
                return confirm_event_and_fork(
                    session,
                    body.scenario_id,
                    body.scenario_revision,
                    subject_operator_id=body.subject_operator_id,
                    summary=body.summary,
                    observed_at=body.observed_at,
                    source_kind=body.source_kind,
                    source_ref=source_ref,
                    parser_call_id=body.parser_call_id,
                    corrections=body.corrections,
                )

        @app.post("/api/v1/scenarios/{scenario_id}/revisions/{revision}/fork")
        def scenario_fork(scenario_id: str, revision: int, body: ForkRequest, user: Annotated[Account, Depends(require_owner)]) -> dict[str, Any]:
            with session_scope() as session:
                fork = fork_scenario(session, scenario_id, revision, body.snapshot_id)
                return {
                    "scenario_id": fork.scenario_id,
                    "revision": fork.revision,
                    "title": fork.title,
                    "tags": fork.tags,
                    "pinned_snapshot_ids": fork.pinned_snapshot_ids,
                }

    @app.get("/api/v1/suites")
    def list_suites() -> dict[str, Any]:
        with session_scope() as session:
            rows = session.execute(select(SuiteRevision).order_by(SuiteRevision.id)).scalars().all()
            return {
                "items": [
                    {
                        "id": r.id,
                        "revision": r.revision,
                        "label": r.label,
                        "case_count": len(r.items),
                        "content_digest": r.content_digest,
                    }
                    for r in rows
                ]
            }

    @app.get("/api/v1/comparisons")
    def list_comparisons() -> dict[str, Any]:
        with session_scope() as session:
            rows = (
                session.execute(
                    select(ComparisonReport).order_by(ComparisonReport.created_at.desc()).limit(20)
                )
                .scalars()
                .all()
            )
            return {"items": [comparison_summary(r) for r in rows]}

    if effective_mode == "local":
        # A suite execution runs up to two replays per case under a 30-second
        # budget — a local-owner action, absent from the public demo. Saved
        # reports stay viewable everywhere.
        @app.post("/api/v1/comparisons")
        def create_comparison(body: ComparisonRequest, user: Annotated[Account, Depends(require_owner)]) -> dict[str, Any]:
            with session_scope() as session:
                report = run_comparison(
                    session,
                    body.suite_id,
                    body.baseline_config_id,
                    body.candidate_config_id,
                    body.idempotency_key,
                )
                return comparison_report(report)

    @app.get("/api/v1/comparisons/{comparison_id}")
    def comparison_detail(comparison_id: str) -> dict[str, Any]:
        with session_scope() as session:
            report = session.get(ComparisonReport, comparison_id)
            if report is None:
                raise ServiceError("COMPARISON_UNKNOWN", "Unknown comparison report", 404)
            return comparison_report(report)

    def comparison_summary(report: ComparisonReport) -> dict[str, Any]:
        return {
            "id": report.id,
            "suite_id": report.suite_id,
            "suite_revision": report.suite_revision,
            "baseline_config_id": report.baseline_config_id,
            "candidate_config_id": report.candidate_config_id,
            "status": report.status,
            "totals": report.totals,
            "created_at": report.created_at.isoformat(),
        }

    def comparison_report(report: ComparisonReport) -> dict[str, Any]:
        return {
            **comparison_summary(report),
            "manifest_digest": report.manifest_digest,
            "items": report.items,
            "execution_kind": "live",
        }

    def attempt_report(attempt: ReplayAttempt) -> dict[str, Any]:
        return {
            "id": attempt.id,
            "idempotency_key": attempt.idempotency_key,
            "scenario_id": attempt.scenario_id,
            "scenario_revision": attempt.scenario_revision,
            "configuration_id": attempt.configuration_id,
            "lifecycle": attempt.lifecycle,
            "domain_outcome": attempt.domain_outcome,
            "result": attempt.result,
            "expectation_verdict": attempt.expectation_verdict,
            "expectation_failures": attempt.expectation_failures,
            "context_digest": attempt.context_digest,
            "manifest_digest": attempt.manifest_digest,
            "created_at": attempt.created_at.isoformat(),
            "completed_at": attempt.completed_at.isoformat() if attempt.completed_at else None,
            "elapsed_ms": attempt.elapsed_ms,
            "execution_kind": "live",  # this endpoint always reports a persisted attempt
        }

    return app


app = create_app()
