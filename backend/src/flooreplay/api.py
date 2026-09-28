"""HTTP surface. Thin: it validates, delegates to the service, and shapes
responses. Domain blocks (NEEDS_CONTEXT and friends) are successful
executions, never HTTP server errors."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from .config import settings
from .db import session_scope
from .fixtures import CATALOG, CONFIGURATIONS
from .importing import ImportStructuralError, preview_import
from .models import (
    ComparisonReport,
    ExecutionConfiguration,
    ReplayAttempt,
    ScenarioRevision,
    SourceSnapshot,
    SuiteRevision,
)
from .parsing import (
    ParserUnavailable,
    get_parser,
    resolve_draft,
)
from .service import (
    ServiceError,
    confirm_event_and_fork,
    execute_replay,
    fork_scenario,
    latest_attempt_summaries,
    publish_import,
    replay_export,
    review_check,
    run_comparison,
)


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


def create_app(mode: str | None = None) -> FastAPI:
    effective_mode = mode or settings.mode
    app = FastAPI(title="FloorReplay API", version="0.1.0")

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
        return JSONResponse(
            status_code=exc.http_status,
            content=ErrorEnvelope(
                code=exc.code, message=exc.message, trace_id=str(uuid.uuid4())
            ).model_dump(),
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

    @app.get("/api/v1/capabilities")
    def capabilities() -> dict[str, Any]:
        return {
            "mode": effective_mode,
            "imports_enabled": effective_mode == "local",
            "build_id": settings.build_id,
            "live_parser_available": bool(settings.openai_api_key),
            "parser_kind": "openai-structured" if settings.openai_api_key else "rule-baseline",
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
                session.execute(select(1))
        except Exception as exc:  # pragma: no cover - infra failure path
            raise ServiceError("DATABASE_UNAVAILABLE", str(exc), 503) from exc
        return {"status": "ready"}

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
    def create_replay(body: ReplayRequest) -> dict[str, Any]:
        with session_scope() as session:
            attempt = execute_replay(
                session,
                body.scenario_id,
                body.scenario_revision,
                body.configuration_id,
                body.idempotency_key,
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
    def create_review_check(body: ReviewCheckRequest) -> dict[str, Any]:
        with session_scope() as session:
            return review_check(
                session,
                body.original_replay_id,
                body.target_scenario_id,
                body.target_scenario_revision,
            )

    @app.get("/api/v1/review-checks")
    def list_review_checks(replay_id: str | None = None) -> dict[str, Any]:
        from .models import ReviewCheck as ReviewCheckModel

        with session_scope() as session:
            query = select(ReviewCheckModel).order_by(ReviewCheckModel.created_at.desc()).limit(20)
            if replay_id:
                query = query.where(ReviewCheckModel.original_replay_id == replay_id)
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
        def import_preview(body: ImportRequestBody) -> dict[str, Any]:
            return _preview_body(body)

        @app.post("/api/v1/imports/publish")
        def import_publish(body: PublishRequestBody) -> dict[str, Any]:
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
        def parse_note(body: NoteParseRequest) -> dict[str, Any]:
            parser = get_parser(settings.openai_api_key or None)
            draft = parser.parse(body.text, CATALOG)
            resolution = resolve_draft(draft, CATALOG)
            from hashlib import sha256

            from .models import ParserCall as ParserCallModel

            with session_scope() as session:
                call = ParserCallModel(
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
        def confirm_note(body: NoteConfirmRequest) -> dict[str, Any]:
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
        def scenario_fork(scenario_id: str, revision: int, body: ForkRequest) -> dict[str, Any]:
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

    @app.post("/api/v1/comparisons")
    def create_comparison(body: ComparisonRequest) -> dict[str, Any]:
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
            "execution_kind": "live",  # this endpoint always reports a persisted attempt
        }

    return app


app = create_app()
