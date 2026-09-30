"""Current-provider evaluation and append-only claim-support annotations."""
from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .db import session_scope
from .domain.hashing import digest
from .models import Base
from .paid_models import AIRun, SpendEntry
from .service import ServiceError
from .spending import lock


class AIClaimReview(Base):
    __tablename__ = 'ai_claim_reviews'
    __table_args__ = (UniqueConstraint('user_id', 'request_key'),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey('accounts.id'))
    request_key: Mapped[str] = mapped_column(String(120))
    run_id: Mapped[str] = mapped_column(ForeignKey('ai_runs.id'), index=True)
    claim_path: Mapped[str] = mapped_column(String(120))
    output_digest: Mapped[str] = mapped_column(String(80))
    supported: Mapped[bool] = mapped_column(Boolean)
    rationale: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


def claim_review_view(review: AIClaimReview) -> dict[str, Any]:
    return {
        "id": review.id, "run_id": review.run_id, "claim_path": review.claim_path,
        "supported": review.supported, "actor": review.user_id,
        "rationale": review.rationale, "output_digest": review.output_digest,
        "created_at": review.created_at.isoformat(),
    }


def review_claim(run_id: str, user_id: str, request_key: str, claim_path: str, supported: bool, rationale: str, *, owner: bool = False) -> dict[str, Any]:
    with session_scope() as session:
        lock(session)
        run = session.get(AIRun, run_id)
        if run is None or (run.user_id != user_id and not owner):
            raise ServiceError('NOT_FOUND', 'AI run not found', 404)
        if run.status != 'COMPLETED' or not run.result or not run.result.get('output'):
            raise ServiceError('NO_VALIDATED_OUTPUT', 'Only returned validated drafts can receive support annotations', 409)
        if not re.fullmatch(r"[a-z_]+(?:\.(?:[a-z_]+|0|[1-9][0-9]*))*", claim_path):
            raise ServiceError("CLAIM_UNKNOWN", "Use a canonical claim path with nonnegative indices", 422)
        output = run.result['output']
        selected: Any = output
        try:
            for part in claim_path.split('.'):
                selected = selected[int(part)] if isinstance(selected, list) else selected[part]
        except (KeyError, ValueError, IndexError, TypeError):
            raise ServiceError('CLAIM_UNKNOWN', 'Claim path does not identify this output', 422) from None
        if not isinstance(selected, dict) or not isinstance(selected.get('text'), str):
            raise ServiceError('CLAIM_UNKNOWN', 'Review a returned claim, not a list or metadata', 422)
        fingerprint = digest(output)
        existing = session.scalar(select(AIClaimReview).where(AIClaimReview.user_id == user_id, AIClaimReview.request_key == request_key))
        if existing:
            if (existing.run_id, existing.claim_path, existing.supported, existing.rationale, existing.output_digest) != (run_id, claim_path, supported, rationale, fingerprint):
                raise ServiceError('IDEMPOTENCY_CONFLICT', 'Review identity already used for another annotation', 409)
            return claim_review_view(existing)
        review = AIClaimReview(user_id=user_id, request_key=request_key, run_id=run_id, claim_path=claim_path, output_digest=fingerprint, supported=supported, rationale=rationale)
        session.add(review)
        session.flush()
        return claim_review_view(review)


def provider_evaluation(session: Session) -> dict[str, Any]:
    runs = session.scalars(select(AIRun).join(SpendEntry, AIRun.reservation_id == SpendEntry.id).where(SpendEntry.purpose == 'evaluation').order_by(AIRun.created_at)).all()
    completed = [run for run in runs if run.status == 'COMPLETED' and any(attempt.get('provider_verified') is True for attempt in run.attempts)]
    ids = {run.id for run in completed}
    latest = {}
    if ids:
        for review in session.scalars(select(AIClaimReview).where(AIClaimReview.run_id.in_(ids)).order_by(AIClaimReview.created_at, AIClaimReview.id)):
            latest[(review.run_id, review.claim_path)] = review
    status = 'NOT_EVALUATED' if not runs else 'MEASURED_WITH_HUMAN_REVIEW' if latest else 'MEASURED_STRUCTURAL_ONLY' if completed else 'INCOMPLETE_OR_UNVERIFIED'
    timings = sorted(float(run.result['elapsed_seconds']) for run in completed if run.result and isinstance(run.result.get('elapsed_seconds'), (int, float)))
    latency = {'p50_seconds': timings[(len(timings) - 1) // 2], 'p95_seconds': timings[min(len(timings) - 1, int(len(timings) * 0.95))], 'measured_runs':len(timings), 'warm_cold_state':'not_instrumented'} if timings else None
    return {'provider':'openai', 'latency':latency, 'status':status, 'attempted':len(runs), 'completed':len(completed), 'failed':sum(run.status not in {'COMPLETED', 'RUNNING'} for run in runs), 'running':sum(run.status == 'RUNNING' for run in runs), 'unverified_completed':sum(run.status == 'COMPLETED' and run not in completed for run in runs), 'reviewed':len({run_id for run_id, _ in latest}), 'reviewed_claims':len(latest), 'supported_claims':sum(review.supported for review in latest.values()), 'human_support_precision':sum(review.supported for review in latest.values()) / len(latest) if latest else None, 'review_policy':'Latest human annotation per run/claim; no manufacturing-expert validation', 'execution_configurations':[{'run_id':run.id, 'configuration':run.configuration, 'status':run.status, 'provider_request_ids':[attempt.get('request_id') for attempt in run.attempts], 'output_digest':digest(run.result.get('output')) if run.result and run.result.get('output') else None} for run in runs]}
