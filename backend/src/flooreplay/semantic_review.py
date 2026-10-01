"""Deliberately shared, immutable drafts and declared semantic review evidence."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from .ai_evaluation import AIClaimReview, claim_review_view
from .db import session_scope
from .domain.hashing import digest
from .models import Base
from .paid_models import AIRun
from .service import ServiceError
from .spending import lock

FLAGS = {'attribution_error', 'unsupported_conclusion', 'omitted_contradiction', 'appropriate_abstention', 'useful_next_check'}


class AIReviewPublication(Base):
    __tablename__ = 'ai_review_publications'
    __table_args__ = (UniqueConstraint('user_id', 'request_key'),)
    run_id: Mapped[str] = mapped_column(ForeignKey('ai_runs.id'), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('accounts.id'))
    request_key: Mapped[str] = mapped_column(String(120))
    output_digest: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class AIRunAssessment(Base):
    __tablename__ = 'ai_run_assessments'
    __table_args__ = (UniqueConstraint('user_id', 'request_key'),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey('accounts.id'))
    request_key: Mapped[str] = mapped_column(String(120))
    run_id: Mapped[str] = mapped_column(ForeignKey('ai_runs.id'), index=True)
    output_digest: Mapped[str] = mapped_column(String(80))
    details: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


def claim_items(output: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    items: list[tuple[str, dict[str, Any]]] = []
    for section, leaf in (('claims', None), ('selected_claims', None), ('hypotheses', 'explanation'), ('assertions', 'assertion')):
        for index, value in enumerate(output.get(section, [])):
            claim = value.get(leaf) if leaf else value
            if isinstance(claim, dict) and isinstance(claim.get('text'), str):
                items.append((f'{section}.{index}' + (f'.{leaf}' if leaf else ''), claim))
    return items


def _run(session: Session, run_id: str, actor: str, owner: bool, fingerprint: str | None = None) -> AIRun:
    run = session.get(AIRun, run_id)
    publication = session.get(AIReviewPublication, run_id)
    if run is None or (run.user_id != actor and not owner and (publication is None or fingerprint is None)):
        raise ServiceError('NOT_FOUND', 'AI draft not found or not shared for review', 404)
    if run.status != 'COMPLETED' or not run.result or not isinstance(run.result.get('output'), dict):
        raise ServiceError('NO_VALIDATED_OUTPUT', 'Only completed validated drafts can receive semantic review', 409)
    actual = digest(run.result['output'])
    if fingerprint is not None and fingerprint != actual:
        raise ServiceError('OUTPUT_MISMATCH', 'Review must identify this exact output digest', 409)
    if publication is not None and publication.output_digest != actual:
        raise ServiceError('OUTPUT_MISMATCH', 'Shared output identity has changed', 409)
    return run


def _declaration(actor: str, run: AIRun, kind: str, qualifications: str, independent: bool) -> None:
    if kind not in {'human', 'ai_assistant', 'unspecified'}:
        raise ServiceError('INVALID_REVIEW', 'Unknown reviewer kind', 422)
    if (kind == 'human' or independent) and not qualifications.strip():
        raise ServiceError('INVALID_REVIEW', 'Describe reviewer qualifications and limitations', 422)
    if independent and actor == run.user_id:
        raise ServiceError('INVALID_REVIEW', 'The generation requester cannot declare an independent review', 422)


def publish_review(run_id: str, actor: str, request_key: str, output_digest: str, owner: bool = False) -> dict[str, Any]:
    with session_scope() as session:
        lock(session)
        run = _run(session, run_id, actor, owner, output_digest)
        if run.user_id != actor and not owner:
            raise ServiceError('NOT_FOUND', 'Only the requester or owner may share a draft', 404)
        previous = session.scalar(select(AIReviewPublication).where(AIReviewPublication.user_id == actor, AIReviewPublication.request_key == request_key))
        if previous and (previous.run_id, previous.output_digest) != (run_id, output_digest):
            raise ServiceError('IDEMPOTENCY_CONFLICT', 'Publication key already used', 409)
        publication = session.get(AIReviewPublication, run_id)
        if publication is not None and (publication.user_id != actor or publication.request_key != request_key):
            raise ServiceError('ALREADY_SHARED', 'This exact draft is already available in the reviewer inbox', 409)
        if publication is None:
            publication = AIReviewPublication(run_id=run_id, user_id=actor, request_key=request_key, output_digest=output_digest)
            session.add(publication)
            session.flush()
        return {'run_id': run_id, 'output_digest': publication.output_digest, 'published_by': publication.user_id, 'created_at': publication.created_at.isoformat()}


def queue() -> dict[str, Any]:
    with session_scope() as session:
        items = []
        for publication in session.scalars(select(AIReviewPublication).order_by(AIReviewPublication.created_at.desc()).limit(100)):
            run = session.get(AIRun, publication.run_id)
            if run and run.status == 'COMPLETED' and run.result and digest(run.result.get('output')) == publication.output_digest:
                reviews = session.scalars(select(AIClaimReview).where(AIClaimReview.run_id == run.id)).all()
                items.append({'id': run.id, 'analysis_id': run.analysis_id, 'task': run.task, 'provider': 'openai', 'model': run.configuration.get('generation_model'), 'output_digest': publication.output_digest, 'claim_count': len(claim_items(run.result['output'])), 'created_at': publication.created_at.isoformat(), 'reviewed_claims': len({r.claim_path for r in reviews})})
        return {'items': items}


def _assessment_view(row: AIRunAssessment) -> dict[str, Any]:
    return {'id': row.id, 'run_id': row.run_id, 'actor': row.user_id, 'output_digest': row.output_digest, 'created_at': row.created_at.isoformat(), **row.details}


def review_packet(run_id: str, actor: str, owner: bool = False) -> dict[str, Any]:
    with session_scope() as session:
        publication = session.get(AIReviewPublication, run_id)
        run = _run(session, run_id, actor, owner, publication.output_digest if publication else None)
        assert run.result is not None
        reviews = session.scalars(select(AIClaimReview).where(AIClaimReview.run_id == run_id).order_by(AIClaimReview.created_at, AIClaimReview.id)).all()
        assessments = session.scalars(select(AIRunAssessment).where(AIRunAssessment.run_id == run_id).order_by(AIRunAssessment.created_at, AIRunAssessment.id)).all()
        return {'id': run.id, 'requested_by': run.user_id, 'analysis_id': run.analysis_id, 'task': run.task, 'provider': 'openai', 'model': run.configuration.get('generation_model'), 'output_digest': digest(run.result['output']), 'output': run.result['output'], 'packet': {**{key: run.packet.get(key, []) for key in ('evidence', 'metrics', 'historical_evidence')}, **{key: run.packet[key] for key in ('incident_id', 'revision', 'cutoff', 'analysis_digest') if key in run.packet}}, 'published_by': publication.user_id if publication else None, 'created_at': run.created_at.isoformat(), 'claim_reviews': [claim_review_view(r) for r in reviews], 'assessments': [_assessment_view(a) for a in assessments]}


def save_claim_review(run_id: str, actor: str, request_key: str, claim_path: str, supported: bool | None, rationale: str, *, owner: bool = False, output_digest: str | None = None, judgment: str | None = None, flags: list[str] | None = None, reviewer_kind: str = 'unspecified', qualifications: str = '', independent: bool = False) -> dict[str, Any]:
    judgment = judgment or ('supported' if supported is True else 'unsupported' if supported is False else '')
    if judgment not in {'supported', 'unsupported', 'insufficient_evidence'} or (supported is not None and supported != (judgment == 'supported')):
        raise ServiceError('INVALID_REVIEW', 'Choose a consistent claim-support judgment', 422)
    if not rationale.strip() or set(flags or []) - FLAGS:
        raise ServiceError('INVALID_REVIEW', 'Rationale and valid review flags are required', 422)
    with session_scope() as session:
        lock(session)
        run = _run(session, run_id, actor, owner, output_digest)
        _declaration(actor, run, reviewer_kind, qualifications, independent)
        assert run.result is not None
        if claim_path not in dict(claim_items(run.result['output'])):
            raise ServiceError('CLAIM_UNKNOWN', 'Review a canonical returned claim path', 422)
        values = {'run_id': run_id, 'claim_path': claim_path, 'supported': judgment == 'supported', 'judgment': judgment, 'rationale': rationale, 'output_digest': digest(run.result['output']), 'flags': sorted(set(flags or [])), 'reviewer_kind': reviewer_kind, 'qualifications': qualifications, 'independent': independent}
        existing = session.scalar(select(AIClaimReview).where(AIClaimReview.user_id == actor, AIClaimReview.request_key == request_key))
        if existing:
            if any(getattr(existing, key) != value for key, value in values.items()):
                raise ServiceError('IDEMPOTENCY_CONFLICT', 'Review identity already used for another annotation', 409)
            return claim_review_view(existing)
        row = AIClaimReview(user_id=actor, request_key=request_key, **values)
        session.add(row)
        session.flush()
        return claim_review_view(row)


def assess_run(run_id: str, actor: str, request_key: str, output_digest: str, details: dict[str, Any], owner: bool = False) -> dict[str, Any]:
    with session_scope() as session:
        lock(session)
        run = _run(session, run_id, actor, owner, output_digest)
        _declaration(actor, run, details['reviewer_kind'], details['qualifications'], details['independent'])
        existing = session.scalar(select(AIRunAssessment).where(AIRunAssessment.user_id == actor, AIRunAssessment.request_key == request_key))
        if existing:
            if (existing.run_id, existing.output_digest, existing.details) != (run_id, output_digest, details):
                raise ServiceError('IDEMPOTENCY_CONFLICT', 'Assessment key already used', 409)
            return _assessment_view(existing)
        row = AIRunAssessment(user_id=actor, request_key=request_key, run_id=run_id, output_digest=output_digest, details=details)
        session.add(row)
        session.flush()
        return _assessment_view(row)


def review_report(run_id: str, actor: str, owner: bool = False) -> dict[str, Any]:
    packet = review_packet(run_id, actor, owner)
    paths = {path for path, _ in claim_items(packet['output'])}
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for row in packet['claim_reviews']:
        latest[(row['actor'], row['claim_path'])] = row
    by_path = {path: [r for (_, p), r in latest.items() if p == path] for path in paths}
    independent = [r for r in latest.values() if r['reviewer_kind'] == 'human' and r['independent']]
    independent_paths = {r['claim_path'] for r in independent}
    disagreements = [{'claim_path': path, 'judgments': sorted({r['judgment'] for r in rows}), 'actors': [r['actor'] for r in rows]} for path, rows in sorted(by_path.items()) if len({r['judgment'] for r in rows}) > 1]
    reviewers = {r['actor']: {key: r[key] for key in ('actor', 'reviewer_kind', 'qualifications', 'independent')} for r in [*packet['claim_reviews'], *packet['assessments']]}
    reviewed = {path for path, rows in by_path.items() if rows}
    independent_assessments = [a for a in packet['assessments'] if a['reviewer_kind'] == 'human' and a['independent']]
    status = 'AWAITING_INDEPENDENT_HUMAN_REVIEW' if not independent_paths and not independent_assessments else 'DECLARED_INDEPENDENT_REVIEW_COMPLETE' if independent_paths == paths and independent_assessments else 'PARTIAL_DECLARED_INDEPENDENT_REVIEW'
    return {'run_id': run_id, 'output_digest': packet['output_digest'], 'total_claims': len(paths), 'reviewed_claims': len(reviewed), 'unreviewed_claims': len(paths - reviewed), **{f'{judgment}_claims': sum(bool(rows) and {r['judgment'] for r in rows} == {judgment} for rows in by_path.values()) for judgment in ('supported', 'unsupported', 'insufficient_evidence')}, 'declared_independent_human_reviewers': len({r['actor'] for r in [*independent, *independent_assessments]}), 'independent_human_reviewed_claims': len(independent_paths), 'independent_human_assessments': len(independent_assessments), 'disagreements': disagreements, 'reviewers': list(reviewers.values()), 'claim_reviews': packet['claim_reviews'], 'assessments': packet['assessments'], 'status': status, 'limitations': ['Reviewer identity is authenticated; qualifications and independence are self-declared, not independently verified.', 'A distinct reviewer account does not establish manufacturing expertise or organizational independence.', 'Claim judgments and run-level omissions/usefulness assessments are separate from operational approval.', 'Synthetic evidence and structural checks do not establish real-factory benefit.']}
