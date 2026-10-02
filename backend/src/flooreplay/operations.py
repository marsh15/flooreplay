"""Allowlisted request receipts and actor-scoped durable provider diagnostics."""
from __future__ import annotations

import json
import logging
import re
import time
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import DateTime, Float, Integer, String, select
from sqlalchemy.orm import Mapped, mapped_column

from .db import session_scope
from .models import Base
from .paid_models import AIRun, RetrievalRun, SpendEntry

logger = logging.getLogger(__name__)
request_identity: ContextVar[str | None] = ContextVar("operation_request_id", default=None)


class OperationalEvent(Base):
    __tablename__ = "operational_events"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: str(uuid4()))
    actor_id: Mapped[str] = mapped_column(String(64), index=True)
    request_id: Mapped[str] = mapped_column(String(64), index=True)
    route: Mapped[str] = mapped_column(String(200))
    method: Mapped[str] = mapped_column(String(16))
    status_code: Mapped[int] = mapped_column(Integer)
    failure_category: Mapped[str | None] = mapped_column(String(48), nullable=True)
    elapsed_seconds: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


def install_operational_monitoring(app: FastAPI) -> None:
    # Uvicorn access lines include raw search query strings; allowlisted receipts replace them.
    logging.getLogger("uvicorn.access").disabled = True
    @app.middleware("http")
    async def receipt(request: Request, call_next: Any) -> Any:
        request.state.request_id = str(uuid4())
        context_token = request_identity.set(request.state.request_id)
        started = time.monotonic()
        status = 500
        try:
            try:
                response = await call_next(request)
            except Exception:
                request.state.failure_category = "UNAVAILABLE"
                response = JSONResponse({"code": "UNAVAILABLE", "message": "The request could not be completed.", "trace_id": request.state.request_id}, status_code=503)
            status = response.status_code
            response.headers["X-Request-ID"] = request.state.request_id
            return response
        finally:
            request_identity.reset(context_token)
            route = getattr(request.scope.get("route"), "path", "unmatched")
            category = getattr(request.state, "failure_category", None)
            category = category if isinstance(category, str) and re.fullmatch(r"[A-Z_]{1,48}", category) else ("SERVER_ERROR" if status >= 500 else "REQUEST_REJECTED" if status >= 400 else None)
            actor = getattr(request.state, "actor_id", None)
            elapsed = round(time.monotonic() - started, 6)
            # Unauthenticated traffic stays anonymous in logs, never a shared private inbox.
            logger.info(json.dumps({"event": "request_receipt", "request_id": request.state.request_id, "entry_point": "http", "route": route, "status_code": status, "elapsed_seconds": elapsed, "failure_category": category}))
            if actor:
                try:
                    with session_scope() as session:
                        session.add(OperationalEvent(actor_id=actor, request_id=request.state.request_id, route=route, method=request.method, status_code=status, failure_category=category, elapsed_seconds=elapsed))
                except Exception:
                    logger.error(json.dumps({"event": "operational_receipt_persistence_failed", "request_id": request.state.request_id, "entry_point": "http"}))


