"""As-known incident accounting and conservative interpretation."""

from __future__ import annotations

import json

import pytest

from flooreplay.incident_engine import analyze_incident
from flooreplay.incident_fixtures import incident_fixtures


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


def test_complete_buckets_zero_output_and_union_blocks():
    report = analyze_incident(_revision())
    assert report["metrics"]["status"] == "COMPLETE"
    assert (report["metrics"]["planned"], report["metrics"]["observed"], report["metrics"]["shortfall"]) == (30, 10, 20)
    assert report["metrics"]["blocked_minutes"] == 30
    assert report["metrics"]["unfinished_buckets"] == ["p2"]
    assert [segment["evidence"] for segment in report["metrics"]["block_segments"]] == [["material"], ["machine", "material"], ["machine"]]
    assert next(h for h in report["hypotheses"] if h["category"] == "quality")["status"] == "PLAUSIBLE"
    json.dumps(report)


def test_missing_output_never_becomes_zero():
    revision = _revision()
    revision["output_buckets"].pop()
    metrics = analyze_incident(revision)["metrics"]
    assert metrics["status"] == "PARTIAL"
    assert metrics["observed"] is metrics["shortfall"] is None
    assert metrics["missing_buckets"] == ["p1"]


def test_sparse_baseline_cannot_make_a_full_window_complete():
    revision = _revision()
    revision["plan_buckets"] = revision["plan_buckets"][:1]
    revision["output_buckets"] = revision["output_buckets"][:1]
    metrics = analyze_incident(revision)["metrics"]
    assert metrics["status"] == "PARTIAL"
    assert metrics["shortfall"] is None
    assert metrics["baseline_target"] is None
    assert metrics["missing_plan_buckets"]


def test_late_record_and_correction_respect_cutoff():
    revision = _revision()
    revision["events"].append({"id": "late-note", "type": "machine_interruption", "lane": "machines", "summary": "Recorded later", "occurred_at": "2026-01-01T09:10:00+05:30", "available_at": "2026-01-01T11:20:00+05:30", "source_id": "src-4"})
    revision["output_buckets"].append({"id": "o1-corrected", "supersedes_id": "o1", "start": "2026-01-01T09:15:00+05:30", "end": "2026-01-01T09:30:00+05:30", "quantity": 8, "available_at": "2026-01-01T09:40:00+05:30"})
    for index in (2, 3):
        plan = revision["plan_buckets"][index]
        revision["output_buckets"].append({**plan, "id": f"o{index}", "quantity": 0, "available_at": "2026-01-01T10:01:00+05:30"})
    earlier = analyze_incident(revision)
    assert earlier["metrics"]["observed"] == 10
    assert "late-note" not in [event["id"] for event in earlier["timeline"]]
    revision["cutoff"] = "2026-01-01T11:30:00+05:30"
    later = analyze_incident(revision)
    assert later["metrics"]["observed"] == 18
    assert "late-note" in [event["id"] for event in later["timeline"]]
    assert earlier["metrics"]["observed"] == 10


def test_conflicting_reports_and_unsupported_cumulative_counter():
    revision = _revision()
    revision["output_buckets"].append({**revision["output_buckets"][0], "id": "duplicate"})
    metrics = analyze_incident(revision)["metrics"]
    assert metrics["status"] == "CONFLICTING"
    assert metrics["shortfall"] is None
    revision["output_buckets"][-1]["kind"] = "cumulative"
    with pytest.raises(ValueError, match="final-good delta"):
        analyze_incident(revision)


def test_output_without_matching_baseline_cannot_be_complete():
    revision = _revision()
    revision["output_buckets"].append({
        "id": "orphan", "start": "2026-01-01T09:05:00+05:30",
        "end": "2026-01-01T09:20:00+05:30", "quantity": 5,
        "available_at": "2026-01-01T09:21:00+05:30",
    })
    assert analyze_incident(revision)["metrics"]["status"] == "CONFLICTING"


def test_hero_later_evidence_changes_report_without_rewriting_early_view():
    early, late = incident_fixtures()[:2]
    first = analyze_incident(early)
    second = analyze_incident(late)
    assert "EV-MAINT-1" not in [event["id"] for event in first["timeline"]]
    assert "EV-MAINT-1" in [event["id"] for event in second["timeline"]]
    assert "EV-MACH-1" not in [event["id"] for event in second["timeline"]]
    assert first["metrics"]["blocked_minutes"] == second["metrics"]["blocked_minutes"] == 30
    assert first["metrics"]["status"] == second["metrics"]["status"] == "COMPLETE"
    assert first["metrics"]["shortfall"] is not None
