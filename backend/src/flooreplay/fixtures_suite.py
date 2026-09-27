"""The 32-case operational evaluation suite.

Every case is a named scenario revision derived from the hero episode by a
targeted mutation, with an explicit statement of the defect it would catch
and per-configuration behavioral demands (expectations). Demands state the
desired behavior; the baseline configuration legitimately fails
healthy-coverage demands because of its documented overlap blind spot, and
the demonstration-defect configuration fails stale-evidence demands because
that is the regression it exists to exhibit.

Categories (launch suite):
  A  Supported coverage and deterministic selection      5
  B  Missing, stale, or incomplete evidence              7
  C  Conflicting facts and temporal applicability        5
  D  Candidate or resource constraints                   8
  E  Valid abstention versus insufficient context        3
  F  Historical replay and later review                  4
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from .domain.evaluation import Expectation
from .domain.types import (
    AssignmentRecord,
    AttendanceStatus,
    ConstraintCode,
    CoverageTarget,
    DomainOutcome,
    IssueCode,
    ReplayRequestContext,
    SkillRecord,
    Snapshot,
    SnapshotKind,
)
from .fixtures import (
    CATALOG,
    DECISION_AT,
    HERO_EVENT,
    HERO_TARGET,
    SHIFT_END,
    SHIFT_START,
    hero_snapshots_v1,
    hero_snapshots_v2,
)

IST = ZoneInfo("Asia/Kolkata")
BASELINE = "CFG-BASELINE-V1"
IMPROVED = "CFG-IMPROVED-V1"
DEFECT = "CFG-DEFECT-SKILLFRESH"

READY = DomainOutcome.READY_FOR_REVIEW
NEEDS = DomainOutcome.NEEDS_CONTEXT
CONFLICT = DomainOutcome.CONFLICTING_CONTEXT
NOFEAS = DomainOutcome.NO_FEASIBLE_CANDIDATE
REJECTED = DomainOutcome.REJECTED_BY_CONSTRAINT


def demand(
    outcome: DomainOutcome | None = None,
    operator: str | None = None,
    issues: tuple[IssueCode, ...] = (),
    failed: tuple[ConstraintCode, ...] = (),
    forbidden: tuple[str, ...] = (),
    no_policy: bool = False,
) -> Expectation:
    return Expectation(
        expected_outcome=outcome,
        required_operator=operator,
        required_issue_codes=issues,
        required_failed_constraints=failed,
        forbidden_operators=forbidden,
        policy_execution_permitted=False if no_policy else None,
    )


# The baseline's documented limitation: on a healthy pool it proposes the
# highest-skilled candidate even when occupied, and C07 rejects it.
LIMITATION = demand(REJECTED, failed=(ConstraintCode.C07,))


@dataclass(frozen=True)
class Case:
    sid: str
    title: str
    category: str
    tags: tuple[str, ...]
    defect_statement: str
    context: ReplayRequestContext
    demands: dict[str, Expectation]


# ---------------------------------------------------------------------------
# Mutation helpers. Each returns a full snapshots tuple with re-identified
# (case-tagged) snapshots; the original fixtures are never mutated.
# ---------------------------------------------------------------------------


def _reid(snap: Snapshot, case: str) -> Snapshot:
    return snap.model_copy(update={"id": f"SNAP-{snap.kind.value[:4]}-{case}"})


def _replace(
    snaps: tuple[Snapshot, ...],
    kind: SnapshotKind,
    case: str,
    mutate: Callable[[Snapshot], Snapshot],
) -> tuple[Snapshot, ...]:
    out = []
    for snap in snaps:
        if snap.kind is kind:
            out.append(mutate(_reid(snap, case)))
        else:
            out.append(_reid(snap, case))
    return tuple(out)


def attendance(
    snaps: tuple[Snapshot, ...],
    case: str,
    *,
    statuses: dict[str, AttendanceStatus] | None = None,
    unknown_rows: tuple[str, ...] = (),
    drop: tuple[str, ...] = (),
    declared: datetime | None = None,
    complete: bool | None = None,
    duplicate_conflict: str | None = None,
) -> tuple[Snapshot, ...]:
    def mutate(snap: Snapshot) -> Snapshot:
        assert snap.attendance is not None
        rows = []
        for rec in snap.attendance:
            if rec.operator_id in (drop or ()):  # dropped entirely
                continue
            status = (statuses or {}).get(rec.operator_id, rec.status)
            if rec.operator_id in unknown_rows:
                status = AttendanceStatus.UNKNOWN
            rows.append(rec.model_copy(update={"status": status}))
        if duplicate_conflict:
            victim = next(
                r for r in snap.attendance if r.operator_id == duplicate_conflict
            )
            rows.append(victim.model_copy(update={"status": AttendanceStatus.ABSENT, "source_ref": "row:99"}))
        return snap.model_copy(
            update={
                "attendance": tuple(rows),
                "declared_evidence_at": declared or snap.declared_evidence_at,
                "coverage_complete": snap.coverage_complete if complete is None else complete,
            }
        )

    return _replace(snaps, SnapshotKind.ATTENDANCE, case, mutate)


def skills(
    snaps: tuple[Snapshot, ...],
    case: str,
    *,
    levels: dict[str, int] | None = None,
    all_levels: int | None = None,
    assessed: datetime | None = None,
    assessed_for: dict[str, datetime] | None = None,
    drop_operation: str | None = None,
    drop_for: tuple[str, ...] = (),
    keep_only: tuple[str, ...] | None = None,
    duplicate_conflict: tuple[str, str] | None = None,
    full_matrix: bool = False,
) -> tuple[Snapshot, ...]:
    def mutate(snap: Snapshot) -> Snapshot:
        assert snap.skills is not None
        rows = []
        if full_matrix:
            # A complete skill matrix: every operator has an OP-SLM row, so
            # low levels are conclusive exclusions rather than unknowns.
            have = {
                r.operator_id
                for r in snap.skills
                if r.operation_id == "OP-SLM"
            }
            any_slm = next(
                (r for r in snap.skills if r.operation_id == "OP-SLM"), None
            )
            if any_slm is not None:
                from .fixtures import OPERATORS

                for op in OPERATORS:
                    if op.id not in have:
                        rows.append(
                            SkillRecord(
                                operator_id=op.id,
                                operation_id="OP-SLM",
                                level=1,
                                assessed_at=any_slm.assessed_at,
                                source_ref="row:matrix",
                            )
                        )
        for rec in snap.skills:
            if drop_operation and rec.operation_id == drop_operation:
                continue
            if drop_for and rec.operator_id in drop_for and rec.operation_id == "OP-SLM":
                continue
            if keep_only is not None and rec.operation_id == "OP-SLM" and rec.operator_id not in keep_only:
                continue
            update: dict[str, object] = {}
            if all_levels is not None:
                update["level"] = all_levels
            elif levels is not None and rec.operator_id in levels and rec.operation_id == "OP-SLM":
                update["level"] = levels[rec.operator_id]
            new_time = (assessed_for or {}).get(rec.operator_id)
            update["assessed_at"] = new_time or assessed or rec.assessed_at
            rows.append(rec.model_copy(update=update))
        if duplicate_conflict:
            op_id, operation_id = duplicate_conflict
            victim = next(
                r
                for r in snap.skills
                if r.operator_id == op_id and r.operation_id == operation_id
            )
            rows.append(victim.model_copy(update={"level": victim.level - 1, "source_ref": "row:98"}))
        return snap.model_copy(update={"skills": tuple(rows)})

    return _replace(snaps, SnapshotKind.SKILLS, case, mutate)


def assignments(
    snaps: tuple[Snapshot, ...],
    case: str,
    *,
    occupy: dict[str, tuple[int, int]] | None = None,  # operator -> (start_h, end_h)
    unslotted_machine_reservation: tuple[str, int, int, str] | None = None,  # op, start_h, end_h, machine
    touching_end: tuple[str, int] | None = None,  # operator, end_h (assignment ending exactly at shift start)
    complete: bool | None = None,
) -> tuple[Snapshot, ...]:
    def mutate(snap: Snapshot) -> Snapshot:
        assert snap.assignments is not None
        rows = list(snap.assignments)
        for op_id, (start_h, end_h) in (occupy or {}).items():
            rows.append(
                AssignmentRecord(
                    operator_id=op_id,
                    slot_id=None,
                    machine_id=None,
                    starts_at=datetime(2026, 9, 22, start_h, tzinfo=IST),
                    ends_at=datetime(2026, 9, 22, end_h, tzinfo=IST),
                    source_ref="row:90",
                )
            )
        if unslotted_machine_reservation:
            op_id, start_h, end_h, machine = unslotted_machine_reservation
            rows.append(
                AssignmentRecord(
                    operator_id=op_id,
                    slot_id=None,
                    machine_id=machine,
                    starts_at=datetime(2026, 9, 22, start_h, tzinfo=IST),
                    ends_at=datetime(2026, 9, 22, end_h, tzinfo=IST),
                    source_ref="row:91",
                )
            )
        if touching_end:
            op_id, end_h = touching_end
            rows.append(
                AssignmentRecord(
                    operator_id=op_id,
                    slot_id=None,
                    machine_id=None,
                    starts_at=datetime(2026, 9, 22, end_h - 2, tzinfo=IST),
                    ends_at=datetime(2026, 9, 22, end_h, tzinfo=IST),
                    source_ref="row:92",
                )
            )
        return snap.model_copy(
            update={
                "assignments": tuple(rows),
                "coverage_complete": snap.coverage_complete if complete is None else complete,
            }
        )

    return _replace(snaps, SnapshotKind.ASSIGNMENTS, case, mutate)


def machine_state(
    snaps: tuple[Snapshot, ...], case: str, *, unusable: tuple[str, ...] = ()
) -> tuple[Snapshot, ...]:
    def mutate(snap: Snapshot) -> Snapshot:
        assert snap.machine_state is not None
        rows = [
            (
                rec.model_copy(update={"usable": False, "detail": "flagged down in fixture"})
                if rec.machine_id in unusable
                else rec
            )
            for rec in snap.machine_state
        ]
        return snap.model_copy(update={"machine_state": tuple(rows)})

    return _replace(snaps, SnapshotKind.MACHINE_STATE, case, mutate)


def plan(snaps: tuple[Snapshot, ...], case: str, *, verified_hour: int | None = None) -> tuple[Snapshot, ...]:
    def mutate(snap: Snapshot) -> Snapshot:
        assert snap.plan is not None
        update: dict[str, object] = {}
        if verified_hour is not None:
            update["verified_at"] = datetime(2026, 9, 22, verified_hour, 0, tzinfo=IST)
        return snap.model_copy(update={"plan": snap.plan.model_copy(update=update)})

    return _replace(snaps, SnapshotKind.PLAN, case, mutate)


def _ctx(
    snaps: tuple[Snapshot, ...], *, target: CoverageTarget | None = None
) -> ReplayRequestContext:
    return ReplayRequestContext(
        catalog=CATALOG,
        snapshots=snaps,
        event=HERO_EVENT,
        decision_at=DECISION_AT,
        target=target or HERO_TARGET,
    )


def _case(
    sid: str,
    title: str,
    category: str,
    tags: tuple[str, ...],
    defect_statement: str,
    snaps: tuple[Snapshot, ...],
    improved: Expectation,
    baseline: Expectation | str = "limitation",
    defect: Expectation | str = "same",
    target: CoverageTarget | None = None,
) -> Case:
    def _resolve(spec: Expectation | str) -> Expectation:
        if isinstance(spec, str):
            return LIMITATION if spec == "limitation" else improved
        return spec

    resolved: dict[str, Expectation] = {
        BASELINE: _resolve(baseline),
        IMPROVED: improved,
        DEFECT: _resolve(defect),
    }
    return Case(
        sid=sid,
        title=title,
        category=category,
        tags=tags,
        defect_statement=defect_statement,
        context=_ctx(snaps, target=target),
        demands=resolved,
    )


# ---------------------------------------------------------------------------
# A. Supported coverage and deterministic selection (5)
# ---------------------------------------------------------------------------

ABSENT_204 = {"O204": AttendanceStatus.ABSENT}


def _cases_a() -> list[Case]:
    v2 = hero_snapshots_v2()
    return [
        _case(
            "SUITE-A1",
            "Supported coverage with deterministic selection",
            "A",
            ("suite", "deterministic-selection"),
            "Catches ranking regressions: the same evidence must always propose the same supported operator.",
            v2,
            improved=demand(READY, operator="O219"),
        ),
        _case(
            "SUITE-A2",
            "Tied candidates resolve by canonical operator id",
            "A",
            ("suite", "tie-break"),
            "Catches unstable tie-breaking that flips proposals between equivalent operators.",
            attendance(skills(v2, "K-A2", levels={"O130": 3, "O215": 3}), "A2", statuses={**ABSENT_204, "O219": AttendanceStatus.ABSENT, "O112": AttendanceStatus.ABSENT, "O145": AttendanceStatus.ABSENT}),
            improved=demand(READY, operator="O130"),
            baseline="same",
        ),
        _case(
            "SUITE-A3",
            "Higher skill outranks same-line preference",
            "A",
            ("suite", "ranking-order"),
            "Catches a ranking that lets line preference beat skill level.",
            attendance(skills(v2, "K-A3", levels={"O152": 2}), "A3", statuses={**ABSENT_204, "O219": AttendanceStatus.ABSENT}),
            improved=demand(READY, operator="O112"),
            baseline="same",
        ),
        _case(
            "SUITE-A4",
            "Higher skill level wins within the same line",
            "A",
            ("suite", "ranking-order"),
            "Catches a ranking that ignores skill level among same-line candidates.",
            attendance(skills(v2, "K-A4", levels={"O152": 4}), "A4", statuses=ABSENT_204),
            improved=demand(READY, operator="O152"),
            baseline="same",
        ),
        _case(
            "SUITE-A5",
            "Partial coverage interval inside the slot",
            "A",
            ("suite", "partial-interval"),
            "Catches interval validation that rejects valid sub-intervals of the vacant slot.",
            v2,
            improved=demand(READY, operator="O219"),
            target=CoverageTarget(
                line_id="L4",
                slot_id="L4-SLM-1",
                machine_id="SN-4407",
                starts_at=datetime(2026, 9, 22, 9, 0, tzinfo=IST),
                ends_at=datetime(2026, 9, 22, 12, 0, tzinfo=IST),
            ),
        ),
    ]


# ---------------------------------------------------------------------------
# B. Missing, stale, or incomplete evidence (7)
# ---------------------------------------------------------------------------


def _cases_b() -> list[Case]:
    v2 = hero_snapshots_v2()
    return [
        _case(
            "SUITE-B1",
            "Stale skill evidence blocks every policy",
            "B",
            ("suite", "evidence-freshness"),
            "Catches a policy that runs on skill evidence older than the freshness budget.",
            hero_snapshots_v1(),
            improved=demand(NEEDS, issues=(IssueCode.SKILL_STALE,), no_policy=True),
            baseline="same",
        ),
        _case(
            "SUITE-B2",
            "Attendance snapshot beyond its freshness budget",
            "B",
            ("suite", "evidence-freshness"),
            "Catches a gate that trusts an attendance export older than five minutes.",
            attendance(v2, "B2", declared=datetime(2026, 9, 22, 7, 52, tzinfo=IST)),
            improved=demand(NEEDS, issues=(IssueCode.ATTENDANCE_STALE,), no_policy=True),
            baseline="same",
        ),
        _case(
            "SUITE-B3",
            "Assignments export does not assert complete coverage",
            "B",
            ("suite", "coverage-assertion"),
            "Catches a gate that reads 'no assignment row' as 'free' from an incomplete export.",
            assignments(v2, "B3", complete=False),
            improved=demand(NEEDS, issues=(IssueCode.ASSIGNMENTS_SCOPE_INCOMPLETE,), no_policy=True),
            baseline="same",
        ),
        _case(
            "SUITE-B4",
            "Machine-state snapshot beyond its freshness budget",
            "B",
            ("suite", "evidence-freshness"),
            "Catches a validator that accepts machine usability from a stale board.",
            _replace(
                v2,
                SnapshotKind.MACHINE_STATE,
                "B4",
                lambda s: s.model_copy(
                    update={
                        "declared_evidence_at": datetime(2026, 9, 22, 7, 40, tzinfo=IST),
                        "machine_state": tuple(
                            r.model_copy(update={"observed_at": datetime(2026, 9, 22, 7, 40, tzinfo=IST)})
                            for r in (s.machine_state or ())
                        ),
                    }
                ),
            ),
            improved=demand(NEEDS, issues=(IssueCode.MACHINE_STATE_STALE,), no_policy=True),
            baseline="same",
        ),
        _case(
            "SUITE-B5",
            "Plan verification older than four hours",
            "B",
            ("suite", "evidence-freshness"),
            "Catches a gate that replays against a plan nobody verified recently.",
            plan(v2, "B5", verified_hour=3),
            improved=demand(NEEDS, issues=(IssueCode.PLAN_STALE,), no_policy=True),
            baseline="same",
        ),
        _case(
            "SUITE-B6",
            "Unknown attendance for the only idle skilled candidate",
            "B",
            ("suite", "unknown-not-absent"),
            "Closes the trap of reading a missing/blank attendance scan as absent and proceeding.",
            attendance(v2, "B6", unknown_rows=("O219",), statuses={"O112": AttendanceStatus.ABSENT, "O145": AttendanceStatus.ABSENT}),
            improved=demand(NEEDS, issues=(IssueCode.ATTENDANCE_UNKNOWN,)),
        ),
        _case(
            "SUITE-B7",
            "No skill rows at all for the target operation",
            "B",
            ("suite", "unknown-not-zero"),
            "Catches a gate that treats missing skill records as level zero and concludes exclusion.",
            skills(v2, "B7", drop_operation="OP-SLM"),
            improved=demand(NEEDS, issues=(IssueCode.SKILL_UNKNOWN,), no_policy=True),
            baseline="same",
        ),
    ]


# ---------------------------------------------------------------------------
# C. Conflicting facts and temporal applicability (5)
# ---------------------------------------------------------------------------


def _cases_c() -> list[Case]:
    v2 = hero_snapshots_v2()
    return [
        _case(
            "SUITE-C1",
            "Contradictory attendance rows for one operator",
            "C",
            ("suite", "contradiction"),
            "Catches silent last-write-wins on two incompatible attendance assertions.",
            attendance(v2, "C1", duplicate_conflict="O219"),
            improved=demand(CONFLICT, issues=(IssueCode.CONTRADICTORY_ASSERTIONS,), no_policy=True),
            baseline="same",
        ),
        _case(
            "SUITE-C2",
            "Contradictory skill levels at the same assessment instant",
            "C",
            ("suite", "contradiction"),
            "Catches averaging or pick-first on conflicting skill evidence.",
            skills(v2, "C2", duplicate_conflict=("O219", "OP-SLM")),
            improved=demand(CONFLICT, issues=(IssueCode.CONTRADICTORY_ASSERTIONS,), no_policy=True),
            baseline="same",
        ),
        _case(
            "SUITE-C3",
            "Attendance evidence declared after the decision time",
            "C",
            ("suite", "future-evidence"),
            "Catches replays that use facts nobody could have known at decision time.",
            attendance(v2, "C3", declared=datetime(2026, 9, 22, 8, 5, tzinfo=IST)),
            improved=demand(NEEDS, issues=(IssueCode.FUTURE_EVIDENCE,), no_policy=True),
            baseline="same",
        ),
        _case(
            "SUITE-C4",
            "Skill assessed after the decision time for one candidate",
            "C",
            ("suite", "future-evidence", "isolation"),
            "Catches one operator's future-dated record blocking or poisoning the whole pool.",
            skills(v2, "C4", assessed_for={"O219": datetime(2026, 9, 22, 9, 0, tzinfo=IST)}),
            improved=demand(READY, operator="O112"),
        ),
        _case(
            "SUITE-C5",
            "Assignment ending exactly at coverage start is not an overlap",
            "C",
            ("suite", "half-open-intervals"),
            "Catches closed-interval overlap math that excludes a candidate who is free at 08:00.",
            assignments(v2, "C5", touching_end=("O219", 8)),
            improved=demand(READY, operator="O219"),
        ),
    ]


# ---------------------------------------------------------------------------
# D. Candidate or resource constraints (8)
# ---------------------------------------------------------------------------


def _cases_d() -> list[Case]:
    v2 = hero_snapshots_v2()
    return [
        _case(
            "SUITE-D1",
            "All skilled candidates absent: conclusive abstention",
            "D",
            ("suite", "abstention"),
            "Catches a policy that invents coverage when every skilled operator is absent.",
            attendance(skills(v2, "K-D1", full_matrix=True), "D1", statuses={"O219": AttendanceStatus.ABSENT, "O112": AttendanceStatus.ABSENT, "O145": AttendanceStatus.ABSENT}),
            improved=demand(NOFEAS),
        ),
        _case(
            "SUITE-D2",
            "All skilled candidates already assigned",
            "D",
            ("suite", "abstention", "overlap"),
            "Catches a policy that reassigns occupied operators instead of abstaining.",
            assignments(skills(v2, "K-D2", full_matrix=True), "D2", occupy={"O219": (8, 16), "O112": (8, 16), "O145": (8, 16)}),
            improved=demand(NOFEAS),
        ),
        _case(
            "SUITE-D3",
            "No candidate meets the required skill level",
            "D",
            ("suite", "abstention", "skill"),
            "Catches level inflation that proposes an unqualified operator.",
            skills(v2, "D3", all_levels=2, full_matrix=True),
            improved=demand(NOFEAS),
            baseline="same",
        ),
        _case(
            "SUITE-D4",
            "Only the unavailable subject is qualified",
            "D",
            ("suite", "abstention", "unavailable-subject"),
            "Catches a policy that proposes the very operator reported unavailable.",
            skills(v2, "D4", all_levels=2, levels={"O117": 3}, full_matrix=True),
            improved=demand(NOFEAS, forbidden=("O117",)),
            baseline="same",
        ),
        _case(
            "SUITE-D5",
            "Designated machine recorded unusable",
            "D",
            ("suite", "machine"),
            "Catches proposals onto a machine the maintenance board flags down.",
            machine_state(v2, "D5", unusable=("SN-4407",)),
            improved=demand(NOFEAS, issues=(IssueCode.TARGET_MACHINE_UNUSABLE,)),
            baseline="same",
        ),
        _case(
            "SUITE-D6",
            "Designated machine incompatible with the operation",
            "D",
            ("suite", "machine"),
            "Catches machine substitution or compatibility checks that trust the plan blindly.",
            v2,
            improved=demand(NOFEAS, issues=(IssueCode.TARGET_MACHINE_UNUSABLE,)),
            baseline="same",
            target=CoverageTarget(
                line_id="L4",
                slot_id="L4-SLM-1",
                machine_id="BT-3305",
                starts_at=SHIFT_START,
                ends_at=SHIFT_END,
            ),
        ),
        _case(
            "SUITE-D7",
            "Machine reserved by an unslotted maintenance assignment",
            "D",
            ("suite", "machine-reservation"),
            "Catches double-booking the designated machine when the reservation is not on the target slot.",
            assignments(v2, "D7", unslotted_machine_reservation=("O210", 8, 16, "SN-4407")),
            improved=demand(REJECTED, failed=(ConstraintCode.C10,)),
            baseline=demand(REJECTED, failed=(ConstraintCode.C10,)),
        ),
        _case(
            "SUITE-D8",
            "The unavailable subject is never proposed",
            "D",
            ("suite", "unavailable-subject"),
            "Catches eligibility that ignores the episode's confirmed unavailability event.",
            v2,
            improved=demand(READY, operator="O219", forbidden=("O117",)),
        ),
    ]


# ---------------------------------------------------------------------------
# E. Valid abstention versus insufficient context (3)
# ---------------------------------------------------------------------------


def _cases_e() -> list[Case]:
    v2 = hero_snapshots_v2()
    return [
        _case(
            "SUITE-E1",
            "One unknown attendance does not block a supported candidate",
            "E",
            ("suite", "isolation"),
            "Catches a gate that blocks the whole replay because one unrelated record is unknown.",
            attendance(v2, "E1", unknown_rows=("O219",)),
            improved=demand(READY, operator="O112"),
        ),
        _case(
            "SUITE-E2",
            "One stale skill does not block a fresh candidate",
            "E",
            ("suite", "isolation", "evidence-freshness"),
            "Catches a gate that requires every operator's evidence to be fresh, not the pool's.",
            skills(v2, "E2", assessed_for={"O219": datetime(2026, 8, 8, 15, 0, tzinfo=IST)}),
            improved=demand(READY, operator="O112"),
            defect=demand(READY, operator="O219"),
        ),
        _case(
            "SUITE-E3",
            "Material unknowns with no supported candidate need context",
            "E",
            ("suite", "abstention-vs-context"),
            "Catches a conclusive NO_FEASIBLE_CANDIDATE when missing evidence could conceal a candidate.",
            attendance(
                skills(v2, "E3", assessed_for={"O145": datetime(2026, 8, 8, 15, 0, tzinfo=IST)}),
                "E3",
                unknown_rows=("O112",),
                statuses={"O219": AttendanceStatus.ABSENT},
            ),
            improved=demand(NEEDS),
        ),
    ]


# ---------------------------------------------------------------------------
# F. Historical replay and later review (4)
# ---------------------------------------------------------------------------


def _cases_f() -> list[Case]:
    v2 = hero_snapshots_v2()
    return [
        _case(
            "SUITE-F1",
            "Historical revision still replays its historical outcome",
            "F",
            ("suite", "immutability"),
            "Catches retroactive rewriting: newer evidence in the database must not change old results.",
            hero_snapshots_v1(),
            improved=demand(NEEDS, issues=(IssueCode.SKILL_STALE,), no_policy=True),
            baseline="same",
        ),
        _case(
            "SUITE-F2",
            "Corrected evidence changes the outcome on a new revision",
            "F",
            ("suite", "correction"),
            "Catches corrections that fail to unblock a replay, or that mutate the old revision.",
            v2,
            improved=demand(READY, operator="O219"),
        ),
        _case(
            "SUITE-F3",
            "Repeated replay of the same manifest is deterministic",
            "F",
            ("suite", "determinism"),
            "Catches hidden nondeterminism: same pinned inputs must yield the same proposal.",
            v2,
            improved=demand(READY, operator="O219"),
        ),
        _case(
            "SUITE-F4",
            "Relaxed freshness regression is caught by the suite",
            "F",
            ("suite", "regression-detection"),
            "The demonstration defect must fail this demand: it lets stale evidence through the gate.",
            hero_snapshots_v1(),
            improved=demand(NEEDS, issues=(IssueCode.SKILL_STALE,), no_policy=True),
            baseline="same",
            defect=demand(NEEDS, issues=(IssueCode.SKILL_STALE,), no_policy=True),
        ),
    ]


SUITE_ID = "SUITE-OPS-V1"


def suite_cases() -> list[Case]:
    return [*_cases_a(), *_cases_b(), *_cases_c(), *_cases_d(), *_cases_e(), *_cases_f()]

