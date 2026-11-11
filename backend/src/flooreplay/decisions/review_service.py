"""Review queue (T20): human resolution of failed extraction fields and NEEDS_REVIEW evaluations.

An item is created once per source and field, and never changes. Its state is derived from its
event log: assignment events, then at most one decision. A decision either creates no fact
(CONFIRMED of a missing field, REJECTED), or appends a NEW fact through `service.append_fact`
with origin `human_review` (CONFIRMED of a failed field, CORRECTED).

A human fact must concern the item's own entity, and an attested value must match the fact it
becomes. A prior fact has at most one live successor, enforced under an advisory lock. The claimed
value stays readable on the item forever.

Replay and snapshot code must not import this module. Only the API and extraction flows do.
"""

from __future__ import annotations

import unicodedata
import uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from flooreplay.decisions import facts as fact_rules
from flooreplay.decisions import service
from flooreplay.decisions.models import (
    DecisionEvaluation,
    FactRow,
    NoteExtraction,
    ReviewEvent,
    ReviewItem,
)
from flooreplay.decisions.types import Fact, FactKind, Recommendation, SourceProfile
from flooreplay.errors import ServiceError
from flooreplay.workspaces import WorkspaceMember

ITEM_STATES = ("OPEN", "ASSIGNED", "CONFIRMED", "CORRECTED", "REJECTED")
DECISION_KINDS = frozenset({"CONFIRMED", "CORRECTED", "REJECTED"})
HUMAN_ORIGIN = "human_review"
EVALUATION_FIELD = "outcome"
OWNER_ROLE = "owner"
NOTE_LIMIT = 2000
VALUE_LIMIT = 500
LOT_PREFIX = "lot:"
ORDER_PREFIX = "order:"


class FactDraft(BaseModel):
    """A human-supplied fact. `origin`, `review_state` and `extraction_id` are set by the server."""

    model_config = ConfigDict(extra="forbid")

    kind: FactKind
    entity_key: str = Field(min_length=1, max_length=200)
    payload: dict[str, Any]
    supersedes_id: str | None = Field(default=None, min_length=1, max_length=200)


class EvidenceSpan(BaseModel):
    start: int
    end: int
    text: str


class ReviewEventView(BaseModel):
    id: str
    kind: str
    actor: str
    assignee_id: str | None
    note: str
    corrected_value: Any
    resulting_fact_id: str | None
    created_at: datetime


class ReviewItemView(BaseModel):
    id: str
    source_kind: str
    extraction_id: str | None
    evaluation_id: str | None
    field: str
    field_status: str
    check_codes: list[str]
    claimed_value: Any
    evidence_span: EvidenceSpan | None
    entity_key: str | None
    state: str
    assignee_id: str | None
    resulting_fact_id: str | None
    created_at: datetime


class ReviewItemDetail(BaseModel):
    item: ReviewItemView
    events: list[ReviewEventView]


class SyncResult(BaseModel):
    extraction_items_created: int
    evaluation_items_created: int


def _events_for(session: Session, workspace_id: str, item_ids: list[str] | None = None) -> dict[str, list[ReviewEvent]]:
    statement = select(ReviewEvent).where(ReviewEvent.workspace_id == workspace_id)
    if item_ids is not None:
        statement = statement.where(ReviewEvent.item_id.in_(item_ids))
    grouped: dict[str, list[ReviewEvent]] = {}
    for event in session.execute(statement.order_by(ReviewEvent.seq)).scalars():
        grouped.setdefault(event.item_id, []).append(event)
    return grouped


def _derive(events: list[ReviewEvent]) -> tuple[str, str | None, str | None]:
    """(state, assignee, resulting fact) from the event log. The latest event decides."""
    assignee: str | None = None
    decision: ReviewEvent | None = None
    for event in events:
        if event.kind == "ASSIGNED":
            assignee = event.assignee_id
        elif event.kind == "UNASSIGNED":
            assignee = None
        elif event.kind in DECISION_KINDS:
            decision = event
    if decision is not None:
        return decision.kind, assignee, decision.resulting_fact_id
    return ("ASSIGNED" if assignee else "OPEN"), assignee, None


