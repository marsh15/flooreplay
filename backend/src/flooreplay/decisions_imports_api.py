"""HTTP surface for CSV import preview and publication (T16).

POST /api/v1/decisions/imports/preview stores nothing. POST /api/v1/decisions/imports/publish
re-runs the preview on the server and appends the raw artifact and its facts in one
transaction. Both routes need a signed-in account and a workspace the caller can see (the
`workspace_id` query parameter, as in decisions_api). Publishing additionally needs a
membership row with the owner or member role in a private workspace; the public demo is
refused. `known_at` is always stamped by the server, so any value sent by the client is
ignored. No route here calls a model provider.
"""

from __future__ import annotations

import base64
import binascii
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, Request
from pydantic import BaseModel, Field

from .auth import Account, require_reviewer
from .db import session_scope
from .decisions import publish
from .decisions.imports import MAX_BYTES, ImportProblem
from .decisions.types import Fact
from .decisions_api import WorkspaceQuery, _member, _readable
from .errors import ServiceError
from .workspaces import DEMO


class ImportBody(BaseModel):
    filename: str = Field(min_length=1, max_length=200)
    profile: str = Field(min_length=1, max_length=48)
    column_mapping: dict[str, str] = Field(default_factory=dict)
    as_of: datetime
    timezone: str = Field(default="Asia/Kolkata", min_length=1, max_length=64)
    units: dict[str, str] = Field(default_factory=dict)
    coverage_qualities: list[str] | None = None
    content_base64: str = Field(min_length=1)


class PublishBody(ImportBody):
    preview_digest: str = Field(min_length=1, max_length=128)
    idempotency_key: str = Field(min_length=1, max_length=200)


class PreviewView(BaseModel):
    status: Literal["READY", "BLOCKED"]
    profile: str
    filename: str
    raw_digest: str
    as_of: datetime
    preview_digest: str
    coverage: dict[str, Any] | None
    problems: list[ImportProblem]
    facts: list[Fact]
    pending_extraction: list[publish.PendingNote]


class PublishView(BaseModel):
    artifact_id: str
    idempotent_replay: bool
    known_at: datetime
    raw_digest: str
    preview_digest: str
    fact_ids: list[str]
    pending_extraction: list[publish.PendingNote]


MAX_ENCODED_CHARS = publish.MAX_ENCODED_CHARS


def _decode(body: ImportBody) -> bytes:
    """The raw upload. Size is checked before decoding and again after."""
    if len(body.content_base64) > MAX_ENCODED_CHARS:
        raise ServiceError("PAYLOAD_TOO_LARGE", f"The upload exceeds {MAX_BYTES} bytes", 413)
    try:
        raw = base64.b64decode(body.content_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ServiceError("INVALID_BASE64", "content_base64 must be valid base64", 422) from exc
    if len(raw) > MAX_BYTES:
        raise ServiceError("PAYLOAD_TOO_LARGE", f"The upload exceeds {MAX_BYTES} bytes", 413)
    return raw


def _preview_view(body: ImportBody, raw: bytes) -> PreviewView:
    preview = publish.run_preview(
        raw,
        filename=body.filename,
        profile=body.profile,
        column_mapping=body.column_mapping,
        as_of=body.as_of,
        timezone=body.timezone,
        units=body.units,
        coverage_qualities=body.coverage_qualities,
    )
    return PreviewView(
        status=preview.status,
        profile=preview.profile.value,
        filename=preview.filename,
        raw_digest=preview.raw_digest,
        as_of=preview.as_of,
        preview_digest=preview.preview_digest,
        coverage=preview.coverage.model_dump(mode="json") if preview.coverage is not None else None,
        problems=list(preview.problems),
        facts=list(preview.facts),
        pending_extraction=list(publish.pending_notes(preview)),
    )


def install_decisions_import_routes(app: FastAPI) -> None:
    prefix = "/api/v1/decisions/imports"

    @app.post(prefix + "/preview", response_model=PreviewView)
    def preview_csv(
        body: ImportBody,
        request: Request,
        user: Annotated[Account, Depends(require_reviewer)],
        workspace_id: WorkspaceQuery,
    ) -> PreviewView:
        _readable(request, workspace_id)
        return _preview_view(body, _decode(body))

    @app.post(prefix + "/publish", response_model=PublishView)
    def publish_csv(
        body: PublishBody,
        request: Request,
        user: Annotated[Account, Depends(require_reviewer)],
        workspace_id: WorkspaceQuery,
    ) -> PublishView:
        _readable(request, workspace_id)
        if workspace_id == DEMO:
            raise ServiceError(
                "PRIVATE_IMPORT_REQUIRED", "The public demo workspace cannot receive imports", 403
            )
        with session_scope() as session:
            member = _member(session, user, workspace_id)
            publish.check_publish_rights(session, workspace_id=workspace_id, member=member)
            raw = _decode(body)
            result = publish.publish_import(
                session,
                workspace_id=workspace_id,
                raw=raw,
                filename=body.filename,
                profile=body.profile,
                column_mapping=body.column_mapping,
                as_of=body.as_of,
                timezone=body.timezone,
                units=body.units,
                coverage_qualities=body.coverage_qualities,
                preview_digest=body.preview_digest,
                idempotency_key=body.idempotency_key,
            )
            return PublishView(
                artifact_id=result.artifact_id,
                idempotent_replay=result.idempotent_replay,
                known_at=result.known_at,
                raw_digest=result.raw_digest,
                preview_digest=result.preview_digest,
                fact_ids=list(result.fact_ids),
                pending_extraction=list(result.pending_extraction),
            )
