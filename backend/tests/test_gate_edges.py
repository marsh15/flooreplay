"""Gate edge cases: freshness boundaries, coverage, contradictions, conflicts."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from flooreplay.domain.engine import run_replay
from flooreplay.domain.types import (
    AttendanceStatus,
    DomainOutcome,
    IssueCode,
    Snapshot,
)
from flooreplay.fixtures import DEFAULT_FRESHNESS

IST = ZoneInfo("Asia/Kolkata")


def _with_snapshot(ctx, replacement: Snapshot) -> object:
    return ctx.model_copy(
        update={
            "snapshots": tuple(
                replacement if s.kind == replacement.kind else s for s in ctx.snapshots
            )
        }
    )


def test_freshness_exact_boundary_is_fresh(hero_v2):
    attendance = next(s for s in hero_v2.snapshots if s.kind.value == "ATTENDANCE")
    exactly_5min = attendance.model_copy(
        update={"declared_evidence_at": datetime(2026, 9, 22, 7, 53, tzinfo=IST)}
    )
    result = run_replay(
        _with_snapshot(hero_v2, exactly_5min),
        DEFAULT_FRESHNESS,
        "improved-v1",
    ).outcome
    assert result.outcome is not DomainOutcome.NEEDS_CONTEXT


def test_freshness_one_beyond_boundary_blocks(hero_v2):
    attendance = next(s for s in hero_v2.snapshots if s.kind.value == "ATTENDANCE")
    stale = attendance.model_copy(
        update={"declared_evidence_at": datetime(2026, 9, 22, 7, 52, 59, tzinfo=IST)}
    )
    result = run_replay(_with_snapshot(hero_v2, stale), DEFAULT_FRESHNESS, "improved-v1").outcome
    assert result.outcome is DomainOutcome.NEEDS_CONTEXT
    assert IssueCode.ATTENDANCE_STALE in {i.code for i in result.gate_issues}


def test_future_evidence_blocks(hero_v2):
    attendance = next(s for s in hero_v2.snapshots if s.kind.value == "ATTENDANCE")
    future = attendance.model_copy(
        update={"declared_evidence_at": datetime(2026, 9, 22, 8, 5, tzinfo=IST)}
    )
    result = run_replay(_with_snapshot(hero_v2, future), DEFAULT_FRESHNESS, "improved-v1").outcome
    assert result.outcome is DomainOutcome.NEEDS_CONTEXT
    assert IssueCode.FUTURE_EVIDENCE in {i.code for i in result.gate_issues}


def test_incomplete_assignments_coverage_blocks(hero_v2):
    assignments = next(s for s in hero_v2.snapshots if s.kind.value == "ASSIGNMENTS")
    incomplete = assignments.model_copy(update={"coverage_complete": False})
    result = run_replay(
        _with_snapshot(hero_v2, incomplete), DEFAULT_FRESHNESS, "improved-v1"
    ).outcome
    assert result.outcome is DomainOutcome.NEEDS_CONTEXT
    assert IssueCode.ASSIGNMENTS_SCOPE_INCOMPLETE in {i.code for i in result.gate_issues}


def test_attendance_roster_gap_blocks(hero_v2):
    attendance = next(s for s in hero_v2.snapshots if s.kind.value == "ATTENDANCE")
    gapped = attendance.model_copy(
        update={"attendance": attendance.attendance[:-2]}  # drop two operators' rows
    )
    result = run_replay(_with_snapshot(hero_v2, gapped), DEFAULT_FRESHNESS, "improved-v1").outcome
    assert IssueCode.ATTENDANCE_ROSTER_GAP in {i.code for i in result.gate_issues}


def test_contradictory_attendance_rows_conflict(hero_v2):
    attendance = next(s for s in hero_v2.snapshots if s.kind.value == "ATTENDANCE")
    rows = list(attendance.attendance)
    o219_row = next(r for r in rows if r.operator_id == "O219")
    rows.append(
        o219_row.model_copy(update={"status": AttendanceStatus.ABSENT, "source_ref": "row:40"})
    )
    contradiction = attendance.model_copy(update={"attendance": tuple(rows)})
    result = run_replay(
        _with_snapshot(hero_v2, contradiction), DEFAULT_FRESHNESS, "improved-v1"
    ).outcome
    assert result.outcome is DomainOutcome.CONFLICTING_CONTEXT
    assert IssueCode.CONTRADICTORY_ASSERTIONS in {i.code for i in result.gate_issues}


def test_missing_attendance_row_is_unknown_not_absent(hero_v2):
    attendance = next(s for s in hero_v2.snapshots if s.kind.value == "ATTENDANCE")
    rows = list(attendance.attendance)
    idx = next(i for i, r in enumerate(rows) if r.operator_id == "O112")
    rows[idx] = rows[idx].model_copy(update={"status": AttendanceStatus.UNKNOWN})
    unknown = attendance.model_copy(update={"attendance": tuple(rows)})
    # O112 becomes material-unknown; O219 remains supported, so the replay
    # still runs. A bad record for one operator must not block another.
    result = run_replay(_with_snapshot(hero_v2, unknown), DEFAULT_FRESHNESS, "improved-v1").outcome
    assert result.proposal is not None
    assert result.proposal.operator_id == "O219"


def test_attendance_history_latest_row_wins_regardless_of_order(hero_v2):
    """Row order in an export must never decide which evidence counts."""
    attendance = next(s for s in hero_v2.snapshots if s.kind.value == "ATTENDANCE")
    o219 = next(r for r in attendance.attendance if r.operator_id == "O219")
    earlier_absent = o219.model_copy(
        update={
            "status": AttendanceStatus.ABSENT,
            "observed_at": datetime(2026, 9, 22, 7, 40, tzinfo=IST),
            "source_ref": "row:40",
        }
    )
    later_present = o219.model_copy(
        update={"observed_at": datetime(2026, 9, 22, 7, 50, tzinfo=IST), "source_ref": "row:41"}
    )
    outcomes = []
    for history in ((earlier_absent, later_present), (later_present, earlier_absent)):
        rows = [r for r in attendance.attendance if r.operator_id != "O219"]
        reordered = attendance.model_copy(update={"attendance": tuple(rows + list(history))})
        result = run_replay(
            _with_snapshot(hero_v2, reordered), DEFAULT_FRESHNESS, "improved-v1"
        ).outcome
        outcomes.append((result.outcome, result.proposal.operator_id if result.proposal else None))
    assert outcomes[0] == outcomes[1]
    assert outcomes[0] == (DomainOutcome.READY_FOR_REVIEW, "O219")


def test_skill_history_latest_assessment_wins_regardless_of_order(hero_v2):
    skills = next(s for s in hero_v2.snapshots if s.kind.value == "SKILLS")
    o219 = next(r for r in skills.skills if r.operator_id == "O219" and r.operation_id == "OP-SLM")
    stale_low = o219.model_copy(
        update={
            "level": 1,
            "assessed_at": datetime(2026, 8, 8, 15, 0, tzinfo=IST),
            "source_ref": "row:60",
        }
    )
    fresh_high = o219  # level 3, assessed 2026-09-18
    outcomes = []
    for history in ((stale_low, fresh_high), (fresh_high, stale_low)):
        rows = [
            r
            for r in skills.skills
            if not (r.operator_id == "O219" and r.operation_id == "OP-SLM")
        ]
        reordered = skills.model_copy(update={"skills": tuple(rows + list(history))})
        result = run_replay(
            _with_snapshot(hero_v2, reordered), DEFAULT_FRESHNESS, "improved-v1"
        ).outcome
        outcomes.append((result.outcome, result.proposal.operator_id if result.proposal else None))
    assert outcomes[0] == outcomes[1]
    assert outcomes[0] == (DomainOutcome.READY_FOR_REVIEW, "O219")


def test_future_attendance_row_never_supports_a_proposal(hero_v2):
    from flooreplay.domain.gate import evaluate_gate

    attendance = next(s for s in hero_v2.snapshots if s.kind.value == "ATTENDANCE")
    rows = list(attendance.attendance)
    idx = next(i for i, r in enumerate(rows) if r.operator_id == "O219")
    rows[idx] = rows[idx].model_copy(
        update={"observed_at": datetime(2026, 9, 22, 8, 30, tzinfo=IST)}
    )
    future = attendance.model_copy(update={"attendance": tuple(rows)})
    ctx = _with_snapshot(hero_v2, future)
    gate = evaluate_gate(ctx, DEFAULT_FRESHNESS)  # type: ignore[arg-type]
    finding = next(f for f in gate.candidates if f.operator_id == "O219")
    assert IssueCode.FUTURE_EVIDENCE in {i.code for i in finding.issues}
    assert not finding.evidence_supported

    # And independent validation fails such a proposal on C02 exactly as it
    # fails future-dated skills on C05, whichever policy proposed it.
    from flooreplay.domain.validator import validate_proposal

    proposal = run_replay(hero_v2, DEFAULT_FRESHNESS, "improved-v1").outcome.proposal
    assert proposal is not None and proposal.operator_id == "O219"
    constraints = validate_proposal(proposal, ctx, DEFAULT_FRESHNESS, proposal.context_digest)
    c02 = next(c for c in constraints if c.code.value == "C02")
    assert c02.verdict.value == "FAIL"
    assert c02.reason_code == "FUTURE_EVIDENCE"