def _view(item: ReviewItem, events: list[ReviewEvent]) -> ReviewItemView:
    state, assignee, resulting = _derive(events)
    span = item.evidence_span
    return ReviewItemView(
        id=item.id,
        source_kind=item.source_kind,
        extraction_id=item.extraction_id,
        evaluation_id=item.evaluation_id,
        field=item.field_name,
        field_status=item.field_status,
        check_codes=list(item.check_codes),
        claimed_value=item.claimed_value,
        evidence_span=None if span is None else EvidenceSpan(**span),
        entity_key=item.entity_key,
        state=state,
        assignee_id=assignee,
        resulting_fact_id=resulting,
        created_at=item.created_at,
    )


def _event_view(event: ReviewEvent) -> ReviewEventView:
    return ReviewEventView(
        id=event.id,
        kind=event.kind,
        actor=event.actor,
        assignee_id=event.assignee_id,
        note=event.note,
        corrected_value=event.corrected_value,
        resulting_fact_id=event.resulting_fact_id,
        created_at=event.created_at,
    )


def _insert_item(
    session: Session,
    workspace_id: str,
    *,
    source_kind: str,
    source_ref: str,
    field_name: str,
    field_status: str,
    check_codes: list[str],
    claimed_value: Any,
    evidence_span: dict[str, Any] | None,
    entity_key: str | None,
    extraction_id: str | None,
    evaluation_id: str | None,
) -> tuple[ReviewItem, bool]:
    """Insert once per (source, field). Returns the item and whether this call created it."""
    inserted = session.execute(
        pg_insert(ReviewItem)
        .values(
            workspace_id=workspace_id,
            id=str(uuid.uuid4()),
            source_kind=source_kind,
            extraction_id=extraction_id,
            evaluation_id=evaluation_id,
            field_name=field_name,
            field_status=field_status,
            check_codes=check_codes,
            claimed_value=claimed_value,
            evidence_span=evidence_span,
            entity_key=entity_key,
            created_at=service.db_now(session),
        )
        .on_conflict_do_nothing()
        .returning(ReviewItem.id)
    ).scalar_one_or_none()
    row = session.execute(
        select(ReviewItem).where(
            ReviewItem.workspace_id == workspace_id,
            ReviewItem.source_kind == source_kind,
            func.coalesce(ReviewItem.extraction_id, ReviewItem.evaluation_id) == source_ref,
            ReviewItem.field_name == field_name,
        )
    ).scalar_one()
    return row, inserted is not None


def _extraction_entity(checks: dict[str, Any]) -> str | None:
    """`lot:<id>` when the lot was checked and passed; otherwise the item cannot bind a fact."""
    for field in checks["fields"]:
        if field["field"] == "lot_id" and field["status"] == "passed" and field["value"]:
            return LOT_PREFIX + str(field["value"])
    return None


def _enqueue_extraction(session: Session, workspace_id: str, row: NoteExtraction) -> list[tuple[ReviewItem, bool]]:
    checks: dict[str, Any] = row.checks or {}
    if row.status != "COMPLETED" or not checks:
        return []
    statuses = {field["field"]: field["status"] for field in checks["fields"]}
    spans = {field["field"]: field["span"] for field in checks["fields"]}
    signal: dict[str, Any] = row.signal or {}
    entity = _extraction_entity(checks)
    out: list[tuple[ReviewItem, bool]] = []
    for name in checks["failed_fields"]:
        codes = sorted(
            {result["code"] for result in checks["results"] if result["field"] == name and result["code"] != "ok"}
        )
        claimed = signal.get(name)
        out.append(
            _insert_item(
                session,
                workspace_id,
                source_kind="EXTRACTION_FIELD",
                source_ref=row.id,
                field_name=name,
                field_status=statuses[name],
                check_codes=codes,
                claimed_value=None if claimed is None else claimed.get("value"),
                evidence_span=spans.get(name),
                entity_key=entity,
                extraction_id=row.id,
                evaluation_id=None,
            )
        )
    return out


