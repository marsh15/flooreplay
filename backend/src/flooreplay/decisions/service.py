"""Effectful fact store: appends facts and loads them back as pure `Fact` objects.

All decisions about validity, visibility and digests stay in the pure modules
(`facts`, `snapshot`). This layer only adds what needs a database: a per-entity lock,
the full correction graph at write time, and the server clock.
"""

from __future__ import annotations

from collections.abc import Collection
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from flooreplay.decisions import facts as fact_rules
from flooreplay.decisions import snapshot as snapshots
from flooreplay.decisions.models import FactRow
from flooreplay.decisions.types import Fact, FactKind, SourceProfile
from flooreplay.errors import ServiceError

# A caller building a Fact for an untrusted append stamps it with its own "now". We accept
# that as a courtesy but never store it: the server clock wins.
CLIENT_CLOCK_TOLERANCE = timedelta(seconds=60)


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


def _row_to_fact(row: FactRow) -> Fact:
    return Fact(
        id=row.id,
        kind=FactKind(row.kind),
        entity_key=row.entity_key,
        payload=row.payload,
        valid_from=row.valid_from,
        valid_to=row.valid_to,
        known_at=row.known_at,
        supersedes_id=row.supersedes_id,
        source=SourceProfile(row.source),
        artifact_id=row.artifact_id,
    )


def _lock_entity(session: Session, workspace_id: str, kind: str, entity_key: str) -> None:
    key = f"{workspace_id}:{kind}:{entity_key}"
    session.execute(select(func.pg_advisory_xact_lock(func.hashtext(key))))


def _stamp_known_at(fact: Fact, trusted_known_at: datetime | None) -> datetime:
    if trusted_known_at is not None:
        if trusted_known_at.tzinfo is None or trusted_known_at.utcoffset() is None:
            raise ServiceError("KNOWN_AT_INVALID", "trusted_known_at must carry a UTC offset", 422)
        return trusted_known_at
    now = utc_now()
    if abs(fact.known_at - now) > CLIENT_CLOCK_TOLERANCE:
        raise ServiceError(
            "KNOWN_AT_CLIENT_SUPPLIED",
            "known_at is set by the server; only seed and CLI may author it",
            422,
        )
    return now


def append_fact(
    session: Session,
    fact: Fact,
    *,
    workspace_id: str,
    trusted_known_at: datetime | None = None,
) -> FactRow:
    """Validate and append one fact; never modifies an existing row.

    `known_at` is the server clock. Only seed and CLI code may pass `trusted_known_at`
    to author it (the frozen cases need that); it replaces `fact.known_at`. Either way
    `valid_from <= known_at` (no backdating) and the full correction graph of the
    entity, existing facts plus this one, must still validate.
    """
    known_at = _stamp_known_at(fact, trusted_known_at)
    fact = fact.model_copy(update={"known_at": known_at})
    if fact.valid_from > known_at:
        raise ServiceError(
            "BACKDATED",
            f"valid_from {fact.valid_from.isoformat()} is after known_at {known_at.isoformat()}",
            422,
        )
    try:  # after stamping, so the pure rules judge the known_at that will be stored
        fact = fact_rules.validate_fact(fact)
    except fact_rules.FactValidationError as exc:
        raise ServiceError("FACT_INVALID", str(exc), 422) from exc

    _lock_entity(session, workspace_id, fact.kind.value, fact.entity_key)
    entity_rows = session.scalars(
        select(FactRow).where(
            FactRow.workspace_id == workspace_id,
            FactRow.kind == fact.kind.value,
            FactRow.entity_key == fact.entity_key,
        )
    ).all()
    graph = [_row_to_fact(row) for row in entity_rows]
    if any(existing.id == fact.id for existing in graph):
        raise ServiceError("FACT_ID_TAKEN", f"fact {fact.id} already exists", 409)
    if fact.supersedes_id is not None and all(f.id != fact.supersedes_id for f in graph):
        # Pull the target in even if it is another kind or entity, so the pure check can
        # name the real problem (kind or entity mismatch) instead of "unknown target".
        target = session.scalar(
            select(FactRow).where(
                FactRow.workspace_id == workspace_id, FactRow.id == fact.supersedes_id
            )
        )
        if target is not None:
            graph.append(_row_to_fact(target))
    try:
        fact_rules.validate_corrections([*graph, fact])
    except fact_rules.CorrectionError as exc:
        raise ServiceError("CORRECTION_INVALID", f"{exc.code.value}: {exc}", 422) from exc

    dumped = fact.model_dump(mode="json")
    row = FactRow(
        id=fact.id,
        workspace_id=workspace_id,
        kind=fact.kind.value,
        entity_key=fact.entity_key,
        payload=dumped["payload"],
        valid_from=fact.valid_from,
        valid_to=fact.valid_to,
        known_at=known_at,
        supersedes_id=fact.supersedes_id,
        source=fact.source.value,
        artifact_id=fact.artifact_id,
        semantic_digest=fact_rules.semantic_digest(fact),
    )
    try:
        with session.begin_nested():
            session.add(row)
            session.flush()
    except IntegrityError as exc:
        # Ids are global, so another workspace may own this one; do not say which.
        raise ServiceError("FACT_REJECTED", "fact violates a stored-data constraint", 409) from exc
    return row


def load_facts(
    session: Session,
    workspace_id: str,
    *,
    kinds: Collection[FactKind] | None = None,
    entity_keys: Collection[str] | None = None,
    known_by: datetime | None = None,
) -> list[Fact]:
    """The workspace's facts as pure `Fact`s, ordered by (known_at, id)."""
    query = select(FactRow).where(FactRow.workspace_id == workspace_id)
    if kinds is not None:
        query = query.where(FactRow.kind.in_([k.value for k in kinds]))
    if entity_keys is not None:
        query = query.where(FactRow.entity_key.in_(list(entity_keys)))
    if known_by is not None:
        query = query.where(FactRow.known_at <= known_by)
    rows = session.scalars(query.order_by(FactRow.known_at, FactRow.id)).all()
    return [_row_to_fact(row) for row in rows]


def snapshot_at(session: Session, workspace_id: str, cutoff: datetime) -> snapshots.Snapshot:
    """The as-known snapshot at `cutoff`. Facts known after it are never even loaded.

    Anything a visible fact supersedes was known strictly earlier, so `known_by=cutoff`
    already contains every row the pure `snapshot_at` needs.
    """
    return snapshots.snapshot_at(load_facts(session, workspace_id, known_by=cutoff), cutoff)
