"""Assigned checks, source responses, outcomes and explicit incident resolution."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from .auth import Account, user_view
from .domain.hashing import digest, incident_digest
from .incident_engine import analyze_incident, incident_evidence_card
from .models import Base, IncidentAnalysis, IncidentRevision, IncidentSourceArtifact
from .service import ServiceError


class IncidentCheck(Base):
    __tablename__ = "incident_checks"
    workspace_id: Mapped[str] = mapped_column(String(64), default="public-demo", server_default="public-demo", index=True)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: str(uuid4()))
    incident_id: Mapped[str] = mapped_column(String(64), index=True)
    analysis_id: Mapped[str] = mapped_column(ForeignKey("incident_analyses.id"))
    revision: Mapped[int] = mapped_column(Integer)
    proposal_id: Mapped[str] = mapped_column(String(64))
    category: Mapped[str] = mapped_column(String(32))
    question: Mapped[str] = mapped_column(Text)
    requested_fields: Mapped[list[str]] = mapped_column(JSONB)
    assignee_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"))
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32))
    created_by: Mapped[str] = mapped_column(ForeignKey("accounts.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    response: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    outcome: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)


class WorkflowActivity(Base):
    __tablename__ = "incident_workflow_activities"
    workspace_id: Mapped[str] = mapped_column(String(64), default="public-demo", server_default="public-demo", index=True)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: str(uuid4()))
    incident_id: Mapped[str] = mapped_column(String(64), index=True)
    task_id: Mapped[str | None] = mapped_column(ForeignKey("incident_checks.id"), nullable=True)
    actor: Mapped[str] = mapped_column(ForeignKey("accounts.id"))
    kind: Mapped[str] = mapped_column(String(32))
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class IncidentResolution(Base):
    __tablename__ = "incident_resolutions"
    workspace_id: Mapped[str] = mapped_column(String(64), default="public-demo", server_default="public-demo", index=True)
    incident_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    state: Mapped[str] = mapped_column(String(16))
    rationale: Mapped[str] = mapped_column(Text)
    resolved_revision: Mapped[int] = mapped_column(Integer)


class WorkflowReceipt(Base):
    __tablename__ = "incident_workflow_receipts"
    workspace_id: Mapped[str] = mapped_column(String(64), default="public-demo", server_default="public-demo", index=True)
    __table_args__ = (UniqueConstraint("actor", "request_key"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: str(uuid4()))
    actor: Mapped[str] = mapped_column(ForeignKey("accounts.id"))
    request_key: Mapped[str] = mapped_column(String(120))
    operation: Mapped[str] = mapped_column(String(200))
    fingerprint: Mapped[str] = mapped_column(String(80))
    result: Mapped[dict[str, Any]] = mapped_column(JSONB)


FIELD_SETS = {
    "material": (
        "material_readiness",
        ["affected_operations", "material_status", "restart_conditions"],
    ),
    "machine": ("maintenance_note", ["affected_operations", "repair_status", "restart_conditions"]),
    "quality": ("qc_hold", ["affected_operations", "qc_disposition", "release_conditions"]),
    "staffing": ("staffing_event", ["affected_operations", "coverage_status", "remaining_gaps"]),
    "changeover": (
        "setup_changeover",
        ["setup_status", "restart_conditions", "remaining_requirements"],
    ),
    "planning_reporting": (
        "reporting_correction",
        ["approved_plan", "reporting_corrections", "recovery_target"],
    ),
}
TERMINAL = {"COMPLETED", "CANCELLED"}


def _time(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None or result.utcoffset() is None:
            raise ValueError
        return result.astimezone(UTC)
    except (ValueError, TypeError, AttributeError):
        raise ServiceError(
            "INVALID_TIME", "Use an ISO timestamp including a timezone", 422
        ) from None


def _text(value: str, label: str, maximum: int = 2000) -> str:
    if not 3 <= len(value.strip()) <= maximum:
        raise ServiceError(
            "INVALID_WORKFLOW_INPUT", f"{label} must contain 3–{maximum} characters", 422
        )
    return value.strip()


def _lock(session: Session, incident_id: str) -> None:
    session.execute(select(func.pg_advisory_xact_lock(func.hashtext(incident_id))))


def _latest(session: Session, incident_id: str) -> IncidentRevision:
    row = session.scalar(
        select(IncidentRevision)
        .where(IncidentRevision.incident_id == incident_id)
        .order_by(IncidentRevision.revision.desc())
        .limit(1)
    )
    if row is None:
        raise ServiceError("INCIDENT_UNKNOWN", "Unknown incident", 404)
    return row


def _account(session: Session, account_id: str) -> Account:
    account = session.get(Account, account_id)
    if account is None or account.disabled:
        raise ServiceError("ASSIGNEE_UNAVAILABLE", "Choose an active named account", 422)
    return account


def _replay(
    session: Session, user: Account, operation: str, body: dict[str, Any]
) -> dict[str, Any] | None:
    key = body["idempotency_key"]
    session.execute(select(func.pg_advisory_xact_lock(func.hashtext(f"workflow:{user.id}:{key}"))))
    existing = session.scalar(
        select(WorkflowReceipt).where(
            WorkflowReceipt.actor == user.id, WorkflowReceipt.request_key == key
        )
    )
    if existing:
        if existing.operation != operation or existing.fingerprint != digest(body):
            raise ServiceError(
                "IDEMPOTENCY_CONFLICT",
                "Request identity already used for another workflow operation",
                409,
            )
        return existing.result
    return None


def _receipt(
    session: Session, user: Account, operation: str, body: dict[str, Any], result: dict[str, Any]
) -> dict[str, Any]:
    session.add(
        WorkflowReceipt(
            workspace_id=_latest(session, result["incident_id"]).workspace_id,
            actor=user.id,
            request_key=body["idempotency_key"],
            operation=operation,
            fingerprint=digest(body),
            result=result,
        )
    )
    session.flush()
    return result


def _activity(
    session: Session,
    incident_id: str,
    user: Account,
    kind: str,
    text: str,
    task: IncidentCheck | None = None,
) -> None:
    session.add(
        WorkflowActivity(
            incident_id=incident_id,
            task_id=task.id if task else None,
            actor=user.id,
            kind=kind,
            text=text,
            created_at=datetime.now(UTC),
        )
    )
    if task:
        task.updated_at = max(datetime.now(UTC), task.updated_at + timedelta(microseconds=1))
    session.flush()


def _activity_view(row: WorkflowActivity) -> dict[str, str]:
    return {
        "id": row.id,
        "actor": row.actor,
        "kind": row.kind,
        "text": row.text,
        "created_at": row.created_at.isoformat(),
    }


def task_view(session: Session, task: IncidentCheck) -> dict[str, Any]:
    account = session.get(Account, task.assignee_id)
    activities = session.scalars(
        select(WorkflowActivity)
        .where(WorkflowActivity.task_id == task.id)
        .order_by(WorkflowActivity.created_at, WorkflowActivity.id)
    ).all()
    return {
        "id": task.id,
        "incident_id": task.incident_id,
        "analysis_id": task.analysis_id,
        "revision": task.revision,
        "proposal_id": task.proposal_id,
        "question": task.question,
        "requested_fields": task.requested_fields,
        "assignee_id": task.assignee_id,
        "assignee_name": account.display_name if account else task.assignee_id,
        "due_at": task.due_at.isoformat(),
        "status": task.status,
        "created_by": task.created_by,
        "created_at": task.created_at.isoformat(),
        "updated_at": task.updated_at.isoformat(),
        "overdue": task.status not in TERMINAL and task.due_at < datetime.now(UTC),
        "activities": [_activity_view(row) for row in activities],
        "response": task.response,
        "outcome": task.outcome,
    }


def assignees(session: Session) -> dict[str, Any]:
    from .workspaces import restrict_accounts
    accounts = session.scalars(
        restrict_accounts(select(Account))
        .where(Account.disabled.is_(False))
        .order_by(Account.display_name, Account.id)
    ).all()
    return {"items": [user_view(account) for account in accounts]}


def workflow_view(session: Session, incident_id: str) -> dict[str, Any]:
    _lock(session, incident_id)
    revision = _latest(session, incident_id)
    analysis = analyze_incident(revision.payload)
    rows = session.scalars(
        select(IncidentCheck)
        .where(IncidentCheck.incident_id == incident_id)
        .order_by(IncidentCheck.created_at, IncidentCheck.id)
    ).all()
    tasks = [task_view(session, row) for row in rows]
    resolution = session.get(IncidentResolution, incident_id)
    activities = session.scalars(
        select(WorkflowActivity)
        .where(WorkflowActivity.incident_id == incident_id, WorkflowActivity.task_id.is_(None))
        .order_by(WorkflowActivity.created_at, WorkflowActivity.id)
    ).all()
    return {
        "incident_id": incident_id,
        "current_revision": revision.revision,
        "resolution": resolution.state
        if resolution and resolution.resolved_revision == revision.revision
        else "OPEN",
        "resolution_rationale": resolution.rationale
        if resolution and resolution.resolved_revision == revision.revision
        else None,
        "resolved_revision": resolution.resolved_revision if resolution else None,
        "resolution_activities": [_activity_view(row) for row in activities],
        "tasks": tasks,
        "handover": {
            "summary": analysis["summary"],
            "cutoff": revision.cutoff.isoformat(),
            "uncertainties": [hypothesis["next_check"] for hypothesis in analysis["hypotheses"]],
            "outstanding_checks": [task for task in tasks if task["status"] not in TERMINAL],
            "completed_checks": [task for task in tasks if task["status"] == "COMPLETED"],
        },
    }


def create_check(
    session: Session, analysis_id: str, user: Account, body: dict[str, Any]
) -> dict[str, Any]:
    operation = f"create:{analysis_id}"
    replay = _replay(session, user, operation, body)
    if replay is not None:
        return replay
    analysis = session.get(IncidentAnalysis, analysis_id)
    if analysis is None:
        raise ServiceError("ANALYSIS_UNKNOWN", "Unknown analysis", 404)
    _lock(session, analysis.incident_id)
    latest = _latest(session, analysis.incident_id)
    if analysis.revision != latest.revision:
        raise ServiceError("STALE_ANALYSIS", "Assign checks from the latest evidence revision", 409)
    resolution = session.get(IncidentResolution, analysis.incident_id)
    if (
        resolution
        and resolution.state == "RESOLVED"
        and resolution.resolved_revision == latest.revision
    ):
        raise ServiceError(
            "INCIDENT_RESOLVED", "Reopen the incident before assigning another check", 409
        )
    proposal = next(
        (item for item in analysis.report["proposals"] if item["id"] == body["proposal_id"]), None
    )
    if proposal is None:
        raise ServiceError("PROPOSAL_UNKNOWN", "Unknown proposal in this analysis", 404)
    category = body["proposal_id"].removeprefix("verify-")
    hypothesis = next(
        (item for item in analysis.report["hypotheses"] if item["category"] == category), None
    )
    if category not in FIELD_SETS or hypothesis is None:
        raise ServiceError(
            "CHECK_UNAVAILABLE", "This proposal has no typed verification check", 422
        )
    existing = session.scalar(
        select(IncidentCheck).where(
            IncidentCheck.incident_id == analysis.incident_id,
            IncidentCheck.proposal_id == body["proposal_id"],
            IncidentCheck.status.not_in(TERMINAL),
        )
    )
    if existing:
        raise ServiceError(
            "CHECK_ALREADY_ASSIGNED", "An active check already exists for this proposal", 409
        )
    from .workspaces import require_assignee_workspace
    require_assignee_workspace(session, body["assignee_id"], analysis.workspace_id)
    assignee = _account(session, body["assignee_id"])
    due = _time(body["due_at"])
    now = datetime.now(UTC)
    if due <= now:
        raise ServiceError("INVALID_DEADLINE", "Choose a future deadline", 422)
    task = IncidentCheck(
        incident_id=analysis.incident_id,
        analysis_id=analysis_id,
        revision=analysis.revision,
        proposal_id=body["proposal_id"],
        category=category,
        question=hypothesis["next_check"],
        requested_fields=FIELD_SETS[category][1],
        assignee_id=assignee.id,
        due_at=due,
        status="OPEN",
        created_by=user.id,
        created_at=now,
        updated_at=now,
    )
    session.add(task)
    session.flush()
    _activity(
        session,
        task.incident_id,
        user,
        "ASSIGNED",
        f"Assigned to {assignee.display_name}; due {due.isoformat()}. {task.question}",
        task,
    )
    return _receipt(session, user, operation, body, task_view(session, task))


def _task(session: Session, task_id: str) -> IncidentCheck:
    task = session.get(IncidentCheck, task_id)
    if task is None:
        raise ServiceError("CHECK_UNKNOWN", "Unknown check", 404)
    _lock(session, task.incident_id)
    return session.execute(
        select(IncidentCheck)
        .where(IncidentCheck.id == task_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one()


def _assigned(user: Account, task: IncidentCheck) -> None:
    if user.role != "owner" and task.assignee_id != user.id:
        raise ServiceError(
            "CHECK_ASSIGNEE_REQUIRED",
            "Only the assigned account or owner can record this step",
            403,
        )


def update_check(
    session: Session, task_id: str, user: Account, body: dict[str, Any]
) -> dict[str, Any]:
    operation = f"update:{task_id}"
    replay = _replay(session, user, operation, body)
    if replay is not None:
        return replay
    task = _task(session, task_id)
    if _time(body["expected_updated_at"]) != task.updated_at:
        raise ServiceError("STALE_CHECK", "The check changed; reload before updating it", 409)
    if task.status in TERMINAL and any(
        body.get(field) is not None for field in ("status", "assignee_id", "due_at")
    ):
        raise ServiceError("CHECK_TERMINAL", "Completed or cancelled checks cannot be changed", 409)
    comment = _text(body["comment"], "Update reason")
    privileged = user.role == "owner" or task.created_by == user.id
    status = body.get("status")
    if status == "CANCELLED" and not privileged:
        raise ServiceError(
            "CHECK_CREATOR_REQUIRED", "Only the creator or owner can cancel a check", 403
        )
    if body.get("assignee_id") is not None or body.get("due_at") is not None:
        if not privileged:
            raise ServiceError(
                "CHECK_CREATOR_REQUIRED",
                "Only the creator or owner can reassign or change deadlines",
                403,
            )
        if body.get("assignee_id") is not None:
            from .workspaces import require_assignee_workspace
            require_assignee_workspace(session, body["assignee_id"], task.workspace_id)
            task.assignee_id = _account(session, body["assignee_id"]).id
        if body.get("due_at") is not None:
            due = _time(body["due_at"])
            if due <= datetime.now(UTC):
                raise ServiceError("INVALID_DEADLINE", "Choose a future deadline", 422)
            task.due_at = due
        comment = f"{comment} Assigned to {task.assignee_id}; due {task.due_at.isoformat()}."
    if status == "IN_PROGRESS":
        _assigned(user, task)
        if task.status != "OPEN":
            raise ServiceError("CHECK_STATE", "Only an open check can be started", 409)
    if status is not None:
        task.status = status
    _activity(session, task.incident_id, user, status or "UPDATED", comment, task)
    return _receipt(session, user, operation, body, task_view(session, task))


def respond_check(
    session: Session, task_id: str, user: Account, body: dict[str, Any]
) -> dict[str, Any]:
    operation = f"respond:{task_id}"
    replay = _replay(session, user, operation, body)
    if replay is not None:
        return replay
    task = _task(session, task_id)
    _assigned(user, task)
    if task.status not in {"OPEN", "IN_PROGRESS"}:
        raise ServiceError(
            "CHECK_STATE", "Only an open or in-progress check can receive a response", 409
        )
    base = _latest(session, task.incident_id)
    from .workspaces import allowed_workspaces
    if allowed_workspaces.get() is not None and base.workspace_id == "public-demo":
        raise ServiceError("PRIVATE_RESPONSE_REQUIRED", "Record factory responses in a private workspace; the synthetic public example cannot receive source observations", 422)
    if body["base_revision"] != base.revision:
        raise ServiceError(
            "STALE_REVISION",
            "A newer incident revision exists; reload before attaching the response",
            409,
        )
    summary = _text(body["summary"], "Response summary")
    source_ref = _text(body["source_ref"], "Source reference", 500)
    details = body["details"]
    if (
        len(details) > 20
        or any(
            not key.strip() or len(key) > 80 or not value.strip() or len(value) > 2000
            for key, value in details.items()
        )
        or any(not details.get(key, "").strip() for key in task.requested_fields)
    ):
        raise ServiceError(
            "RESPONSE_FIELDS_REQUIRED",
            "Fill every requested field with a concrete observation or explicit unknown",
            422,
        )
    now = datetime.now(UTC)
    occurred = _time(body["occurred_at"])
    if occurred > now or not base.window_start <= occurred < base.window_end:
        raise ServiceError(
            "INVALID_OCCURRENCE",
            "Response occurrence must be within the incident window and no later than now",
            422,
        )
    if base.cutoff >= now:
        raise ServiceError(
            "CUTOFF_IN_FUTURE",
            "Evidence cannot be appended while the baseline cutoff is in the future",
            409,
        )
    evidence_id = f"check-{task.id}"
    artifact_id = str(uuid4())
    cutoff = max(now, base.cutoff + timedelta(microseconds=1))
    event = {
        "id": evidence_id,
        "source_id": f"workflow:{task.id}",
        "source_system": "workflow-response",
        "source_artifact_id": artifact_id,
        "source_ref": source_ref,
        "type": FIELD_SETS[task.category][0],
        "occurred_at": occurred.isoformat(),
        "available_at": cutoff.isoformat(),
        "imported_at": cutoff.isoformat(),
        "summary": summary,
        "assertion": True,
        "details": details,
        **base.payload["scope"],
        "line_blocking": body["line_blocking"],
    }
    if body["line_blocking"]:
        if not body.get("start") or not body.get("end"):
            raise ServiceError(
                "BLOCK_INTERVAL_REQUIRED", "A confirmed block needs start and end", 422
            )
        start, end = _time(body["start"]), _time(body["end"])
        if not base.window_start <= start < end <= base.window_end or end > now:
            raise ServiceError(
                "INVALID_BLOCK_INTERVAL",
                "Confirmed block interval must fit the incident window and end no later than now",
                422,
            )
        event.update(
            type="line_block",
            linked_categories=[task.category],
            start=start.isoformat(),
            end=end.isoformat(),
        )
    elif body.get("start") is not None or body.get("end") is not None:
        raise ServiceError(
            "INVALID_BLOCK_INTERVAL",
            "Block timestamps require an explicit confirmed line block",
            422,
        )
    payload = {
        **base.payload,
        "revision": base.revision + 1,
        "cutoff": cutoff.isoformat(),
        "events": [*base.payload["events"], event],
    }
    analyze_incident(payload)
    revision = IncidentRevision(
        incident_id=task.incident_id,
        revision=base.revision + 1,
        title=base.title,
        line_id=base.line_id,
        cutoff=cutoff,
        window_start=base.window_start,
        window_end=base.window_end,
        payload=payload,
        content_digest=incident_digest(payload),
        evidence_card=incident_evidence_card(payload),
    )
    raw = json.dumps(body, sort_keys=True).encode()
    artifact = IncidentSourceArtifact(
        id=artifact_id,
        idempotency_key=f"workflow:{sha256((user.id + ':' + body['idempotency_key']).encode()).hexdigest()}",
        incident_id=task.incident_id,
        revision=revision.revision,
        profile="workflow-v1",
        source_system="workflow-response",
        filename=f"{task.id}.json",
        raw_digest=sha256(raw).hexdigest(),
        raw_bytes=raw,
        preview={"task_id": task.id, "events": [event], "requested_fields": task.requested_fields},
    )
    session.add_all([revision, artifact])
    task.status = "ANSWERED"
    task.response = {
        "evidence_id": evidence_id,
        "revision": revision.revision,
        "summary": summary,
        "occurred_at": occurred.isoformat(),
        "source_ref": source_ref,
        "details": details,
    }
    _activity(
        session,
        task.incident_id,
        user,
        "ANSWERED",
        f"Attached {evidence_id} as evidence revision {revision.revision}: {summary}",
        task,
    )
    return _receipt(session, user, operation, body, task_view(session, task))


def complete_check(
    session: Session, task_id: str, user: Account, body: dict[str, Any]
) -> dict[str, Any]:
    operation = f"complete:{task_id}"
    replay = _replay(session, user, operation, body)
    if replay is not None:
        return replay
    task = _task(session, task_id)
    _assigned(user, task)
    if task.status != "ANSWERED":
        raise ServiceError(
            "CHECK_STATE", "Record the source response before completing the check", 409
        )
    actual = _time(body["actual_completed_at"])
    now = datetime.now(UTC)
    if not task.created_at <= actual <= now:
        raise ServiceError(
            "INVALID_COMPLETION_TIME", "Completion must be between check creation and now", 422
        )
    observed_units, observed_at = body.get("observed_good_units"), body.get("observed_at")
    if (observed_units is None) != (observed_at is None):
        raise ServiceError(
            "OBSERVATION_PAIR_REQUIRED",
            "Observed good units and observation time must be supplied together",
            422,
        )
    if observed_at is not None:
        observed = _time(observed_at)
        if not actual <= observed <= now:
            raise ServiceError(
                "INVALID_OBSERVATION_TIME",
                "Outcome observation must be between action completion and now",
                422,
            )
        observed_at = observed.isoformat()
    task.outcome = {
        "action_taken": _text(body["action_taken"], "Action taken"),
        "actual_completed_at": actual.isoformat(),
        "observed_good_units": observed_units,
        "observed_at": observed_at,
        "assessment": _text(body["assessment"], "Outcome assessment"),
        "remaining_uncertainty": _text(body["remaining_uncertainty"], "Remaining uncertainty"),
    }
    task.status = "COMPLETED"
    _activity(
        session,
        task.incident_id,
        user,
        "COMPLETED",
        f"{task.outcome['action_taken']} Outcome: {task.outcome['assessment']}. Remaining uncertainty: {task.outcome['remaining_uncertainty']}",
        task,
    )
    return _receipt(session, user, operation, body, task_view(session, task))


def resolve_incident(
    session: Session, incident_id: str, user: Account, body: dict[str, Any]
) -> dict[str, Any]:
    operation = f"resolution:{incident_id}"
    replay = _replay(session, user, operation, body)
    if replay is not None:
        return replay
    _lock(session, incident_id)
    latest = _latest(session, incident_id)
    if body["base_revision"] != latest.revision:
        raise ServiceError(
            "STALE_REVISION", "A newer evidence revision exists; reload before resolving", 409
        )
    rationale = _text(body["rationale"], "Resolution rationale")
    tasks = session.scalars(
        select(IncidentCheck).where(IncidentCheck.incident_id == incident_id)
    ).all()
    if body["state"] == "RESOLVED" and (
        not any(task.status == "COMPLETED" and task.outcome for task in tasks)
        or any(task.status not in TERMINAL for task in tasks)
    ):
        raise ServiceError(
            "RESOLUTION_BLOCKED",
            "Resolve only after all checks are terminal and at least one has a recorded outcome",
            409,
        )
    row = session.get(IncidentResolution, incident_id)
    if row is None:
        row = IncidentResolution(
            incident_id=incident_id,
            state=body["state"],
            rationale=rationale,
            resolved_revision=latest.revision,
        )
        session.add(row)
    else:
        row.state, row.rationale, row.resolved_revision = body["state"], rationale, latest.revision
    _activity(session, incident_id, user, body["state"], rationale)
    return _receipt(session, user, operation, body, workflow_view(session, incident_id))