def _enqueue_evaluation(session: Session, workspace_id: str, row: DecisionEvaluation) -> tuple[ReviewItem, bool]:
    return _insert_item(
        session,
        workspace_id,
        source_kind="EVALUATION",
        source_ref=row.id,
        field_name=EVALUATION_FIELD,
        field_status="needs_review",
        check_codes=[],
        claimed_value=row.outcome,
        evidence_span=None,
        entity_key=ORDER_PREFIX + row.order_id,
        extraction_id=None,
        evaluation_id=row.id,
    )


def enqueue_from_extraction(session: Session, workspace_id: str, extraction_id: str) -> list[ReviewItem]:
    """One item per field the checks did not pass. Idempotent; a clean extraction adds nothing."""
    row = session.get(NoteExtraction, (workspace_id, extraction_id))
    if row is None:
        raise ServiceError("EXTRACTION_UNKNOWN", "Extraction not found", 404)
    return [item for item, _ in _enqueue_extraction(session, workspace_id, row)]


def enqueue_needs_review(session: Session, workspace_id: str, evaluation_id: str) -> ReviewItem:
    """The single item for an evaluation whose outcome is NEEDS_REVIEW. Idempotent."""
    row = session.get(DecisionEvaluation, (workspace_id, evaluation_id))
    if row is None:
        raise ServiceError("EVALUATION_UNKNOWN", "Evaluation not found", 404)
    if row.outcome != Recommendation.NEEDS_REVIEW:
        raise ServiceError("EVALUATION_NOT_NEEDS_REVIEW", "Evaluation outcome is not NEEDS_REVIEW", 422)
    return _enqueue_evaluation(session, workspace_id, row)[0]


def sync_queue(session: Session, workspace_id: str) -> SyncResult:
    """Bring the queue up to date with stored extractions and NEEDS_REVIEW evaluations.

    Idempotent: a second call creates nothing. Only creation counts are returned.
    """
    extractions = session.execute(
        select(NoteExtraction).where(NoteExtraction.workspace_id == workspace_id, NoteExtraction.status == "COMPLETED")
    ).scalars().all()
    extraction_created = 0
    for extraction in extractions:
        extraction_created += sum(1 for _, created in _enqueue_extraction(session, workspace_id, extraction) if created)
    evaluations = session.execute(
        select(DecisionEvaluation).where(
            DecisionEvaluation.workspace_id == workspace_id,
            DecisionEvaluation.outcome == Recommendation.NEEDS_REVIEW.value,
        )
    ).scalars().all()
    evaluation_created = sum(1 for evaluation in evaluations if _enqueue_evaluation(session, workspace_id, evaluation)[1])
    return SyncResult(extraction_items_created=extraction_created, evaluation_items_created=evaluation_created)


def list_items(
    session: Session,
    workspace_id: str,
    *,
    state: str | None = None,
    assignee: str | None = None,
) -> list[ReviewItemView]:
    items = list(
        session.execute(
            select(ReviewItem)
            .where(ReviewItem.workspace_id == workspace_id)
            .order_by(ReviewItem.created_at, ReviewItem.id)
        ).scalars()
    )
    events = _events_for(session, workspace_id)
    views = [_view(item, events.get(item.id, [])) for item in items]
    if state is not None:
        views = [view for view in views if view.state == state]
    if assignee is not None:
        views = [view for view in views if view.assignee_id == assignee]
    return views


def get_item(session: Session, workspace_id: str, item_id: str) -> ReviewItemDetail:
    item = _load(session, workspace_id, item_id)
    events = _events_for(session, workspace_id, [item_id]).get(item_id, [])
    return ReviewItemDetail(item=_view(item, events), events=[_event_view(e) for e in events])


