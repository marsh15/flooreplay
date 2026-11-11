"""HTTP surface for the review queue (T20).

Same rules as `decisions_api`: a signed-in account, a workspace query parameter checked against
memberships (404 when not visible), and writes that need a membership in a workspace that accepts
writes (the demo workspace never does). Assignment and decisions are further limited by the
service: owners and assignees, read from the membership and assignment rows, never the request.

Text limits (note 2000, value 500, no NUL) are enforced by the service so that every refusal
carries a stable error code.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Query, Request
from pydantic import BaseModel, Field

from .auth import Account, require_reviewer
from .db import session_scope
from .decisions import review_service
from .decisions.review_service import FactDraft, ReviewItemDetail, ReviewItemView, SyncResult
from .decisions_api import WorkspaceQuery, _member, _readable

ReviewState = Literal["OPEN", "ASSIGNED", "CONFIRMED", "CORRECTED", "REJECTED"]


class ReviewItemList(BaseModel):
    items: list[ReviewItemView]


class AssignRequest(BaseModel):
    assignee_id: str | None = Field(default=None, min_length=1, max_length=200, description="Null clears the assignment")


class NoteRequest(BaseModel):
    note: str = Field(description="Required, at most 2000 characters")


class ConfirmRequest(NoteRequest):
    value: str | None = Field(default=None, description="Required when the field failed checks; at most 500 characters")
    fact: FactDraft | None = None


class CorrectRequest(NoteRequest):
    value: str | None = Field(default=None, description="The corrected value; at most 500 characters")
    fact: FactDraft | None = None


def install_review_routes(app: FastAPI) -> None:
    prefix = "/api/v1/decisions/review-items"

    @app.get(prefix, response_model=ReviewItemList)
    def list_review_items(
        request: Request,
        user: Annotated[Account, Depends(require_reviewer)],
        workspace_id: WorkspaceQuery,
        state: Annotated[ReviewState | None, Query()] = None,
        assignee: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    ) -> ReviewItemList:
        ws = _readable(request, workspace_id)
        with session_scope() as session:
            items = review_service.list_items(session, ws, state=state, assignee=assignee)
            return ReviewItemList(items=items)

    @app.get(prefix + "/{item_id}", response_model=ReviewItemDetail)
    def get_review_item(
        item_id: str,
        request: Request,
        user: Annotated[Account, Depends(require_reviewer)],
        workspace_id: WorkspaceQuery,
    ) -> ReviewItemDetail:
        ws = _readable(request, workspace_id)
        with session_scope() as session:
            return review_service.get_item(session, ws, item_id)

    @app.post(prefix + "/sync", response_model=SyncResult)
    def sync_review_queue(
        request: Request,
        user: Annotated[Account, Depends(require_reviewer)],
        workspace_id: WorkspaceQuery,
    ) -> SyncResult:
        # Idempotent: creates the missing items for stored extractions and NEEDS_REVIEW evaluations.
        ws = _readable(request, workspace_id)
        with session_scope() as session:
            _member(session, user, ws)
            return review_service.sync_queue(session, ws)

    @app.post(prefix + "/{item_id}/assign", response_model=ReviewItemView)
    def assign_review_item(
        item_id: str,
        body: AssignRequest,
        request: Request,
        user: Annotated[Account, Depends(require_reviewer)],
        workspace_id: WorkspaceQuery,
    ) -> ReviewItemView:
        ws = _readable(request, workspace_id)
        with session_scope() as session:
            _member(session, user, ws)
            return review_service.assign(session, ws, item_id, user.id, body.assignee_id)

    @app.post(prefix + "/{item_id}/confirm", response_model=ReviewItemView)
    def confirm_review_item(
        item_id: str,
        body: ConfirmRequest,
        request: Request,
        user: Annotated[Account, Depends(require_reviewer)],
        workspace_id: WorkspaceQuery,
    ) -> ReviewItemView:
        ws = _readable(request, workspace_id)
        with session_scope() as session:
            _member(session, user, ws)
            return review_service.confirm(
                session, ws, item_id, user.id, note=body.note, value=body.value, fact=body.fact
            )

    @app.post(prefix + "/{item_id}/correct", response_model=ReviewItemView)
    def correct_review_item(
        item_id: str,
        body: CorrectRequest,
        request: Request,
        user: Annotated[Account, Depends(require_reviewer)],
        workspace_id: WorkspaceQuery,
    ) -> ReviewItemView:
        ws = _readable(request, workspace_id)
        with session_scope() as session:
            _member(session, user, ws)
            return review_service.correct(
                session, ws, item_id, user.id, note=body.note, value=body.value, fact=body.fact
            )

    @app.post(prefix + "/{item_id}/reject", response_model=ReviewItemView)
    def reject_review_item(
        item_id: str,
        body: NoteRequest,
        request: Request,
        user: Annotated[Account, Depends(require_reviewer)],
        workspace_id: WorkspaceQuery,
    ) -> ReviewItemView:
        ws = _readable(request, workspace_id)
        with session_scope() as session:
            _member(session, user, ws)
            return review_service.reject(session, ws, item_id, user.id, note=body.note)
