"""Current-provider evaluation and append-only claim-support annotations."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from .domain.hashing import digest
from .models import Base
from .paid_models import AIRun, SpendEntry


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
    judgment: Mapped[str] = mapped_column(String(32), default="unsupported")
    flags: Mapped[list[str]] = mapped_column(JSONB, default=list)
    reviewer_kind: Mapped[str] = mapped_column(String(32), default="unspecified")
    qualifications: Mapped[str] = mapped_column(Text, default="")
    independent: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


def claim_review_view(review: AIClaimReview) -> dict[str, Any]:
    return {
        "id": review.id, "run_id": review.run_id, "claim_path": review.claim_path,
        "supported": review.supported, "actor": review.user_id,
        "rationale": review.rationale, "output_digest": review.output_digest,
        "created_at": review.created_at.isoformat(),
        "judgment": review.judgment, "flags": review.flags, "reviewer_kind": review.reviewer_kind,
        "qualifications": review.qualifications, "independent": review.independent,
    }


def review_claim(run_id: str, user_id: str, request_key: str, claim_path: str, supported: bool | None, rationale: str, *, owner: bool = False, output_digest: str | None = None, judgment: str | None = None, flags: list[str] | None = None, reviewer_kind: str = 'unspecified', qualifications: str = '', independent: bool = False) -> dict[str, Any]:
    from .semantic_review import save_claim_review
    return save_claim_review(run_id, user_id, request_key, claim_path, supported, rationale, owner=owner, output_digest=output_digest, judgment=judgment, flags=flags, reviewer_kind=reviewer_kind, qualifications=qualifications, independent=independent)


def provider_evaluation(session: Session) -> dict[str, Any]:
    runs = session.scalars(select(AIRun).join(SpendEntry, AIRun.reservation_id == SpendEntry.id).where(SpendEntry.purpose == 'evaluation').order_by(AIRun.created_at)).all()
    completed = [run for run in runs if run.status == 'COMPLETED' and any(attempt.get('provider_verified') is True for attempt in run.attempts)]
    ids = {run.id for run in completed}
    latest = {}
    if ids:
        for review in session.scalars(select(AIClaimReview).where(AIClaimReview.run_id.in_(ids)).order_by(AIClaimReview.created_at, AIClaimReview.id)):
            latest[(review.user_id, review.run_id, review.claim_path)] = review
    human = [review for review in latest.values() if review.reviewer_kind == 'human']
    independent = [review for review in human if review.independent]
    status = 'NOT_EVALUATED' if not runs else 'MEASURED_WITH_DECLARED_INDEPENDENT_REVIEW' if independent else 'MEASURED_WITH_DECLARED_HUMAN_REVIEW' if human else 'MEASURED_WITH_ANNOTATIONS' if latest else 'MEASURED_STRUCTURAL_ONLY' if completed else 'INCOMPLETE_OR_UNVERIFIED'
    timings = sorted(float(run.result['elapsed_seconds']) for run in completed if run.result and isinstance(run.result.get('elapsed_seconds'), (int, float)))
    latency = {'p50_seconds': timings[(len(timings) - 1) // 2], 'p95_seconds': timings[min(len(timings) - 1, int(len(timings) * 0.95))], 'measured_runs':len(timings), 'warm_cold_state':'not_instrumented'} if timings else None
    return {'provider':'openai', 'latency':latency, 'status':status, 'attempted':len(runs), 'completed':len(completed), 'failed':sum(run.status not in {'COMPLETED', 'RUNNING'} for run in runs), 'running':sum(run.status == 'RUNNING' for run in runs), 'unverified_completed':sum(run.status == 'COMPLETED' and run not in completed for run in runs), 'reviewed':len({run_id for _, run_id, _ in latest}), 'reviewed_claims':len(latest), 'supported_claims':sum(review.supported for review in latest.values()), 'human_support_precision':sum(review.supported for review in human) / len(human) if human else None, 'declared_human_reviewed_claims':len(human), 'declared_independent_reviewed_claims':len(independent), 'reviewer_qualifications_verified':False, 'review_policy':'Latest annotation per actor/run/claim; human status and independence are declared, not verified', 'execution_configurations':[{'run_id':run.id, 'configuration':run.configuration, 'status':run.status, 'provider_request_ids':[attempt.get('request_id') for attempt in run.attempts], 'output_digest':digest(run.result.get('output')) if run.result and run.result.get('output') else None} for run in runs]}