def _load(session: Session, workspace_id: str, item_id: str) -> ReviewItem:
    row = session.execute(
        select(ReviewItem).where(ReviewItem.workspace_id == workspace_id, ReviewItem.id == item_id)
    ).scalar_one_or_none()
    if row is None:
        raise ServiceError("REVIEW_ITEM_UNKNOWN", "Review item not found", 404)
    return row


def _locked(session: Session, workspace_id: str, item_id: str) -> ReviewItem:
    """Serialises decisions on one item. Taking a row lock does not fire the append-only triggers."""
    row = session.execute(
        select(ReviewItem)
        .where(ReviewItem.workspace_id == workspace_id, ReviewItem.id == item_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if row is None:
        raise ServiceError("REVIEW_ITEM_UNKNOWN", "Review item not found", 404)
    return row


def _append_event(
    session: Session,
    workspace_id: str,
    item_id: str,
    kind: str,
    actor: str,
    *,
    assignee_id: str | None = None,
    note: str = "",
    corrected_value: Any = None,
    resulting_fact_id: str | None = None,
) -> ReviewEvent:
    event = ReviewEvent(
        workspace_id=workspace_id,
        id=str(uuid.uuid4()),
        item_id=item_id,
        kind=kind,
        actor=actor,
        assignee_id=assignee_id,
        note=note,
        corrected_value=corrected_value,
        resulting_fact_id=resulting_fact_id,
        created_at=service.db_now(session),
    )
    session.add(event)
    session.flush()
    return event


def _require_undecided(events: list[ReviewEvent]) -> None:
    if any(event.kind in DECISION_KINDS for event in events):
        raise ServiceError("REVIEW_ALREADY_DECIDED", "This item already has a final decision", 409)


def _is_owner(session: Session, workspace_id: str, actor_id: str) -> bool:
    member = session.get(WorkspaceMember, (workspace_id, actor_id))
    return member is not None and member.role == OWNER_ROLE


def _require_actor(session: Session, workspace_id: str, actor_id: str, events: list[ReviewEvent]) -> None:
    """Only the current assignee, or a workspace owner, may decide."""
    _, assignee, _ = _derive(events)
    if assignee != actor_id and not _is_owner(session, workspace_id, actor_id):
        raise ServiceError(
            "REVIEW_ASSIGNEE_REQUIRED", "Only the assignee or a workspace owner can decide this item", 403
        )


def _validate_text(value: str, label: str, limit: int) -> None:
    """Runs before any database access: NUL is not storable in Postgres text, and sizes are capped."""
    if "\x00" in value:
        raise ServiceError("NUL_NOT_ALLOWED", f"{label} must not contain NUL characters", 422)
    if len(value) > limit:
        raise ServiceError("TEXT_TOO_LONG", f"{label} is limited to {limit} characters", 422)


def _begin_decision(
    session: Session, workspace_id: str, item_id: str, actor_id: str, note: str
) -> tuple[ReviewItem, list[ReviewEvent]]:
    item = _locked(session, workspace_id, item_id)
    events = _events_for(session, workspace_id, [item_id]).get(item_id, [])
    _require_undecided(events)
    _require_actor(session, workspace_id, actor_id, events)
    if not note.strip():
        raise ServiceError("NOTE_REQUIRED", "A written note is required for this decision", 422)
    return item, events


def _require_value(value: str | None) -> str:
    if value is None or not value.strip():
        raise ServiceError("VALUE_REQUIRED", "The value this decision records is required", 422)
    return value


def _check_binding(session: Session, workspace_id: str, item: ReviewItem, draft: FactDraft) -> FactRow | None:
    """The fact must concern the item's own entity, and any superseded fact must be that same entity."""
    if item.entity_key is None:
        raise ServiceError("ENTITY_UNBOUND", "This item has no checked entity to bind a fact to", 422)
    if draft.entity_key != item.entity_key:
        raise ServiceError("ENTITY_MISMATCH", "The fact must concern this item's own entity", 422)
    if draft.supersedes_id is None:
        return None
    target = session.get(FactRow, (workspace_id, draft.supersedes_id))
    if target is None:
        raise ServiceError("FACT_UNKNOWN", "supersedes_id is not a fact in this workspace", 404)
    if target.entity_key != draft.entity_key or target.kind != draft.kind.value:
        raise ServiceError("SUPERSEDES_MISMATCH", "supersedes_id must name a fact of the same kind and entity", 422)
    return target


def _nfc(text_value: str) -> str:
    return unicodedata.normalize("NFC", text_value)


def _check_attested(session: Session, workspace_id: str, item: ReviewItem, draft: FactDraft, value: str) -> None:
    """The attested value must equal what the fact says. Numbers compare as decimals, text exactly (NFC)."""
    mismatch = ServiceError("VALUE_FACT_MISMATCH", "The attested value does not match the fact", 422)
    if item.field_name == "qty":
        claimed = draft.payload.get("qty")
        if not isinstance(claimed, dict):
            raise mismatch
        try:
            attested_number = Decimal(value.strip())
            fact_number = Decimal(str(claimed.get("value")))
        except (InvalidOperation, ValueError) as exc:
            raise mismatch from exc
        if not (attested_number.is_finite() and fact_number.is_finite()) or attested_number != fact_number:
            raise mismatch
        if item.extraction_id is not None:
            extraction = session.get(NoteExtraction, (workspace_id, item.extraction_id))
            claimed_unit = ((extraction.signal or {}).get("unit") or {}).get("value") if extraction else None
            if claimed_unit is not None and claimed.get("unit") != claimed_unit:
                raise mismatch
        return
    if item.field_name == "lot_id":
        expected: Any = draft.entity_key.removeprefix(LOT_PREFIX)
    else:
        expected = draft.payload.get(item.field_name)
    if expected is None or isinstance(expected, dict | list):
        raise mismatch
    if _nfc(value) != _nfc(str(expected)):
        raise mismatch


def _human_fact(
    session: Session,
    workspace_id: str,
    item: ReviewItem,
    draft: FactDraft,
    review_state: str,
    value: str,
) -> FactRow:
    """Append the human fact. Origin, review state and provenance are set here, never by the caller."""
    target = _check_binding(session, workspace_id, item, draft)
    _check_attested(session, workspace_id, item, draft, value)
    # Forks: one advisory lock per workspace and entity serialises successors of the same fact.
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"review-fact:{workspace_id}:{draft.entity_key}"},
    )
    if target is not None and session.scalar(
        select(FactRow.id).where(FactRow.workspace_id == workspace_id, FactRow.supersedes_id == target.id)
    ) is not None:
        raise ServiceError("FACT_ALREADY_SUPERSEDED", "That fact already has a live successor", 409)
    fields = fact_rules.KIND_REGISTRY[draft.kind].payload_model.model_fields
    payload = dict(draft.payload)
    if "origin" in fields:
        payload["origin"] = HUMAN_ORIGIN
    if "extraction_id" in fields:
        payload["extraction_id"] = item.extraction_id
    if "review_state" in fields:
        payload["review_state"] = review_state
    now = service.db_now(session)
    # A correction fixes the same observation, so it keeps the valid time it supersedes.
    valid_from = now if target is None else target.valid_from
    valid_to = None if target is None else target.valid_to
    try:
        fact = Fact(
            id=f"review-{item.id}",
            kind=draft.kind,
            entity_key=draft.entity_key,
            payload=payload,
            valid_from=valid_from,
            valid_to=valid_to,
            known_at=now,
            supersedes_id=draft.supersedes_id,
            source=SourceProfile.REVIEW_QUEUE,
            artifact_id=None,
        )
    except ValueError as exc:
        raise ServiceError("FACT_INVALID", str(exc), 422) from exc
    return service.append_fact(session, fact, workspace_id=workspace_id)


