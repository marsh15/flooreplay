"""Factory boundaries for HTTP operations; administrative CLI sessions are explicit trust roots."""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextvars import ContextVar
from typing import Any
from uuid import uuid4

from fastapi import Request
from sqlalchemy import ForeignKey, String, event, or_, select
from sqlalchemy.orm import Mapped, Session, mapped_column, with_loader_criteria

from .auth import Account, current_user
from .db import session_scope
from .models import Base, IncidentRevision
from .service import ServiceError

DEMO = 'public-demo'
# None is reserved for offline administrative sessions. HTTP always establishes a scope.
allowed_workspaces: ContextVar[tuple[str, ...] | None] = ContextVar('factory_workspaces', default=None)
request_actor: ContextVar[str | None] = ContextVar('factory_request_actor', default=None)
write_workspace: ContextVar[str | None] = ContextVar('factory_write_workspace', default=None)


class Workspace(Base):
    __tablename__ = 'workspaces'
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(120))
    visibility: Mapped[str] = mapped_column(String(16), default='private')


class WorkspaceMember(Base):
    __tablename__ = 'workspace_members'
    workspace_id: Mapped[str] = mapped_column(ForeignKey('workspaces.id'), primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey('accounts.id'), primary_key=True)
    role: Mapped[str] = mapped_column(String(16), default='member')


def personal_workspace(session: Session, actor: Account) -> str:
    identity = 'owner-' + actor.id
    if session.get(Workspace, identity) is None:
        from sqlalchemy.dialects.postgresql import insert
        session.execute(insert(Workspace).values(id=identity, name=actor.display_name + ' private workspace', visibility='private').on_conflict_do_nothing())
        session.execute(insert(WorkspaceMember).values(workspace_id=identity, account_id=actor.id, role='owner').on_conflict_do_nothing())
    return identity


async def request_scope(request: Request) -> AsyncIterator[None]:
    actor = current_user(request)
    identifiers = [DEMO]
    destination = None
    with session_scope() as session:
        if actor is not None:
            if actor.role == 'owner':
                destination = personal_workspace(session, actor)
            identifiers.extend(session.scalars(select(WorkspaceMember.workspace_id).where(WorkspaceMember.account_id == actor.id)).all())
    request.state.workspace_ids = identifiers
    request.state.default_workspace_id = destination
    actor_token = request_actor.set(actor.id if actor else None)
    read_token = allowed_workspaces.set(tuple(identifiers))
    write_token = write_workspace.set(destination)
    try:
        yield
    finally:
        request_actor.reset(actor_token)
        write_workspace.reset(write_token)
        allowed_workspaces.reset(read_token)


def destination(session: Session, actor: Account, requested: str | None) -> str:
    identifier = requested or personal_workspace(session, actor)
    membership = session.get(WorkspaceMember, (identifier, actor.id))
    if identifier == DEMO or membership is None or membership.role != 'owner':
        raise ServiceError('WORKSPACE_UNKNOWN', 'Private destination workspace not found or not owned', 404)
    return identifier


def list_workspaces(session: Session, actor: Account) -> dict[str, Any]:
    return {'items': [{'id': row.id, 'name': row.name, 'visibility': row.visibility, 'role': role} for row, role in session.execute(select(Workspace, WorkspaceMember.role).join(WorkspaceMember).where(WorkspaceMember.account_id == actor.id))]}


def create_workspace(session: Session, actor: Account, name: str) -> dict[str, Any]:
    row = Workspace(name=name, visibility='private')
    session.add(row)
    session.flush()
    session.add(WorkspaceMember(workspace_id=row.id, account_id=actor.id, role='owner'))
    session.flush()
    return {'id': row.id, 'name': row.name, 'visibility': row.visibility}


