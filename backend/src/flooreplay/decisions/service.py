"""Effectful fact store: appends facts and loads them back as pure `Fact` objects.

All decisions about validity, visibility and digests stay in the pure modules
(`facts`, `snapshot`). This layer only adds what needs a database: per-entity locks,
the full correction graph at write time, and the database clock.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from datetime import datetime, timedelta

import psycopg.errors
from sqlalchemy import func, select, text
from sqlalchemy.exc import DataError, DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from flooreplay.decisions import facts as fact_rules
from flooreplay.decisions import snapshot as snapshots
from flooreplay.decisions.models import DecisionSourceArtifact, FactRow
from flooreplay.decisions.types import Fact, FactKind, SourceProfile
from flooreplay.errors import ServiceError
from flooreplay.workspaces import allowed_workspaces

# A caller building a Fact for an untrusted append stamps it with its own "now". We accept
# that as a courtesy but never store it: the database clock wins.
CLIENT_CLOCK_TOLERANCE = timedelta(seconds=60)

SETTLE_HORIZON = timedelta(seconds=120)
"""How long a fresh `known_at` stays provisional.

`known_at` is stamped under the entity lock, but a transaction can still commit well after
it was stamped, so a fact may become visible with a `known_at` in the past. A snapshot whose
cutoff is later than `db_now - SETTLE_HORIZON` is therefore provisional: late commits may
still land before it. Anything that stores an evaluation must require `is_settled` first.
"""

LOCK_NAMESPACE = "decision-facts:"


def db_now(session: Session) -> datetime:
    """The database's wall clock (not the transaction start), so stamps follow lock order."""
    return session.execute(select(func.clock_timestamp())).scalar_one()


def is_settled(session: Session, cutoff: datetime) -> bool:
    """True when `cutoff` is old enough that no in-flight append can still land before it."""
    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
        raise ServiceError("CUTOFF_INVALID", "cutoff must carry a UTC offset", 422)
    return cutoff <= db_now(session) - SETTLE_HORIZON


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


def _take_locks(session: Session, workspace_id: str, facts: Sequence[Fact]) -> None:
    """Lock every touched entity, in ascending hash order, so batches cannot deadlock."""
    keys = {f"{LOCK_NAMESPACE}{workspace_id}:{f.kind.value}:{f.entity_key}" for f in facts}
    hashes: list[int] = sorted({session.scalar(select(func.hashtext(key))) or 0 for key in keys})
    for value in hashes:
        session.execute(select(func.pg_advisory_xact_lock(value)))


def _check_nul(fact: Fact) -> None:
    for value in (fact.id, fact.entity_key, fact.supersedes_id, fact.artifact_id):
        if value is not None and "\x00" in value:
            raise ServiceError("FACT_INVALID", "NUL characters are not allowed in text", 422)


def _require_read_committed(session: Session) -> None:
    # The entity lock plus a fresh read of the entity's facts is only sound when each
    # statement sees everything committed before it. Stronger isolation would hide rows.
    level: str | None = session.scalar(text("SHOW transaction_isolation"))
    if level != "read committed":
        raise ServiceError(
            "ISOLATION_UNSUPPORTED", f"append_facts needs READ COMMITTED, got {level}", 500
        )


def _stamp(fact: Fact, now: datetime, trusted_known_at: datetime | None) -> datetime:
    if trusted_known_at is not None:
        return trusted_known_at
    if abs(fact.known_at - now) > CLIENT_CLOCK_TOLERANCE:
        raise ServiceError(
            "KNOWN_AT_CLIENT_SUPPLIED",
            "known_at is set by the server; only seed and CLI may author it",
            422,
        )
    return now


def translate_db_error(exc: DBAPIError) -> ServiceError | None:
    """The ServiceError for a database failure the caller can act on, else None."""
    if isinstance(exc.orig, psycopg.errors.DeadlockDetected | psycopg.errors.SerializationFailure):
        return ServiceError(
            "RETRY", "Concurrent write conflict; retry the request", 409, retry_after=1
        )
    if isinstance(exc, DataError):
        return ServiceError("FACT_INVALID", "fact contains a value the database cannot store", 422)
    return None


def append_fact(
    session: Session,
    fact: Fact,
    *,
    workspace_id: str,
    trusted_known_at: datetime | None = None,
) -> FactRow:
    """Append one fact; see `append_facts`."""
    return append_facts(
        session, [fact], workspace_id=workspace_id, trusted_known_at=trusted_known_at
    )[0]


def append_facts(
    session: Session,
    facts: Sequence[Fact],
    *,
    workspace_id: str,
    trusted_known_at: datetime | None = None,
) -> list[FactRow]:
    """Validate and append facts as one all-or-nothing batch; never modifies an existing row.

    Every touched entity is locked first, in a global order, then one `known_at` is stamped
    from the database clock for the whole batch. Corrections must therefore go in a later call
    than the fact they replace (they need a strictly later `known_at`).

    Only seed and CLI code may pass `trusted_known_at` to author `known_at` (the frozen cases
    need that). It is refused whenever a workspace scope is active, i.e. on any HTTP path.
    Either way `valid_from <= known_at` (no backdating), a referenced artifact must be in the
    same workspace, and the full correction graph of each entity (existing facts plus the new
    one) must still validate.
    """
    if not facts:
        return []
    if trusted_known_at is not None:
        if allowed_workspaces.get() is not None:
            raise ServiceError(
                "TRUSTED_TIME_FORBIDDEN", "known_at cannot be authored in a workspace scope", 403
            )
        if trusted_known_at.tzinfo is None or trusted_known_at.utcoffset() is None:
            raise ServiceError("KNOWN_AT_INVALID", "trusted_known_at must carry a UTC offset", 422)
    for fact in facts:
        _check_nul(fact)
    try:
        _require_read_committed(session)
        _take_locks(session, workspace_id, facts)
        now = db_now(session)  # after the locks: stamps follow lock order, not arrival order
        with session.begin_nested():  # all or nothing, without poisoning the caller's session
            return [
                _append_one(session, fact, workspace_id, _stamp(fact, now, trusted_known_at))
                for fact in facts
            ]
    except DBAPIError as exc:
        translated = translate_db_error(exc)
        if translated is None:
            raise
        raise translated from exc


def _append_one(session: Session, fact: Fact, workspace_id: str, known_at: datetime) -> FactRow:
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

    if session.scalar(
        select(FactRow.id).where(FactRow.workspace_id == workspace_id, FactRow.id == fact.id)
    ):
        raise ServiceError("FACT_ID_TAKEN", f"fact {fact.id} already exists", 409)
    if fact.artifact_id is not None and not session.scalar(
        select(DecisionSourceArtifact.id).where(
            DecisionSourceArtifact.workspace_id == workspace_id,
            DecisionSourceArtifact.id == fact.artifact_id,
        )
    ):
        raise ServiceError(
            "ARTIFACT_UNKNOWN", f"artifact {fact.artifact_id} not found in this workspace", 422
        )

    entity_rows = session.scalars(
        select(FactRow).where(
            FactRow.workspace_id == workspace_id,
            FactRow.kind == fact.kind.value,
            FactRow.entity_key == fact.entity_key,
        )
    ).all()
    graph = [_row_to_fact(row) for row in entity_rows]
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
    already contains every row the pure `snapshot_at` needs. Use `is_settled` before treating
    the result as final: a cutoff inside `SETTLE_HORIZON` of now is provisional.
    """
    return snapshots.snapshot_at(load_facts(session, workspace_id, known_by=cutoff), cutoff)