def assign(session: Session, workspace_id: str, item_id: str, actor_id: str, assignee_id: str | None) -> ReviewItemView:
    """Assign, reassign or clear an undecided item.

    Owners may do anything. The current assignee may reassign or clear. Any other member may only
    take an unassigned item for themselves.
    """
    item = _locked(session, workspace_id, item_id)
    events = _events_for(session, workspace_id, [item_id]).get(item_id, [])
    _require_undecided(events)
    _, current, _ = _derive(events)
    owner = _is_owner(session, workspace_id, actor_id)
    if assignee_id is None:
        if not (owner or current == actor_id):
            raise ServiceError("REVIEW_ASSIGNMENT_FORBIDDEN", "Only the owner or the assignee can clear this item", 403)
        _append_event(session, workspace_id, item.id, "UNASSIGNED", actor_id)
    else:
        if session.get(WorkspaceMember, (workspace_id, assignee_id)) is None:
            raise ServiceError("ASSIGNEE_NOT_MEMBER", "Assignee must be a member of this workspace", 422)
        allowed = owner or current == actor_id or (current is None and assignee_id == actor_id)
        if not allowed:
            raise ServiceError(
                "REVIEW_ASSIGNMENT_FORBIDDEN",
                "Members may only take an unassigned item for themselves",
                403,
            )
        _append_event(session, workspace_id, item.id, "ASSIGNED", actor_id, assignee_id=assignee_id)
    return get_item(session, workspace_id, item_id).item


