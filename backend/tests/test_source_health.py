"""Source health separates missing or delayed records from reported shortfall."""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from flooreplay.api import app
from flooreplay.source_health import source_health


# Same synthetic revision as test_incident_engine: four 15-minute plans from 09:00, cutoff 09:37.
def _revision():
    return {
        "scope": {"factory": "F1", "line_id": "L1", "order_id": "O1", "style_id": "S1", "stage": "sewing", "unit": "pieces"},
        "window": {"start": "2026-01-01T09:00:00+05:30", "end": "2026-01-01T10:00:00+05:30"},
        "cutoff": "2026-01-01T09:37:00+05:30",
        "plan_buckets": [
            {"id": f"p{i}", "start": f"2026-01-01T09:{i * 15:02d}:00+05:30", "end": f"2026-01-01T09:{(i + 1) * 15:02d}:00+05:30" if i < 3 else "2026-01-01T10:00:00+05:30", "quantity": 15, "available_at": "2026-01-01T08:00:00+05:30"}
            for i in range(4)
        ],
        "output_buckets": [
            {"id": "o0", "start": "2026-01-01T09:00:00+05:30", "end": "2026-01-01T09:15:00+05:30", "quantity": 10, "available_at": "2026-01-01T09:16:00+05:30"},
            {"id": "o1", "start": "2026-01-01T09:15:00+05:30", "end": "2026-01-01T09:30:00+05:30", "quantity": 0, "available_at": "2026-01-01T09:31:00+05:30"},
        ],
        "events": [
            {"id": "material", "type": "material_readiness", "lane": "materials", "summary": "Material late", "start": "2026-01-01T09:00:00+05:30", "end": "2026-01-01T09:20:00+05:30", "available_at": "2026-01-01T09:01:00+05:30", "source_id": "src-1", "line_blocking": True},
            {"id": "machine", "type": "machine_interruption", "lane": "machines", "summary": "Machine stopped", "start": "2026-01-01T09:15:00+05:30", "end": "2026-01-01T09:30:00+05:30", "available_at": "2026-01-01T09:16:00+05:30", "source_id": "src-2", "line_blocking": True},
            {"id": "qc", "type": "qc_hold", "lane": "quality", "summary": "Lot held", "occurred_at": "2026-01-01T09:25:00+05:30", "available_at": "2026-01-01T09:26:00+05:30", "source_id": "src-3"},
        ],
    }


def _statuses(report: dict) -> dict[str, str]:
    return {entry["plan_id"]: entry["status"] for entry in report["production_feed"]["intervals"]}


def test_unreported_interval_awaits_while_the_feed_is_behind():
    revision = _revision()
    revision["output_buckets"].pop()
    report = source_health(revision, [])
    assert _statuses(report) == {"p0": "REPORTED", "p1": "AWAITING", "p2": "NOT_DUE", "p3": "NOT_DUE"}
    awaiting = report["production_feed"]["intervals"][1]
    assert awaiting["minutes_since_due"] == 7 and awaiting["overdue"] is True
    assert report["production_feed"]["typical_delay_minutes"] == 1
    assert report["production_feed"]["intervals_reported_below_plan"] == ["p0"]
    assert "missing data, not lost output" in report["summary"]


def test_interval_skipped_by_a_feed_that_moved_on_is_a_gap():
    revision = _revision()
    revision["cutoff"] = "2026-01-01T09:50:00+05:30"
    revision["output_buckets"][1] = {"id": "o2", "start": "2026-01-01T09:30:00+05:30", "end": "2026-01-01T09:45:00+05:30", "quantity": 15, "available_at": "2026-01-01T09:46:00+05:30"}
    report = source_health(revision, [])
    assert _statuses(report) == {"p0": "REPORTED", "p1": "GAP", "p2": "REPORTED", "p3": "NOT_DUE"}
    assert "overdue" not in report["production_feed"]["intervals"][1]
    assert report["production_feed"]["counts"]["GAP"] == 1


def test_records_unknown_at_the_cutoff_do_not_count_as_reported():
    revision = _revision()
    revision["output_buckets"][1]["available_at"] = "2026-01-01T09:40:00+05:30"
    assert _statuses(source_health(revision, []))["p1"] == "AWAITING"


def test_conflicting_outputs_and_late_notes_are_flagged():
    revision = _revision()
    revision["output_buckets"].append({**revision["output_buckets"][1], "id": "o1-duplicate"})
    revision["events"].append({"id": "late-note", "type": "maintenance_note", "summary": "Earlier feed issue", "occurred_at": "2026-01-01T09:05:00+05:30", "available_at": "2026-01-01T09:30:00+05:30"})
    report = source_health(revision, [])
    assert _statuses(report)["p1"] == "CONFLICTING"
    assert report["conflicts"]["conflicting_intervals"] == ["p1"]
    assert report["operations_feed"]["late_record_ids"] == ["late-note"]
    assert report["rejections"]["recorded"] is False


@pytest.mark.skipif(os.environ.get("FLOORREPLAY_SKIP_DB") == "1", reason="database not available")
def test_public_source_health_for_the_seeded_example():
    response = TestClient(app).get("/api/v1/incidents/INC-001/revisions/2/source-health")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["incident_id"] == "INC-001" and body["revision"] == 2
    assert sum(body["production_feed"]["counts"].values()) == len(body["production_feed"]["intervals"]) > 0
    assert TestClient(app).get("/api/v1/incidents/INC-001/revisions/999/source-health").status_code == 404
