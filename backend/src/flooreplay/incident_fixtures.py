"""Author-written synthetic incidents for the deterministic demo.

These are operational observations, not factory data or evaluation labels.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

IST = timezone(timedelta(hours=5, minutes=30))


def _at(day: int, hour: int, minute: int = 0) -> str:
    return datetime(2026, 9, day, hour, minute, tzinfo=IST).isoformat()


def _bucket(day: int, hour: int, minute: int, quantity: int, prefix: str, index: int) -> dict[str, Any]:
    start = datetime(2026, 9, day, hour, minute, tzinfo=IST)
    return {
        "id": f"{prefix}-{index}",
        "start": start.isoformat(),
        "end": (start + timedelta(minutes=15)).isoformat(),
        "quantity": quantity,
        "available_at": (_at(day, 8) if prefix == "plan" else (start + timedelta(minutes=15)).isoformat()),
        "kind": "final_good_delta" if prefix == "out" else "baseline_plan",
    }


def _base(incident_id: str, day: int, title: str, line: str, actual: list[int]) -> dict[str, Any]:
    times = [(9 + i // 4, (i % 4) * 15) for i in range(12)]
    return {
        "id": incident_id,
        "revision": 1,
        "title": title,
        "scope": {"factory": "Synthetic Factory A", "line_id": line, "order_id": f"ORD-{day}", "style_id": "ST-42", "stage": "sewing", "unit": "good_units"},
        "window": {"start": _at(day, 9), "end": _at(day, 12)},
        "cutoff": _at(day, 12),
        "plan_buckets": [_bucket(day, h, m, 20, "plan", i) for i, (h, m) in enumerate(times)],
        "output_buckets": [_bucket(day, h, m, q, "out", i) for i, ((h, m), q) in enumerate(zip(times, actual, strict=True))],
        "events": [],
        "coverage": {"production": True, "materials": False, "machines": False, "quality": False, "staffing": False, "notes": False},
    }


def incident_fixtures() -> list[dict[str, Any]]:
    hero = _base("INC-001", 28, "Delayed start on sewing line S4", "S4", [0, 0, 8, 17, 20, 20, 12, 10, 19, 20, 20, 20])
    hero["cutoff"] = _at(28, 11)
    hero["events"] = [
        {"id": "EV-MAT-1", "type": "material_readiness", "lane": "materials", "summary": "Fabric lot F-218 reached the line at 09:32, after the scheduled start.", "occurred_at": _at(28, 9, 32), "available_at": _at(28, 9, 38), "source_id": "material-transfer-218"},
        {"id": "EV-BLOCK-1", "type": "line_block", "lane": "production", "summary": "Supervisor recorded the line waiting for fabric from 09:00 to 09:30.", "start": _at(28, 9), "end": _at(28, 9, 30), "available_at": _at(28, 9, 40), "source_id": "shift-log-44", "assertion": True, "line_blocking": True, "linked_categories": ["material"]},
        {"id": "EV-START-1", "type": "line_start", "lane": "production", "summary": "First final good units recorded in the 09:30 bucket.", "occurred_at": _at(28, 9, 30), "available_at": _at(28, 9, 45), "source_id": "output-ledger-28"},
        {"id": "EV-MACH-1", "type": "machine_interruption", "lane": "machines", "summary": "Needle feed on machine M12 interrupted between 10:31 and 10:49; line-wide impact is not established.", "start": _at(28, 10, 31), "end": _at(28, 10, 49), "available_at": _at(28, 10, 55), "source_id": "machine-log-m12"},
        {"id": "EV-QC-1", "type": "qc_hold", "lane": "quality", "summary": "QC placed lot L-91 on hold pending seam inspection; held units are not added to good output.", "occurred_at": _at(28, 10, 42), "available_at": _at(28, 10, 50), "source_id": "qc-hold-l91"},
        {"id": "EV-MAINT-1", "type": "maintenance_note", "lane": "machines", "summary": "Technician reported that the feed issue began around 10:14; recorded later, with no confirmed line-stop duration.", "start": _at(28, 10, 10), "end": _at(28, 10, 20), "available_at": _at(28, 11, 20), "source_id": "maintenance-note-77", "assertion": True},
    ]
    hero["coverage"] = {"production": True, "materials": True, "machines": True, "quality": True, "staffing": False, "notes": False}
    later = {**hero, "revision": 2, "cutoff": _at(28, 11, 30), "events": [*hero["events"], {"id": "EV-MACH-CORR", "type": "machine_interruption", "lane": "machines", "summary": "Maintenance confirmed machine M12 was stopped from 10:31 to 10:49; other stations continued.", "start": _at(28, 10, 31), "end": _at(28, 10, 49), "available_at": _at(28, 11, 22), "source_id": "maintenance-confirmation-78", "supersedes_id": "EV-MACH-1"}]}
    cases = [
        ("INC-101", 10, "Late fabric transfer on line S2", "S2", [0, 0, 12, 20, 20, 20, 20, 20, 20, 20, 20, 20], "material_readiness", "Fabric transfer arrived at 09:28 after a warehouse queue.", "materials"),
        ("INC-102", 11, "Feed adjustment on line S3", "S3", [20, 20, 20, 20, 10, 8, 20, 20, 20, 20, 20, 20], "machine_interruption", "Machine M08 needed a feed adjustment; line stoppage was not documented.", "machines"),
        ("INC-103", 12, "QC hold on lot L-61", "S5", [20, 20, 20, 20, 20, 11, 10, 20, 20, 20, 20, 20], "qc_hold", "QC held lot L-61 for seam inspection while other lots continued.", "quality"),
        ("INC-104", 13, "Coverage gap at button operation", "S2", [20, 20, 14, 12, 15, 20, 20, 20, 20, 20, 20, 20], "staffing_event", "Button operation had no assigned trained operator between 09:30 and 10:10.", "staffing"),
        ("INC-105", 14, "Changeover ran beyond plan", "S1", [0, 8, 18, 20, 20, 20, 20, 20, 20, 20, 20, 20], "setup_changeover", "Style setup finished at 09:24 after the scheduled 09:00 start.", "production"),
        ("INC-106", 15, "Output ledger correction on line S6", "S6", [20] * 12, "reporting_correction", "An initial output upload omitted one bucket; corrected ledger shows normal production.", "production"),
        ("INC-107", 16, "Delayed WIP transfer on line S4", "S4", [0, 5, 16, 20, 20, 20, 20, 20, 20, 20, 20, 20], "material_readiness", "Cut panels reached line S4 after the planned start.", "materials"),
        ("INC-108", 17, "Intermittent machine alarm on line S3", "S3", [20, 20, 20, 14, 16, 20, 20, 20, 20, 20, 20, 20], "machine_interruption", "Operator recorded intermittent alarm on M03; production continued.", "machines"),
        ("INC-109", 18, "Lot held for QC disposition", "S7", [20, 20, 20, 20, 12, 12, 20, 20, 20, 20, 20, 20], "qc_hold", "Named lot L-82 awaited QC disposition; final good output remained separate.", "quality"),
        ("INC-110", 19, "Routine shift at baseline", "S8", [20] * 12, "routine_note", "No interruption was recorded and output met the baseline plan.", "production"),
    ]
    history = []
    for incident_id, day, title, line, actual, event_type, summary, lane in cases:
        item = _base(incident_id, day, title, line, actual)
        item["events"] = [{"id": f"{incident_id}-EV", "type": event_type, "lane": lane, "summary": summary, "occurred_at": _at(day, 9, 30), "available_at": _at(day, 10), "source_id": f"{incident_id}-source"}]
        item["coverage"][lane if lane != "production" else "notes"] = True
        history.append(item)
    return [hero, later, *history]