def confirm(
    session: Session,
    workspace_id: str,
    item_id: str,
    actor_id: str,
    *,
    note: str,
    value: str | None = None,
    fact: FactDraft | None = None,
) -> ReviewItemView:
    """Accept the field as the human sees it.

    A missing field is confirmed as absent: no value, no fact. A FAILED field can only be
    confirmed by attesting a value, with a fact that records it as human_review.
    """
    _validate_text(note, "note", NOTE_LIMIT)
    if value is not None:
        _validate_text(value, "value", VALUE_LIMIT)
    item, _ = _begin_decision(session, workspace_id, item_id, actor_id, note)
    if item.field_status == "failed":
        attested = _require_value(value)
        if fact is None:
            raise ServiceError("FACT_REQUIRED", "Attesting a failed field requires the fact it becomes", 422)
        row = _human_fact(session, workspace_id, item, fact, "confirmed", attested)
        _append_event(
            session, workspace_id, item.id, "CONFIRMED", actor_id,
            note=note, corrected_value=attested, resulting_fact_id=row.id,
        )
    else:
        if value is not None or fact is not None:
            raise ServiceError("CONFIRM_TAKES_NO_VALUE", "Confirming a missing field records no value or fact", 422)
        _append_event(session, workspace_id, item.id, "CONFIRMED", actor_id, note=note)
    return get_item(session, workspace_id, item_id).item


def correct(
    session: Session,
    workspace_id: str,
    item_id: str,
    actor_id: str,
    *,
    note: str,
    value: str | None,
    fact: FactDraft | None,
) -> ReviewItemView:
    """Record a corrected value as a NEW fact. The original claim is never overwritten."""
    _validate_text(note, "note", NOTE_LIMIT)
    if value is not None:
        _validate_text(value, "value", VALUE_LIMIT)
    item, _ = _begin_decision(session, workspace_id, item_id, actor_id, note)
    corrected = _require_value(value)
    if fact is None:
        raise ServiceError("FACT_REQUIRED", "A correction must state the fact it becomes", 422)
    row = _human_fact(session, workspace_id, item, fact, "corrected", corrected)
    _append_event(
        session, workspace_id, item.id, "CORRECTED", actor_id,
        note=note, corrected_value=corrected, resulting_fact_id=row.id,
    )
    return get_item(session, workspace_id, item_id).item


def reject(session: Session, workspace_id: str, item_id: str, actor_id: str, *, note: str) -> ReviewItemView:
    """Close the item without a fact. The claimed value stays readable."""
    _validate_text(note, "note", NOTE_LIMIT)
    item, _ = _begin_decision(session, workspace_id, item_id, actor_id, note)
    _append_event(session, workspace_id, item.id, "REJECTED", actor_id, note=note)
    return get_item(session, workspace_id, item_id).item
