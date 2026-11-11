"""Publish a previewed CSV into a private workspace (T16).

The server re-runs the preview before anything is stored, so a caller can only publish what
the server itself would show: a changed file or a changed interpretation answers
PREVIEW_MISMATCH. Publication keeps the raw bytes and their digest in
`decision_source_artifacts`, stamps `known_at` from the database clock, and appends the facts
in the same transaction through `service.append_facts`. Notes are returned as pending
extraction items and never become facts here. No model provider is called.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from flooreplay.decisions import service
from flooreplay.decisions.imports import MAX_BYTES, ImportPreview, preview_import
from flooreplay.decisions.models import DecisionSourceArtifact, FactRow
from flooreplay.decisions.types import FrozenModel
from flooreplay.errors import ServiceError
from flooreplay.workspaces import Workspace, WorkspaceMember

PUBLISH_ROLES = frozenset({"owner", "member"})
MAX_ENCODED_CHARS = -(-MAX_BYTES // 3) * 4
"""Longest base64 text that can decode to MAX_BYTES; checked before decoding."""


class PendingNote(FrozenModel):
    note_id: str
    lot_hint: str | None = None
    text: str
    note_digest: str
    state: Literal["pending_extraction"] = "pending_extraction"


class PublishResult(FrozenModel):
    artifact_id: str
    idempotent_replay: bool
    known_at: datetime
    raw_digest: str
    preview_digest: str
    fact_ids: tuple[str, ...]
    pending_extraction: tuple[PendingNote, ...]


def run_preview(
    raw: bytes,
    *,
    filename: str,
    profile: str,
    column_mapping: dict[str, str],
    as_of: datetime,
    timezone: str,
    units: dict[str, str],
    coverage_qualities: list[str] | None,
) -> ImportPreview:
    """The pure preview. Stores nothing; an unknown profile is a 422."""
    try:
        return preview_import(
            raw,
            filename=filename,
            profile=profile,
            column_mapping=column_mapping,
            as_of=as_of,
            timezone=timezone,
            units=units,
            coverage_qualities=coverage_qualities,
        )
    except ValueError as exc:
        raise ServiceError("INVALID_IMPORT", str(exc), 422) from exc


def pending_notes(preview: ImportPreview) -> tuple[PendingNote, ...]:
    return tuple(
        PendingNote(note_id=n.note_id, lot_hint=n.lot_hint, text=n.text, note_digest=n.note_digest)
        for n in preview.notes
    )


def check_publish_rights(session: Session, *, workspace_id: str, member: WorkspaceMember) -> None:
    """Only a private workspace accepts imports, and only from owner or member roles."""
    workspace = session.get(Workspace, workspace_id)
    if workspace is None:
        raise ServiceError("WORKSPACE_UNKNOWN", "Workspace not found", 404)
    if workspace.visibility != "private":
        raise ServiceError(
            "PRIVATE_IMPORT_REQUIRED", "Imports can only be published into a private workspace", 403
        )
    if member.role not in PUBLISH_ROLES:
        raise ServiceError("MEMBER_REQUIRED", "Only workspace owners and members can publish imports", 403)


def _lock_import_key(session: Session, workspace_id: str, idempotency_key: str) -> None:
    key = f"decision-import:{workspace_id}:{idempotency_key}"
    session.execute(select(func.pg_advisory_xact_lock(func.hashtext(key))))


def _result(
    session: Session,
    workspace_id: str,
    artifact: DecisionSourceArtifact,
    preview: ImportPreview,
    *,
    replay: bool,
) -> PublishResult:
    fact_ids = session.scalars(
        select(FactRow.id)
        .where(FactRow.workspace_id == workspace_id, FactRow.artifact_id == artifact.id)
        .order_by(FactRow.id)
    ).all()
    # append_facts stamps its own clock reading after taking the entity locks, so the facts can
    # be a few milliseconds later than the artifact row. Snapshots use the facts' stamp.
    stamp = session.scalar(
        select(func.min(FactRow.known_at)).where(
            FactRow.workspace_id == workspace_id, FactRow.artifact_id == artifact.id
        )
    )
    return PublishResult(
        artifact_id=artifact.id,
        idempotent_replay=replay,
        known_at=stamp or artifact.known_at,
        raw_digest=artifact.raw_digest,
        preview_digest=artifact.preview_digest,
        fact_ids=tuple(fact_ids),
        pending_extraction=pending_notes(preview),
    )


def publish_import(
    session: Session,
    *,
    workspace_id: str,
    raw: bytes,
    filename: str,
    profile: str,
    column_mapping: dict[str, str],
    as_of: datetime,
    timezone: str,
    units: dict[str, str],
    coverage_qualities: list[str] | None,
    preview_digest: str,
    idempotency_key: str,
) -> PublishResult:
    """Store the raw artifact and its facts in one transaction, or refuse with a stable code.

    Order: lock the idempotency key, re-run the preview, compare digests, replay or conflict on
    the key, refuse blocked previews, then stamp `known_at` and append.
    """
    if "\x00" in idempotency_key:
        raise ServiceError("INVALID_IDEMPOTENCY_KEY", "idempotency key cannot contain NUL bytes", 422)
    _lock_import_key(session, workspace_id, idempotency_key)
    preview = run_preview(
        raw,
        filename=filename,
        profile=profile,
        column_mapping=column_mapping,
        as_of=as_of,
        timezone=timezone,
        units=units,
        coverage_qualities=coverage_qualities,
    )
    if preview.preview_digest != preview_digest:
        raise ServiceError(
            "PREVIEW_MISMATCH", "Source data or interpretation changed since preview", 409
        )
    existing = session.scalar(
        select(DecisionSourceArtifact).where(
            DecisionSourceArtifact.workspace_id == workspace_id,
            DecisionSourceArtifact.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.preview_digest != preview.preview_digest:
            raise ServiceError(
                "IDEMPOTENCY_CONFLICT", "Idempotency key was already used for different content", 409
            )
        return _result(session, workspace_id, existing, preview, replay=True)
    if preview.status != "READY":
        raise ServiceError("IMPORT_BLOCKED", "Fix the blocking problems before publishing", 422)

    now = service.db_now(session)  # server clock; the request never supplies known_at
    if preview.as_of > now:
        raise ServiceError(
            "AS_OF_AFTER_KNOWN_AT",
            "as_of is later than the server clock; declare when the data was known",
            422,
        )
    coverage: dict[str, Any] = (
        preview.coverage.model_dump(mode="json") if preview.coverage is not None else {}
    )
    artifact = DecisionSourceArtifact(
        id=str(uuid4()),
        workspace_id=workspace_id,
        profile=preview.profile.value,
        filename=filename,
        raw_bytes=raw,
        raw_digest=preview.raw_digest,
        as_of=preview.as_of,
        known_at=now,
        coverage=coverage,
        idempotency_key=idempotency_key,
        preview_digest=preview.preview_digest,
    )
    session.add(artifact)
    session.flush()
    stamped = [
        fact.model_copy(update={"known_at": now, "artifact_id": artifact.id})
        for fact in preview.facts
    ]
    service.append_facts(session, stamped, workspace_id=workspace_id)
    return _result(session, workspace_id, artifact, preview, replay=False)
