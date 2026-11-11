"""HTTP tests for CSV import preview and publication (T16).

Every test signs in fresh accounts and works in uuid-scoped owner workspaces with uuid keys,
because the facts trigger forbids cleanup. Client-supplied known_at values are sent on purpose
and must be ignored.
"""

from __future__ import annotations

import base64
import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from decisions.test_api import client_for, owner_workspace, uid
from flooreplay.api import app
from flooreplay.db import session_scope
from flooreplay.decisions import service
from flooreplay.decisions.imports import MAX_BYTES
from flooreplay.decisions.models import DecisionSourceArtifact, FactRow
from flooreplay.workspaces import DEMO, Workspace, WorkspaceMember

SAMPLES = Path(__file__).parents[2] / "src/flooreplay/decisions/samples"
AS_OF = "2026-10-20T09:00:00+05:30"
ROUTE = "/api/v1/decisions/imports"
ERP_MAPPING = {
    "lot_id": "lot_id",
    "qty": "qty",
    "unit": "unit",
    "fabric_quality": "quality",
    "colour": "colour",
    "allocation_order_id": "allocation_order_id",
    "allocation_qty": "allocation_qty",
}
NOTES_MAPPING = {"note_id": "note_id", "lot_hint": "lot_hint", "text": "text"}


def erp_raw() -> bytes:
    return (SAMPLES / "erp-fabric-stock.csv").read_bytes()


def body(raw: bytes, **overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "filename": "stock.csv",
        "profile": "erp-fabric-stock",
        "column_mapping": ERP_MAPPING,
        "as_of": AS_OF,
        "units": {},
        "coverage_qualities": ["SJ180", "SJ200"],
        "content_base64": base64.b64encode(raw).decode(),
    }
    data.update(overrides)
    return data


def publish_body(raw: bytes, preview_digest: str, key: str, **overrides: Any) -> dict[str, Any]:
    return body(raw, preview_digest=preview_digest, idempotency_key=key, **overrides)


def preview_of(client: TestClient, ws: str, raw: bytes, **overrides: Any) -> dict[str, Any]:
    response = client.post(f"{ROUTE}/preview", params={"workspace_id": ws}, json=body(raw, **overrides))
    assert response.status_code == 200, response.text
    return dict(response.json())


def error_code(response: Any) -> str:
    return str(response.json()["code"])


def counts(ws: str) -> tuple[int, int]:
    with session_scope() as session:
        artifacts = session.scalar(
            select(func.count()).select_from(DecisionSourceArtifact).where(DecisionSourceArtifact.workspace_id == ws)
        )
        facts = session.scalar(select(func.count()).select_from(FactRow).where(FactRow.workspace_id == ws))
    return int(artifacts or 0), int(facts or 0)


def stored_artifacts(ws: str, key: str) -> list[DecisionSourceArtifact]:
    with session_scope() as session:
        rows = session.scalars(
            select(DecisionSourceArtifact).where(
                DecisionSourceArtifact.workspace_id == ws, DecisionSourceArtifact.idempotency_key == key
            )
        ).all()
        for row in rows:
            session.expunge(row)
        return list(rows)


def test_preview_stores_nothing_and_returns_digest() -> None:
    client, _ = client_for("owner")
    ws = owner_workspace(client)
    before = counts(ws)
    result = preview_of(client, ws, erp_raw())
    assert result["status"] == "READY"
    assert result["preview_digest"].startswith("sha256:")
    assert result["raw_digest"] == "sha256:" + hashlib.sha256(erp_raw()).hexdigest()
    assert len(result["facts"]) > 0
    assert counts(ws) == before


def test_publish_happy_path_keeps_raw_bytes_and_imported_facts() -> None:
    client, _ = client_for("owner")
    ws = owner_workspace(client)
    raw = erp_raw()
    preview = preview_of(client, ws, raw)
    key = uid()
    before = datetime.now(UTC)
    response = client.post(f"{ROUTE}/publish", params={"workspace_id": ws}, json=publish_body(raw, preview["preview_digest"], key))
    after = datetime.now(UTC)
    assert response.status_code == 200, response.text
    view = response.json()
    assert view["idempotent_replay"] is False
    assert sorted(view["fact_ids"]) == sorted(item["id"] for item in preview["facts"])
    known_at = datetime.fromisoformat(view["known_at"])
    assert before - timedelta(seconds=5) <= known_at <= after + timedelta(seconds=5)

    (artifact,) = stored_artifacts(ws, key)
    assert bytes(artifact.raw_bytes) == raw
    assert artifact.raw_digest == "sha256:" + hashlib.sha256(raw).hexdigest()
    assert artifact.preview_digest == preview["preview_digest"]
    assert artifact.profile == "erp_fabric_stock"
    assert counts(ws) == (1, len(preview["facts"]))


