"""CSV import: profiles, normalization, row diagnostics, publication, fork.

Covers the plan's essential import edge cases: empty file, BOM, bad
headers, duplicate rows, unknown entities, malformed values, incomplete
roster, size limits, idempotent publication, and the fork flow that must
leave historical revisions untouched.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from flooreplay.api import app

pytestmark = pytest.mark.skipif(
    __import__("os").environ.get("FLOORREPLAY_SKIP_DB") == "1", reason="database not available"
)

GOOD_META = {
    "declared_evidence_at": "2026-09-22T07:55:00+05:30",
    "coverage_complete": True,
}

ATT_HEADERS = "operator_id,status,observed_at,shift_note\n"
SKILL_HEADERS = "operator_id,operation_id,level,assessed_at\n"


@pytest.fixture(scope="module")
def client(owner_headers) -> TestClient:
    from flooreplay.seeding import run_seed

    run_seed()
    return TestClient(app, headers=owner_headers)


def _preview(client: TestClient, profile: str, csv_text: str, **meta: object) -> object:
    body = {"profile_id": profile, "csv_text": csv_text, **GOOD_META, **(meta or {})}
    return client.post("/api/v1/imports/preview", json=body)


# ---------------------------------------------------------------------------
# Structural (file-level) problems -> 422 envelope
# ---------------------------------------------------------------------------


def test_empty_file_rejected(client: TestClient):
    response = _preview(client, "attendance-v1", "")
    assert response.status_code == 422
    assert response.json()["code"] == "EMPTY_FILE"


def test_bad_headers_rejected(client: TestClient):
    response = _preview(client, "attendance-v1", "emp,stat,when\nO219,P,2026-09-22T07:55+05:30\n")
    assert response.status_code == 422
    assert response.json()["code"] == "BAD_HEADERS"
    assert "operator_id" in response.json()["message"]


def test_header_only_file_rejected(client: TestClient):
    response = _preview(client, "attendance-v1", ATT_HEADERS.strip())
    assert response.status_code == 422


def test_bom_is_accepted(client: TestClient):
    csv_text = "\ufeff" + ATT_HEADERS + "O219,P,2026-09-22T07:55:00+05:30,covering\n"
    response = _preview(client, "attendance-v1", csv_text)
    assert response.status_code == 200
    assert response.json()["counts"]["blocking"] == 0


def test_unknown_profile_rejected(client: TestClient):
    response = _preview(client, "inventory-v1", ATT_HEADERS + "O219,P,2026-09-22T07:55:00+05:30\n")
    assert response.status_code == 422
    assert response.json()["code"] == "UNKNOWN_PROFILE"


def test_row_limit_enforced(client: TestClient):
    rows = "\n".join("O219,P,2026-09-22T07:55:00+05:30" for _ in range(5001))
    response = _preview(client, "attendance-v1", ATT_HEADERS + rows + "\n")
    assert response.status_code == 422
    assert response.json()["code"] == "TOO_MANY_ROWS"


# ---------------------------------------------------------------------------
# Normalization demonstrated
# ---------------------------------------------------------------------------


def test_attendance_p_a_blank_normalization(client: TestClient):
    csv_text = (
        ATT_HEADERS
        + "O219,P,2026-09-22T07:55:00+05:30,covering\n"
        + "O145,A,2026-09-22T07:55:00+05:30,leave\n"
        + "O112,,2026-09-22T07:55:00+05:30,no-scan\n"
    )
    body = _preview(client, "attendance-v1", csv_text).json()
    by_operator = {r["normalized"]["operator_id"]: r for r in body["rows"]}
    assert by_operator["O219"]["normalized"]["status"] == "PRESENT"
    assert by_operator["O145"]["normalized"]["status"] == "ABSENT"
    assert by_operator["O112"]["normalized"]["status"] == "UNKNOWN"
    assert any("blank status -> UNKNOWN" in n for n in by_operator["O112"]["normalizations"])
    assert any("'P' -> PRESENT" in n for n in by_operator["O219"]["normalizations"])
    # Original cells are retained for inspection, including extra columns.
    assert by_operator["O219"]["raw"]["shift_note"] == "covering"
    assert body["ignored_columns"] == ["shift_note"]


def test_naive_timestamp_interpreted_as_factory_tz(client: TestClient):
    csv_text = ATT_HEADERS + "O219,P,2026-09-22 07:55:00,naive\n"
    body = _preview(client, "attendance-v1", csv_text).json()
    row = body["rows"][0]
    assert row["normalized"]["observed_at"] == "2026-09-22T07:55:00+05:30"
    assert any("Asia/Kolkata" in n for n in row["normalizations"])


def test_invalid_timestamp_is_blocking(client: TestClient):
    csv_text = ATT_HEADERS + "O219,P,tomorrow-morning,bad\n"
    body = _preview(client, "attendance-v1", csv_text).json()
    assert body["counts"]["blocking"] == 1
    assert body["rows"][0]["issues"][0]["code"] == "INVALID_TIMESTAMP"


# ---------------------------------------------------------------------------
# Row-level diagnostics
# ---------------------------------------------------------------------------


def test_unknown_operator_and_operation_flagged(client: TestClient):
    att = _preview(client, "attendance-v1", ATT_HEADERS + "O999,P,2026-09-22T07:55:00+05:30\n").json()
    assert att["rows"][0]["issues"][0]["code"] == "UNKNOWN_OPERATOR"

    skills = _preview(
        client,
        "skills-v1",
        SKILL_HEADERS + "O219,OP-XXX,3,2026-09-18T15:00:00+05:30\n",
    ).json()
    assert skills["rows"][0]["issues"][0]["code"] == "UNKNOWN_OPERATION"


def test_duplicate_natural_key_flagged(client: TestClient):
    csv_text = ATT_HEADERS + (
        "O219,P,2026-09-22T07:55:00+05:30\nO219,P,2026-09-22T07:55:00+05:30\n"
    )
    body = _preview(client, "attendance-v1", csv_text).json()
    codes = [i["code"] for r in body["rows"] for i in r["issues"]]
    assert "DUPLICATE_NATURAL_KEY" in codes


def test_missing_required_cell_and_bad_level(client: TestClient):
    skills = _preview(
        client, "skills-v1", SKILL_HEADERS + ",OP-SLM,3,2026-09-18T15:00:00+05:30\n"
    ).json()
    assert skills["rows"][0]["issues"][0]["code"] == "MISSING_REQUIRED_CELL"

    skills = _preview(
        client, "skills-v1", SKILL_HEADERS + "O219,OP-SLM,high,2026-09-18T15:00:00+05:30\n"
    ).json()
    assert skills["rows"][0]["issues"][0]["code"] == "UNSUPPORTED_VALUE"


def test_roster_gap_warns_but_does_not_block(client: TestClient):
    csv_text = ATT_HEADERS + "O219,P,2026-09-22T07:55:00+05:30\n"  # 21 operators missing
    body = _preview(client, "attendance-v1", csv_text).json()
    assert body["counts"]["blocking"] == 0
    file_codes = [i["code"] for i in body["file_issues"]]
    assert "ROSTER_GAP" in file_codes


def test_formula_like_cell_warns(client: TestClient):
    csv_text = ATT_HEADERS + "O219,=SUM(A1:A9),2026-09-22T07:55:00+05:30\n"
    body = _preview(client, "attendance-v1", csv_text).json()
    codes = [i["code"] for i in body["rows"][0]["issues"]]
    assert "FORMULA_LIKE_CELL" in codes


# ---------------------------------------------------------------------------
# Publication: all-or-nothing, idempotent, immutable
# ---------------------------------------------------------------------------


def _good_skills_csv() -> str:
    # Fresh assessment for the roster on the two documented operations.
    from flooreplay.fixtures import _OTHER_LEVELS, _SLM_LEVELS, OPERATORS

    lines = [SKILL_HEADERS.strip()]
    for op in OPERATORS:
        if op.id in _SLM_LEVELS:
            lines.append(f"{op.id},OP-SLM,{_SLM_LEVELS[op.id]},2026-09-21T15:00:00+05:30")
        lines.append(f"{op.id},OP-COL,{_OTHER_LEVELS[op.id]},2026-09-21T15:00:00+05:30")
    return "\n".join(lines) + "\n"


def test_publish_requires_zero_blocking_issues(client: TestClient):
    bad = SKILL_HEADERS + "O219,OP-SLM,9,2026-09-21T15:00:00+05:30\n"
    preview = _preview(client, "skills-v1", bad).json()
    response = client.post(
        "/api/v1/imports/publish",
        json={
            "profile_id": "skills-v1",
            "csv_text": bad,
            "preview_digest": preview["preview_digest"],
            **GOOD_META,
        },
    )
    assert response.status_code == 422
    assert response.json()["code"] == "BLOCKING_ISSUES"


def test_publish_is_idempotent_and_forks_cleanly(client: TestClient):
    csv_text = _good_skills_csv()
    preview = _preview(client, "skills-v1", csv_text).json()
    assert preview["counts"]["blocking"] == 0

    publish_body = {
        "profile_id": "skills-v1",
        "csv_text": csv_text,
        "preview_digest": preview["preview_digest"],
        "GOOD_META": None,  # placeholder removed below
    }
    publish_body.pop("GOOD_META")
    publish_body.update(GOOD_META)

    first = client.post("/api/v1/imports/publish", json=publish_body)
    assert first.status_code == 200
    snapshot_id = first.json()["snapshot_id"]

    second = client.post("/api/v1/imports/publish", json=publish_body)
    assert second.status_code == 200
    # Idempotent by content digest: the exact same preview is never
    # published twice, whatever the run count against a live database.
    assert second.json()["snapshot_id"] == snapshot_id
    assert second.json()["already_published"] is True

    # Publication with a tampered digest is refused.
    publish_body["preview_digest"] = "sha256:deadbeef"
    tampered = client.post("/api/v1/imports/publish", json=publish_body)
    assert tampered.status_code == 409

    # Fork the hero revision 1 with the imported snapshot and replay it:
    # fresh skills must lift the stale-evidence block.
    fork = client.post(
        "/api/v1/scenarios/SCEN-HERO/revisions/1/fork", json={"snapshot_id": snapshot_id}
    )
    assert fork.status_code == 200
    new_revision = fork.json()["revision"]
    assert new_revision > 2
    assert snapshot_id in fork.json()["pinned_snapshot_ids"]
    assert "imported-evidence" in fork.json()["tags"]

    replay = client.post(
        "/api/v1/replays",
        json={
            "scenario_id": "SCEN-HERO",
            "scenario_revision": new_revision,
            "configuration_id": "CFG-IMPROVED-V1",
            "idempotency_key": f"fork-test-{new_revision}",
        },
    )
    assert replay.status_code == 200
    assert replay.json()["domain_outcome"] == "READY_FOR_REVIEW"
    assert replay.json()["result"]["proposal"]["operator_id"] == "O219"

    # The historical revision is untouched: replaying it still blocks.
    historical = client.post(
        "/api/v1/replays",
        json={
            "scenario_id": "SCEN-HERO",
            "scenario_revision": 1,
            "configuration_id": "CFG-IMPROVED-V1",
            "idempotency_key": "fork-test-historical-1",
        },
    )
    assert historical.json()["domain_outcome"] == "NEEDS_CONTEXT"


def test_public_mode_mounts_no_import_routes(owner_headers):
    public_app = __import__("flooreplay.api", fromlist=["create_app"]).create_app(mode="public")
    public_client = TestClient(public_app)
    assert (
        public_client.post(
            "/api/v1/imports/preview",
            json={"profile_id": "attendance-v1", "csv_text": "x", **GOOD_META},
        ).status_code
        == 404
    )
    assert public_client.get("/api/v1/capabilities").json()["imports_enabled"] is False
    assert public_client.get("/api/v1/replays/none").status_code == 404  # core routes intact