def operational_report(actor_id: str, query: str = "", limit: int = 50) -> dict[str, Any]:
    """No raw questions, source text, tokens, private paths or provider response bodies."""
    from .ai_runs import lookup_run

    limit = max(1, min(limit, 100))
    query = query.strip()[:120]
    with session_scope() as session:
        statement = select(OperationalEvent).where(OperationalEvent.actor_id == actor_id)
        if query:
            pattern = "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            statement = statement.where(OperationalEvent.request_id.ilike(pattern) | OperationalEvent.route.ilike(pattern) | OperationalEvent.failure_category.ilike(pattern))
        events = session.scalars(statement.order_by(OperationalEvent.created_at.desc()).limit(limit)).all()
        runs = session.scalars(select(AIRun).where(AIRun.user_id == actor_id).order_by(AIRun.created_at.desc()).limit(100)).all()
        retrievals = session.scalars(select(RetrievalRun).where(RetrievalRun.user_id == actor_id).order_by(RetrievalRun.created_at.desc()).limit(100)).all()
        retrieval_views: list[dict[str, Any]] = [{"id": r.id, "status": "INTERRUPTED_PENDING" if r.status == "RUNNING" and (datetime.now(UTC) - r.created_at).total_seconds() > 65 else r.status, "task": "retrieval", "request_id": None, "incident_id": None, "analysis_id": "not_recorded", "created_at": r.created_at.isoformat(), "completed_at": None, "elapsed_seconds": None, "provider_receipts": [], "inspect_url": "/operations?q=" + r.id} for r in retrievals]
        run_ids = [run.id for run in runs]
        entries = session.scalars(select(SpendEntry).where(SpendEntry.user_id == actor_id).order_by(SpendEntry.created_at.desc()).limit(100)).all()
        event_views: list[dict[str, Any]] = [{"request_id": e.request_id, "route": e.route, "method": e.method, "status_code": e.status_code, "failure_category": e.failure_category, "elapsed_seconds": e.elapsed_seconds, "created_at": e.created_at.isoformat()} for e in events]
        spend = [{"id": e.id, "operation": e.operation, "purpose": e.purpose, "status": e.status, "reserved_inr": e.reserved_inr, "charged_inr": e.charged_inr} for e in entries]
    operations = []
    alerts = []
    for run_id in run_ids:
        run = lookup_run(run_id, actor_id)
        receipts = [{key: attempt[key] for key in ("response_id", "request_id", "status") if key in attempt} for attempt in run["attempts"]]
        item = {"id": run_id, "status": run["status"], "task": run["task"], "request_id": run["configuration"].get("request_id"), "analysis_id": run["analysis_id"], "incident_id": run["packet"].get("incident_id"), "created_at": run["created_at"], "completed_at": run["completed_at"], "elapsed_seconds": (run.get("result") or {}).get("elapsed_seconds"), "provider_receipts": receipts, "inspect_url": "/api/v1/ai-runs/" + run_id}
        if not query or query.lower() in str(item).lower():
            operations.append(item)
        if run["status"] == "UNCERTAIN":
            alerts.append({"code": "UNCERTAIN_PROVIDER_CHARGE", "severity": "page", "operation_id": run_id, "inspect_url": item["inspect_url"], "remediation": "Inspect provider receipts and billing before reconciling the retained reservation. Do not submit a new paid request."})
        elif run["status"] in {"INVALID", "UNAVAILABLE", "INCOMPLETE"}:
            alerts.append({"code": "DRAFT_FAILED", "severity": "ticket", "operation_id": run_id, "inspect_url": item["inspect_url"], "remediation": "Inspect the pinned run and failure category; use the deterministic report while investigating."})
    for retrieval in retrieval_views:
        if not query or query.lower() in str(retrieval).lower():
            operations.append(retrieval)
        if retrieval["status"] in {"INTERRUPTED_PENDING", "FAILED"}:
            alerts.append({"code": "RETRIEVAL_INTERRUPTED", "severity": "ticket", "operation_id": retrieval["id"], "remediation": "Inspect related embedding reservations. The same retrieval identity cannot dispatch another paid request automatically."})
    for entry in spend:
        if entry["status"] == "UNCERTAIN":
            alerts.append({"code": "UNCERTAIN_RESERVATION", "severity": "page", "operation_id": entry["id"], "remediation": "Reconcile provider billing before releasing this reservation. Do not infer that an interrupted embedding or generation was free."})
    for event in event_views:
        if event["status_code"] >= 500:
            alerts.append({"code": "REQUEST_FAILED", "severity": "page", "request_id": event["request_id"], "remediation": "Search this request ID in host logs. Check readiness and the deployed commit; inspect related operations before retrying a paid request."})
    return {"scope": "signed_in_owner_operations", "events": event_views, "operations": operations[:limit], "allowance_entries": spend, "alerts": alerts[:100], "execution_model": "bounded_request_path", "recovery_policy": "Expired running calls become uncertain; reservations remain committed and no provider call is retried automatically.", "limitations": ["Actor-scoped receipts; this is not a fleet-wide or externally delivered pager.", "Database outage receipts remain in host logs; persisted evidence may be incomplete."]}