def test_publish_with_a_changed_file_is_preview_mismatch() -> None:
    client, _ = client_for("owner")
    ws = owner_workspace(client)
    raw = erp_raw()
    preview = preview_of(client, ws, raw)
    changed = raw.replace(b"4000", b"4001", 1)
    key = uid()
    response = client.post(f"{ROUTE}/publish", params={"workspace_id": ws}, json=publish_body(changed, preview["preview_digest"], key))
    assert response.status_code == 409
    assert error_code(response) == "PREVIEW_MISMATCH"
    assert stored_artifacts(ws, key) == []
    assert counts(ws) == (0, 0)


def test_blocked_preview_is_refused() -> None:
    client, _ = client_for("owner")
    ws = owner_workspace(client)
    raw = erp_raw().replace(b"4000", b"#N/A", 1)
    preview = preview_of(client, ws, raw)
    assert preview["status"] == "BLOCKED"
    key = uid()
    response = client.post(f"{ROUTE}/publish", params={"workspace_id": ws}, json=publish_body(raw, preview["preview_digest"], key))
    assert response.status_code == 422
    assert error_code(response) == "IMPORT_BLOCKED"
    assert counts(ws) == (0, 0)


def test_public_demo_workspace_is_refused() -> None:
    client, _ = client_for("owner")
    raw = erp_raw()
    preview = preview_of(client, DEMO, raw)
    response = client.post(f"{ROUTE}/publish", params={"workspace_id": DEMO}, json=publish_body(raw, preview["preview_digest"], uid()))
    assert response.status_code == 403
    assert error_code(response) == "PRIVATE_IMPORT_REQUIRED"


def test_non_private_workspace_is_refused() -> None:
    client, owner_id = client_for("owner")
    shared = "shared-" + uid()
    with session_scope() as session:
        session.add(Workspace(id=shared, name="shared " + shared, visibility="shared"))
        session.flush()
        session.add(WorkspaceMember(workspace_id=shared, account_id=owner_id, role="owner"))
    raw = erp_raw()
    preview = preview_of(client, shared, raw)
    response = client.post(f"{ROUTE}/publish", params={"workspace_id": shared}, json=publish_body(raw, preview["preview_digest"], uid()))
    assert response.status_code == 403
    assert error_code(response) == "PRIVATE_IMPORT_REQUIRED"
    assert counts(shared) == (0, 0)


def test_reviewer_membership_cannot_publish_but_can_preview() -> None:
    owner, _ = client_for("owner")
    ws = owner_workspace(owner)
    reviewer, reviewer_id = client_for("reviewer")
    with session_scope() as session:
        session.add(WorkspaceMember(workspace_id=ws, account_id=reviewer_id, role="reviewer"))
    raw = erp_raw()
    preview = preview_of(reviewer, ws, raw)
    response = reviewer.post(f"{ROUTE}/publish", params={"workspace_id": ws}, json=publish_body(raw, preview["preview_digest"], uid()))
    assert response.status_code == 403
    assert error_code(response) == "MEMBER_REQUIRED"
    assert counts(ws) == (0, 0)


def test_member_role_can_publish() -> None:
    owner, _ = client_for("owner")
    ws = owner_workspace(owner)
    member, member_id = client_for("reviewer")
    with session_scope() as session:
        session.add(WorkspaceMember(workspace_id=ws, account_id=member_id, role="member"))
    raw = erp_raw()
    preview = preview_of(member, ws, raw)
    response = member.post(f"{ROUTE}/publish", params={"workspace_id": ws}, json=publish_body(raw, preview["preview_digest"], uid()))
    assert response.status_code == 200, response.text


def test_unauthenticated_requests_are_401() -> None:
    anonymous = TestClient(app)
    ws = "anon-" + uid()
    raw = erp_raw()
    preview = anonymous.post(f"{ROUTE}/preview", params={"workspace_id": ws}, json=body(raw))
    publish = anonymous.post(f"{ROUTE}/publish", params={"workspace_id": ws}, json=publish_body(raw, "sha256:x", uid()))
    assert preview.status_code == 401
    assert publish.status_code == 401


def test_idempotent_retry_returns_original_without_duplicates() -> None:
    client, _ = client_for("owner")
    ws = owner_workspace(client)
    raw = erp_raw()
    preview = preview_of(client, ws, raw)
    key = uid()
    payload = publish_body(raw, preview["preview_digest"], key)
    first = client.post(f"{ROUTE}/publish", params={"workspace_id": ws}, json=payload)
    second = client.post(f"{ROUTE}/publish", params={"workspace_id": ws}, json=payload)
    assert first.status_code == 200 and second.status_code == 200, second.text
    assert second.json()["idempotent_replay"] is True
    assert second.json()["artifact_id"] == first.json()["artifact_id"]
    assert second.json()["known_at"] == first.json()["known_at"]
    assert len(stored_artifacts(ws, key)) == 1
    assert counts(ws) == (1, len(preview["facts"]))