def add_member(session: Session, actor: Account, workspace_id: str, account_id: str) -> dict[str, str]:
    destination(session, actor, workspace_id)
    account = session.get(Account, account_id)
    if account is None or account.disabled:
        raise ServiceError('ACCOUNT_UNKNOWN', 'Account not found', 404)
    row = session.get(WorkspaceMember, (workspace_id, account_id))
    if row is None:
        session.add(WorkspaceMember(workspace_id=workspace_id, account_id=account_id, role='member'))
    return {'workspace_id': workspace_id, 'account_id': account_id, 'role': row.role if row else 'member'}


@event.listens_for(Session, 'do_orm_execute')
def scope_queries(state: Any) -> None:
    identifiers = allowed_workspaces.get()
    if identifiers is None or not state.is_select:
        return
    # All incident-linked tables carry the same immutable factory boundary.
    from .ai_evaluation import AIClaimReview
    from .incident_workflow import (
        IncidentCheck,
        IncidentResolution,
        WorkflowActivity,
        WorkflowReceipt,
    )
    from .models import (
        ComparisonReport,
        ExpectationRevision,
        ImportAudit,
        IncidentAnalysis,
        IncidentModelJob,
        IncidentReview,
        IncidentSourceArtifact,
        ParserCall,
        ReplayAttempt,
        ReviewCheck,
        ScenarioRevision,
        SourceSnapshot,
        SuiteRevision,
    )
    from .paid_models import AIRun, CorpusRelease, RetrievalRun
    from .semantic_review import AIReviewPublication, AIRunAssessment
    classes = (SourceSnapshot, ScenarioRevision, ExpectationRevision, ReplayAttempt, ImportAudit, SuiteRevision, ComparisonReport, ParserCall, ReviewCheck, IncidentRevision, IncidentAnalysis, IncidentModelJob, IncidentReview, IncidentSourceArtifact, AIRun, CorpusRelease, RetrievalRun, IncidentCheck, IncidentResolution, WorkflowActivity, WorkflowReceipt, AIReviewPublication, AIRunAssessment, AIClaimReview)
    statement = state.statement
    for model in classes:
        statement = statement.options(with_loader_criteria(model, model.workspace_id.in_(identifiers), include_aliases=True))
    state.statement = statement


@event.listens_for(Session, 'before_flush')
def scope_new_rows(session: Session, _context: Any, _instances: Any) -> None:
    identifiers = allowed_workspaces.get()
    if identifiers is None:
        return
    for row in session.new:
        if hasattr(row, 'workspace_id') and not isinstance(row, WorkspaceMember):
            if getattr(row, 'workspace_id', None) is None:
                # Linked operations inherit their evidence boundary, never actor privilege.
                incident_id = getattr(row, 'incident_id', None)
                analysis_id = getattr(row, 'analysis_id', None)
                run_id = getattr(row, 'run_id', None)
                parent: Any = None
                if incident_id:
                    parent = session.scalar(select(IncidentRevision).where(IncidentRevision.incident_id == incident_id).order_by(IncidentRevision.revision.desc()))
                elif analysis_id:
                    from .models import IncidentAnalysis
                    parent = session.get(IncidentAnalysis, analysis_id)
                elif run_id:
                    from .paid_models import AIRun
                    parent = session.get(AIRun, run_id)
                row.workspace_id = parent.workspace_id if parent else write_workspace.get() or DEMO
            if row.workspace_id not in identifiers:
                raise ServiceError('WORKSPACE_UNKNOWN', 'Workspace not found', 404)


def visible_account_ids() -> Any:
    identifiers = allowed_workspaces.get()
    return select(WorkspaceMember.account_id).where(WorkspaceMember.workspace_id.in_(identifiers or ()))


def restrict_accounts(statement: Any) -> Any:
    if allowed_workspaces.get() is None:
        return statement
    return statement.where(or_(Account.id == request_actor.get(), Account.id.in_(visible_account_ids())))


def require_assignee_workspace(session: Session, account_id: str, workspace_id: str) -> None:
    if workspace_id == DEMO or allowed_workspaces.get() is None:
        return
    if session.get(WorkspaceMember, (workspace_id, account_id)) is None:
        raise ServiceError('ASSIGNEE_UNAVAILABLE', 'Choose an active member of this factory workspace', 422)
