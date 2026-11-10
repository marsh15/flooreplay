"""Read models for the order decision screens.

These compose what the pure engine and the stores already hold into the shapes the screens
render: an order summary, one replayed decision with the facts it cites, the knowledge
timeline and the human records. A read never stores anything: the decision view replays the
snapshot in memory and only *looks up* an evaluation that a person already stored.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from flooreplay.auth import Account
from flooreplay.decisions import service
from flooreplay.decisions import snapshot as snapshots
from flooreplay.decisions.constraints import ConstraintResult
from flooreplay.decisions.facts import OrderRequestPayload, parse_payload
from flooreplay.decisions.gate import GateResult
from flooreplay.decisions.models import DecisionEvaluation, DecisionRecord
from flooreplay.decisions.policy import PolicyDocument, policy_digest
from flooreplay.decisions.recommend import RecommendationView
from flooreplay.decisions.replay import replay
from flooreplay.decisions.types import Fact, FactKind, GateState, Recommendation

TIMELINE_EVENT_LIMIT = 500
"""A timeline is bounded; an order that cites more facts than this shows its newest."""

_SUMMARY_KEYS = ("qty", "issue", "usable_qty", "on_hand", "inbound_qty", "eta", "available_minutes")


class LatestOutcome(BaseModel):
    outcome: Recommendation
    gate_state: GateState
    cutoff: datetime


class OrderSummary(BaseModel):
    order_id: str
    buyer: str | None = None
    style_id: str | None = None
    ship_date: str | None = None
    total_qty: str | None = None
    latest: LatestOutcome | None = None


class PolicyRef(BaseModel):
    digest: str
    label: str
    engine_version: str


class RecordedDecision(BaseModel):
    id: str
    recorded_at: datetime
    reviewer: str
    engine_outcome: Recommendation
    final_outcome: Recommendation
    reason: str
    override: bool


class DecisionView(BaseModel):
    order_id: str
    cutoff: datetime
    settled: bool
    policy: PolicyRef
    snapshot_digest: str
    decision_digest: str
    gate: GateResult
    constraints: list[ConstraintResult]
    recommendation: RecommendationView
    facts: list[Fact]
    records: list[RecordedDecision]


class TimelineEvent(BaseModel):
    known_at: datetime
    fact_id: str
    kind: FactKind
    entity_key: str
    source: str
    summary: str


class Timeline(BaseModel):
    knowledge_times: list[datetime]
    events: list[TimelineEvent]


def _utc(moment: datetime) -> datetime:
    return moment.astimezone(UTC)


def order_summaries(session: Session, workspace_id: str) -> list[OrderSummary]:
    """One summary per order that has an order_request fact, with its newest stored outcome."""
    order_ids = service.list_order_ids(session, workspace_id)
    if not order_ids:
        return []
    snapshot = service.snapshot_at(session, workspace_id, service.db_now(session))
    latest: dict[str, DecisionEvaluation] = {}
    for row in session.scalars(
        select(DecisionEvaluation)
        .where(DecisionEvaluation.workspace_id == workspace_id)
        .order_by(DecisionEvaluation.created_at.desc(), DecisionEvaluation.id.desc())
    ):
        latest.setdefault(row.order_id, row)

    summaries: list[OrderSummary] = []
    for order_id in order_ids:
        found = snapshots.current(snapshot, FactKind.ORDER_REQUEST, service.ORDER_KEY_PREFIX + order_id)
        summary = OrderSummary(order_id=order_id)
        if found.fact is not None:
            parsed = parse_payload(found.fact)
            if isinstance(parsed, OrderRequestPayload):
                summary.buyer = parsed.buyer
                summary.style_id = parsed.style_id
                summary.ship_date = parsed.ship_date.isoformat()
                summary.total_qty = str(sum((Decimal(c.qty_pcs) for c in parsed.colours), Decimal(0)))
        newest = latest.get(order_id)
        if newest is not None:
            summary.latest = LatestOutcome(
                outcome=Recommendation(newest.outcome),
                gate_state=GateState(newest.result["gate"]["state"]),
                cutoff=_utc(newest.cutoff),
            )
        summaries.append(summary)
    return summaries


def _cited_ids(order_id: str, snapshot: snapshots.Snapshot, gate: GateResult, constraints: list[ConstraintResult]) -> set[str]:
    cited: set[str] = set()
    for finding in gate.findings:
        cited.update(finding.fact_ids)
    for result in constraints:
        cited.update(result.fact_ids)
        cited.update(result.consumed_by)
        cited.update(result.pending_review_fact_ids)
    own = service.ORDER_KEY_PREFIX + order_id
    cited.update(fact.id for fact in snapshot.facts if fact.entity_key == own)
    return cited


def _with_history(cited: set[str], known: list[Fact]) -> set[str]:
    """Close a set of fact ids over supersession in both directions, competing branches included."""
    by_id = {fact.id: fact for fact in known}
    shown = {fid for fid in cited if fid in by_id}
    grew = True
    while grew:
        grew = False
        for fact in known:
            linked = (fact.supersedes_id in shown) if fact.supersedes_id else False
            ancestor = any(by_id[fid].supersedes_id == fact.id for fid in shown)
            if fact.id not in shown and (linked or ancestor):
                shown.add(fact.id)
                grew = True
    return shown


def _ordered(order_id: str, facts: list[Fact]) -> list[Fact]:
    own = service.ORDER_KEY_PREFIX + order_id
    return sorted(facts, key=lambda f: (f.entity_key != own, f.known_at, f.id))


def _reviewer(session: Session, actor: str) -> str:
    account = session.get(Account, actor)
    return account.display_name if account is not None and account.display_name else actor


def recorded_decisions(session: Session, workspace_id: str, evaluation_id: str) -> list[RecordedDecision]:
    rows = session.scalars(
        select(DecisionRecord)
        .where(DecisionRecord.workspace_id == workspace_id, DecisionRecord.evaluation_id == evaluation_id)
        .order_by(DecisionRecord.created_at, DecisionRecord.id)
    ).all()
    return [
        RecordedDecision(
            id=row.id,
            recorded_at=_utc(row.created_at),
            reviewer=_reviewer(session, row.actor),
            engine_outcome=Recommendation(row.recommended_outcome),
            final_outcome=Recommendation(row.decision),
            reason=row.reason,
            override=row.override,
        )
        for row in rows
    ]


def decision_view(
    session: Session,
    workspace_id: str,
    order_id: str,
    cutoff: datetime | None,
    policy: PolicyDocument,
) -> DecisionView:
    """Replay one order as known at `cutoff` (default: the newest settled instant)."""
    when = _utc(cutoff) if cutoff is not None else service.latest_settled_instant(session)
    known = service.load_facts(session, workspace_id, known_by=when)
    snapshot = snapshots.snapshot_at(known, when)
    coverage = service.load_coverage(session, workspace_id, when)
    result = replay(snapshot, order_id, policy, coverage)
    shown = _with_history(_cited_ids(order_id, snapshot, result.gate, list(result.constraints)), known)
    stored = service.find_evaluation(session, workspace_id, result, order_id, when)
    return DecisionView(
        order_id=order_id,
        cutoff=when,
        settled=service.is_settled(session, when),
        policy=PolicyRef(digest=policy_digest(policy), label=policy.label, engine_version=policy.engine_version),
        snapshot_digest=result.snapshot_digest,
        decision_digest=result.decision_digest,
        gate=result.gate,
        constraints=list(result.constraints),
        recommendation=result.recommendation,
        facts=_ordered(order_id, [fact for fact in known if fact.id in shown]),
        records=recorded_decisions(session, workspace_id, stored.id) if stored is not None else [],
    )


def _summary(fact: Fact) -> str:
    parts = [f"{fact.kind.value.replace('_', ' ')} {fact.entity_key}"]
    for key in _SUMMARY_KEYS:
        value: Any = fact.payload.get(key)
        if value is None:
            continue
        if isinstance(value, dict) and "value" in value:
            value = f"{value['value']} {value.get('unit', '')}".strip()
        parts.append(f"{key.replace('_', ' ')} {value}")
    if fact.supersedes_id:
        parts.append(f"replaces {fact.supersedes_id}")
    return ", ".join(parts)


def timeline(session: Session, workspace_id: str, order_id: str) -> Timeline:
    """What the system learned about this order, in the order it learned it.

    The facts are the ones a replay at the newest knowledge time cites, plus their supersession
    history. Judging relevance at that instant (not at today's clock) keeps an old order's
    evidence from being dropped just because its exports have since gone stale, and a cutoff
    chosen from `knowledge_times` always shows that fact as known.
    """
    known = service.load_facts(session, workspace_id, known_by=service.latest_settled_instant(session))
    if not known:
        return Timeline(knowledge_times=[], events=[])
    newest = max(fact.known_at for fact in known)
    snapshot = snapshots.snapshot_at(known, newest)
    policy = service.resolve_policy(session, workspace_id, None)
    result = replay(snapshot, order_id, policy, service.load_coverage(session, workspace_id, newest))
    shown = _with_history(_cited_ids(order_id, snapshot, result.gate, list(result.constraints)), known)
    chosen = sorted((f for f in known if f.id in shown), key=lambda f: (f.known_at, f.id))
    chosen = chosen[-TIMELINE_EVENT_LIMIT:]
    return Timeline(
        knowledge_times=sorted({fact.known_at for fact in chosen}),
        events=[
            TimelineEvent(
                known_at=fact.known_at,
                fact_id=fact.id,
                kind=fact.kind,
                entity_key=fact.entity_key,
                source=fact.source.value,
                summary=_summary(fact),
            )
            for fact in chosen
        ],
    )