def test_a_nul_byte_in_the_idempotency_key_is_a_422_and_stores_nothing() -> None:
    client, _ = client_for("owner")
    ws = owner_workspace(client)
    raw = erp_raw()
    preview = preview_of(client, ws, raw)
    payload = publish_body(raw, preview["preview_digest"], "a\x00b")
    response = client.post(f"{ROUTE}/publish", params={"workspace_id": ws}, json=payload)
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "INVALID_IDEMPOTENCY_KEY"
    assert counts(ws) == (0, 0)


def test_same_key_with_different_content_is_409() -> None:
    client, _ = client_for("owner")
    ws = owner_workspace(client)
    raw = erp_raw()
    key = uid()
    first = preview_of(client, ws, raw)
    assert client.post(f"{ROUTE}/publish", params={"workspace_id": ws}, json=publish_body(raw, first["preview_digest"], key)).status_code == 200
    other = raw.replace(b"4000", b"4500", 1)
    second = preview_of(client, ws, other)
    response = client.post(f"{ROUTE}/publish", params={"workspace_id": ws}, json=publish_body(other, second["preview_digest"], key))
    assert response.status_code == 409
    assert error_code(response) == "IDEMPOTENCY_CONFLICT"
    assert len(stored_artifacts(ws, key)) == 1
    assert counts(ws)[0] == 1


def test_client_supplied_known_at_is_ignored() -> None:
    client, _ = client_for("owner")
    ws = owner_workspace(client)
    raw = erp_raw()
    preview = preview_of(client, ws, raw)
    forged = "2001-01-01T00:00:00+00:00"
    key = uid()
    payload = publish_body(raw, preview["preview_digest"], key, known_at=forged)
    response = client.post(f"{ROUTE}/publish", params={"workspace_id": ws}, json=payload)
    assert response.status_code == 200, response.text
    assert datetime.fromisoformat(response.json()["known_at"]).year == datetime.now(UTC).year
    (artifact,) = stored_artifacts(ws, key)
    assert artifact.known_at.year != 2001


def test_oversize_upload_is_413_on_preview_and_publish() -> None:
    client, _ = client_for("owner")
    ws = owner_workspace(client)
    raw = b"a" * (MAX_BYTES + 1)
    preview = client.post(f"{ROUTE}/preview", params={"workspace_id": ws}, json=body(raw))
    publish = client.post(f"{ROUTE}/publish", params={"workspace_id": ws}, json=publish_body(raw, "sha256:x", uid()))
    assert preview.status_code == 413
    assert publish.status_code == 413
    assert counts(ws) == (0, 0)


def test_facts_appear_in_snapshots_only_at_or_after_server_known_at() -> None:
    client, _ = client_for("owner")
    ws = owner_workspace(client)
    raw = erp_raw()
    preview = preview_of(client, ws, raw)
    view = client.post(f"{ROUTE}/publish", params={"workspace_id": ws}, json=publish_body(raw, preview["preview_digest"], uid())).json()
    known_at = datetime.fromisoformat(view["known_at"])
    ids = set(view["fact_ids"])
    with session_scope() as session:
        before = {fact.id for fact in service.load_facts(session, ws, known_by=known_at - timedelta(seconds=1))}
        at = {fact.id for fact in service.load_facts(session, ws, known_by=known_at)}
    assert before.isdisjoint(ids)
    assert ids <= at


def test_notes_profile_is_stored_as_pending_extraction_without_facts() -> None:
    client, _ = client_for("owner")
    ws = owner_workspace(client)
    raw = (SAMPLES / "notes.csv").read_bytes()
    kwargs = {"profile": "notes", "column_mapping": NOTES_MAPPING, "coverage_qualities": None, "filename": "notes.csv"}
    preview = preview_of(client, ws, raw, **kwargs)
    assert preview["status"] == "READY"
    key = uid()
    response = client.post(
        f"{ROUTE}/publish", params={"workspace_id": ws},
        json=publish_body(raw, preview["preview_digest"], key, **kwargs),
    )
    assert response.status_code == 200, response.text
    view = response.json()
    assert view["fact_ids"] == []
    assert len(view["pending_extraction"]) >= 3
    assert all(item["state"] == "pending_extraction" for item in view["pending_extraction"])
    assert len(stored_artifacts(ws, key)) == 1
    assert counts(ws) == (1, 0)
