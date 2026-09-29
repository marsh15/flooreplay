"""PostgreSQL-backed queue for optional local-only incident drafts."""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import settings
from .db import engine, session_scope
from .incident_ai import draft_with_ollama
from .models import IncidentAnalysis, IncidentModelJob
from .service import ServiceError


def _packet(analysis: IncidentAnalysis) -> dict[str, Any]:
    report = analysis.report
    evidence = [
        {key: event[key] for key in ("id", "type", "summary", "occurred_at", "start", "end", "source_id", "assertion") if key in event}
        for event in report.get("timeline", [])
    ]
    if len(evidence) > 30:
        raise ServiceError("PACKET_TOO_LARGE", "Narrow the investigation before local drafting", 422)
    metrics = [
        {"id": key, "value": value, "unit": report["metrics"].get("unit", "")}
        for key, value in report["metrics"].items()
        if key in {"planned", "observed", "shortfall", "variance", "blocked_minutes", "baseline_target"}
        and isinstance(value, (int, float))
    ]
    return {
        "incident_id": analysis.incident_id, "revision": analysis.revision,
        "evidence": evidence, "metrics": metrics,
        "precedents": [
            {key: item[key] for key in ("id", "title", "match_reason", "differences") if key in item}
            for item in report.get("precedents", [])[:3]
        ],
        "missing_evidence": [
            reason
            for name in ("production", "timeline", "hypotheses", "actions")
            for reason in report.get("capabilities", {}).get(name, {}).get("reasons", [])
        ],
        "hypotheses": report.get("hypotheses", []),
    }


def enqueue_draft(session: Session, analysis: IncidentAnalysis, key: str, question: str) -> IncidentModelJob:
    session.execute(select(func.pg_advisory_xact_lock(func.hashtext(key))))
    existing = session.execute(select(IncidentModelJob).where(IncidentModelJob.idempotency_key == key)).scalar_one_or_none()
    if existing is not None:
        if (existing.analysis_id, existing.question) != (analysis.id, question):
            raise ServiceError("IDEMPOTENCY_CONFLICT", "Key already used for another draft", 409)
        return existing
    packet = _packet(analysis)
    job = IncidentModelJob(
        idempotency_key=key, analysis_id=analysis.id, question=question,
        packet=packet, status="QUEUED", attempts=0,
    )
    session.add(job)
    session.flush()
    return job


def job_view(job: IncidentModelJob) -> dict[str, Any]:
    return {
        "id": job.id, "analysis_id": job.analysis_id, "status": job.status,
        "attempts": job.attempts, "created_at": job.created_at.isoformat(),
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "result": job.result,
    }


def work_once(owner: str | None = None) -> bool:
    owner = owner or str(uuid.uuid4())
    with session_scope() as session:
        job = session.execute(
            select(IncidentModelJob)
            .where(IncidentModelJob.status == "QUEUED")
            .order_by(IncidentModelJob.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        ).scalar_one_or_none()
        if job is None:
            return False
        job.status = "RUNNING"
        job.owner = owner
        job.attempts += 1
        job.lease_until = datetime.now(UTC) + timedelta(seconds=150)
        job_id, packet, question = job.id, job.packet, job.question
    try:
        result = draft_with_ollama(packet, question=question, model=settings.local_model)
    except (ValueError, TypeError) as exc:
        result = {"status": "INVALID_PACKET", "reason": str(exc)}
    with session_scope() as session:
        job = session.get(IncidentModelJob, job_id)
        if job is None or job.status != "RUNNING" or job.owner != owner:
            return True
        job.result = result
        job.status = "COMPLETED" if result["status"] == "DRAFT_NEEDS_REVIEW" else "FAILED"
        job.completed_at = datetime.now(UTC)
        job.lease_until = None
    return True


def run_worker() -> None:
    if settings.mode != "local":
        raise RuntimeError("Local model worker is disabled in public mode")
    owner = str(uuid.uuid4())
    with engine.connect() as lock_connection:
        if not lock_connection.scalar(select(func.pg_try_advisory_lock(947_361))):
            raise RuntimeError("Another local model worker already owns the queue")
        lock_connection.commit()
        try:
            while True:
                with session_scope() as session:
                    expired = session.execute(
                        select(IncidentModelJob).where(
                            IncidentModelJob.status == "RUNNING",
                            IncidentModelJob.lease_until < datetime.now(UTC),
                        ).with_for_update(skip_locked=True)
                    ).scalars().all()
                    for job in expired:
                        job.status = "INTERRUPTED"
                        job.completed_at = datetime.now(UTC)
                        job.result = {"status": "INTERRUPTED", "reason": "Worker lease expired"}
                if not work_once(owner):
                    time.sleep(2)
        finally:
            lock_connection.execute(select(func.pg_advisory_unlock(947_361)))
