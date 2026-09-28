"""Synthetic fixture factory: the bounded demo world.

One small garment unit in Asia/Kolkata, two lines, ~20 operators, two
styles, eight operations, individually identified machines. All data is
synthetic and labeled as such. The hero episode:

- Decision time 07:58 IST on 2026-09-22, shift 08:00-16:30.
- O117 (R. Balamurugan) cannot cover sleeve attachment on Line 4.
- With stale skill evidence the gate reports NEEDS_CONTEXT.
- With corrected (fresh) skill evidence:
  * the baseline policy proposes O204, who is occupied on Line 3 and is
    rejected by constraint C07;
  * the improved policy proposes O219 (K. Nakul), who is idle and skilled.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from flooreplay.domain.types import (
    AssignmentRecord,
    AttendanceRecord,
    AttendanceStatus,
    Catalog,
    ConstraintCode,
    CoverageTarget,
    GateFreshnessSettings,
    IssueCode,
    Line,
    Machine,
    MachineStateRecord,
    OperationDef,
    Operator,
    PlanSnapshotPayload,
    ReplayRequestContext,
    SkillRecord,
    Slot,
    Snapshot,
    SnapshotKind,
    Style,
    UnavailabilityEvent,
)

IST = ZoneInfo("Asia/Kolkata")
FACTORY_DATE = datetime(2026, 9, 22, tzinfo=IST)


def ist(hour: int, minute: int, day: int = 22) -> datetime:
    return datetime(2026, 9, day, hour, minute, tzinfo=IST)


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------

OPERATIONS = (
    OperationDef(id="OP-CUT", name="Fabric cut", required_skill_level=2),
    OperationDef(id="OP-SLM", name="Sleeve attach", required_skill_level=3),
    OperationDef(id="OP-COL", name="Collar join", required_skill_level=3),
    OperationDef(id="OP-SHD", name="Shoulder seam", required_skill_level=2),
    OperationDef(id="OP-HLM", name="Hem lock", required_skill_level=2),
    OperationDef(id="OP-BTK", name="Bar-tack", required_skill_level=3),
    OperationDef(id="OP-INP", name="Inspection", required_skill_level=2),
    OperationDef(id="OP-PKG", name="Pack", required_skill_level=1),
)

SINGLE_NEEDLE_OPS = ("OP-SLM", "OP-COL", "OP-SHD")
MACHINES = (
    Machine(id="SN-4401", kind="single-needle", compatible_operation_ids=SINGLE_NEEDLE_OPS),
    Machine(id="SN-4402", kind="single-needle", compatible_operation_ids=SINGLE_NEEDLE_OPS),
    Machine(id="SN-4403", kind="single-needle", compatible_operation_ids=SINGLE_NEEDLE_OPS),
    Machine(id="SN-4404", kind="single-needle", compatible_operation_ids=SINGLE_NEEDLE_OPS),
    Machine(id="SN-4405", kind="single-needle", compatible_operation_ids=SINGLE_NEEDLE_OPS),
    Machine(id="SN-4406", kind="single-needle", compatible_operation_ids=SINGLE_NEEDLE_OPS),
    Machine(id="SN-4407", kind="single-needle", compatible_operation_ids=SINGLE_NEEDLE_OPS),
    Machine(id="OL-2210", kind="overlock", compatible_operation_ids=("OP-HLM", "OP-SHD")),
    Machine(id="BT-3305", kind="bar-tack", compatible_operation_ids=("OP-BTK",)),
    Machine(id="IN-1102", kind="inspection table", compatible_operation_ids=("OP-INP",)),
    Machine(id="PK-2210", kind="pack table", compatible_operation_ids=("OP-PKG",)),
    Machine(id="CUT-0101", kind="cutting table", compatible_operation_ids=("OP-CUT",)),
)

OPERATORS = (
    Operator(id="O101", display_name="M. Arivazhagan", home_line_id="L3"),
    Operator(id="O108", display_name="S. Deepika", home_line_id="L3"),
    Operator(id="O112", display_name="T. Ilango", home_line_id="L3"),
    Operator(id="O117", display_name="R. Balamurugan", home_line_id="L4"),
    Operator(id="O121", display_name="V. Karpagam", home_line_id="L3"),
    Operator(id="O126", display_name="N. Selvaraj", home_line_id="L3"),
    Operator(id="O130", display_name="A. Nithya", home_line_id="L4"),
    Operator(id="O133", display_name="P. Jeyakumar", home_line_id="L4"),
    Operator(id="O141", display_name="G. Meenakshi", home_line_id="L3"),
    Operator(id="O145", display_name="K. Ravindran", home_line_id="L4"),
    Operator(id="O152", display_name="D. Lakshmi", home_line_id="L4"),
    Operator(id="O158", display_name="H. Praveena", home_line_id="L4"),
    Operator(id="O163", display_name="S. Vijayabaskar", home_line_id="L3"),
    Operator(id="O171", display_name="B. Ramadevi", home_line_id="L4"),
    Operator(id="O177", display_name="C. Udhayakumar", home_line_id="L3"),
    Operator(id="O182", display_name="R. Gayathri", home_line_id="L4"),
    Operator(id="O190", display_name="J. Kumaresan", home_line_id="L4"),
    Operator(id="O196", display_name="L. Saralam", home_line_id="L3"),
    Operator(id="O204", display_name="S. Vaishnavi", home_line_id="L3"),
    Operator(id="O210", display_name="P. Thirumoorthy", home_line_id="L3"),
    Operator(id="O215", display_name="A. Kayalvizhi", home_line_id="L4"),
    Operator(id="O219", display_name="K. Nakul", home_line_id="L4"),
)

CATALOG = Catalog(
    factory_name="Kaveri Garments, Unit 3 (synthetic fixture)",
    timezone="Asia/Kolkata",
    lines=(Line(id="L3", name="Line 3"), Line(id="L4", name="Line 4")),
    operators=OPERATORS,
    operations=OPERATIONS,
    styles=(
        Style(
            id="ST-411",
            code="KST-411",
            name="Trail Jacket",
            operation_ids=("OP-CUT", "OP-SLM", "OP-COL", "OP-SHD", "OP-BTK", "OP-INP", "OP-PKG"),
        ),
        Style(
            id="ST-208",
            code="KST-208",
            name="Utility Trouser",
            operation_ids=("OP-CUT", "OP-HLM", "OP-BTK", "OP-INP", "OP-PKG"),
        ),
    ),
    machines=MACHINES,
)

SHIFT_START = ist(8, 0)
SHIFT_END = ist(16, 30)
DECISION_AT = ist(7, 58)

SLOTS = (
    Slot(
        id="L4-SLM-1",
        line_id="L4",
        style_id="ST-411",
        operation_id="OP-SLM",
        machine_id="SN-4407",
        starts_at=SHIFT_START,
        ends_at=SHIFT_END,
        planned_operator_id="O117",
    ),
    Slot(
        id="L3-COL-1",
        line_id="L3",
        style_id="ST-411",
        operation_id="OP-COL",
        machine_id="SN-4403",
        starts_at=SHIFT_START,
        ends_at=SHIFT_END,
        planned_operator_id="O204",
    ),
    Slot(
        id="L4-HLM-1",
        line_id="L4",
        style_id="ST-208",
        operation_id="OP-HLM",
        machine_id="OL-2210",
        starts_at=SHIFT_START,
        ends_at=SHIFT_END,
        planned_operator_id="O190",
    ),
    Slot(
        id="L3-SHD-1",
        line_id="L3",
        style_id="ST-411",
        operation_id="OP-SHD",
        machine_id="SN-4402",
        starts_at=SHIFT_START,
        ends_at=SHIFT_END,
        planned_operator_id="O126",
    ),
    Slot(
        id="L4-COL-1",
        line_id="L4",
        style_id="ST-411",
        operation_id="OP-COL",
        machine_id="SN-4405",
        starts_at=SHIFT_START,
        ends_at=SHIFT_END,
        planned_operator_id="O158",
    ),
    Slot(
        id="L4-INP-1",
        line_id="L4",
        style_id="ST-208",
        operation_id="OP-INP",
        machine_id="IN-1102",
        starts_at=SHIFT_START,
        ends_at=SHIFT_END,
        planned_operator_id="O133",
    ),
)

HERO_EVENT = UnavailabilityEvent(
    subject_operator_id="O117",
    observed_at=ist(7, 52),
    summary="O117 reported unable to cover sleeve attach on Line 4; confirmed with supervisor.",
    source_ref="floor-note:FR-2241",
)

HERO_TARGET = CoverageTarget(
    line_id="L4",
    slot_id="L4-SLM-1",
    machine_id="SN-4407",
    starts_at=SHIFT_START,
    ends_at=SHIFT_END,
)

DEFAULT_FRESHNESS = GateFreshnessSettings()


# ---------------------------------------------------------------------------
# Snapshots
# ---------------------------------------------------------------------------


def _attendance_snapshot(rows: tuple[AttendanceRecord, ...], snapshot_id: str) -> Snapshot:
    return Snapshot(
        id=snapshot_id,
        kind=SnapshotKind.ATTENDANCE,
        source_system="attendance-export",
        scope="roster:all; date:2026-09-22; shift:08:00-16:30",
        declared_evidence_at=ist(7, 55),
        coverage_complete=True,
        content_digest="computed-at-publish",
        attendance=rows,
    )


def default_attendance_rows() -> tuple[AttendanceRecord, ...]:
    absent = {"O145", "O196"}  # unrelated realism: two operators on leave
    return tuple(
        AttendanceRecord(
            operator_id=op.id,
            status=AttendanceStatus.ABSENT if op.id in absent else AttendanceStatus.PRESENT,
            observed_at=ist(7, 55),
            source_ref=f"row:{i + 2}",
        )
        for i, op in enumerate(OPERATORS)
    )


def assignments_snapshot() -> Snapshot:
    rows = []
    for i, slot in enumerate(SLOTS):
        if slot.planned_operator_id is None:
            continue
        rows.append(
            AssignmentRecord(
                operator_id=slot.planned_operator_id,
                slot_id=slot.id,
                machine_id=slot.machine_id,
                starts_at=slot.starts_at,
                ends_at=slot.ends_at,
                source_ref=f"row:{i + 2}",
            )
        )
    return Snapshot(
        id="SNAP-ASSIGN-2026-09-22-A",
        kind=SnapshotKind.ASSIGNMENTS,
        source_system="line-lead-export",
        scope="roster:all; date:2026-09-22; interval:full-shift",
        declared_evidence_at=ist(7, 55),
        coverage_complete=True,
        content_digest="computed-at-publish",
        assignments=tuple(rows),
    )


def plan_snapshot() -> Snapshot:
    return Snapshot(
        id="SNAP-PLAN-2026-09-22-B",
        kind=SnapshotKind.PLAN,
        source_system="production-planning",
        scope="date:2026-09-22; lines:L3,L4",
        declared_evidence_at=ist(5, 30),
        coverage_complete=True,
        content_digest="computed-at-publish",
        plan=PlanSnapshotPayload(
            revision="PLAN-2026-09-22-B",
            verified_at=ist(5, 30),
            shift_starts_at=SHIFT_START,
            shift_ends_at=SHIFT_END,
            slots=SLOTS,
        ),
    )


def machine_state_snapshot() -> Snapshot:
    states = [
        MachineStateRecord(
            machine_id=m.id, usable=m.id != "SN-4404", observed_at=ist(7, 54), source_ref=f"row:{i + 2}"
        )
        for i, m in enumerate(MACHINES)
    ]
    return Snapshot(
        id="SNAP-MACH-2026-09-22-A",
        kind=SnapshotKind.MACHINE_STATE,
        source_system="maintenance-board",
        scope="machines:all",
        declared_evidence_at=ist(7, 54),
        coverage_complete=True,
        content_digest="computed-at-publish",
        machine_state=tuple(states),
    )


# Skill levels on sleeve attach for the hero ranking story.
_SLM_LEVELS = {
    "O204": 4,  # best, but occupied on L3
    "O219": 3,  # idle, same line -> the improved policy's pick
    "O112": 3,  # idle, other line -> ranked second
    "O117": 3,  # the unavailable subject
    "O152": 2,
    "O158": 2,
    "O130": 2,
    "O215": 2,
    "O145": 3,
}
_OTHER_LEVELS = {
    "O101": 3, "O108": 2, "O112": 2, "O117": 2, "O121": 1, "O126": 2,
    "O130": 1, "O133": 2, "O141": 2, "O145": 2, "O152": 1, "O158": 3,
    "O163": 1, "O171": 2, "O177": 3, "O182": 1, "O190": 2, "O196": 1,
    "O204": 3, "O210": 1, "O215": 2, "O219": 2,
}


def skills_snapshot(assessed_day_2026: tuple[int, int], snapshot_id: str) -> Snapshot:
    assessed_at = datetime(2026, assessed_day_2026[0], assessed_day_2026[1], 15, 0, tzinfo=IST)
    rows = []
    row = 2
    for op in OPERATORS:
        if op.id in _SLM_LEVELS:
            rows.append(
                SkillRecord(
                    operator_id=op.id,
                    operation_id="OP-SLM",
                    level=_SLM_LEVELS[op.id],
                    assessed_at=assessed_at,
                    source_ref=f"row:{row}",
                )
            )
            row += 1
        rows.append(
            SkillRecord(
                operator_id=op.id,
                operation_id="OP-COL",
                level=_OTHER_LEVELS[op.id],
                assessed_at=assessed_at,
                source_ref=f"row:{row}",
            )
        )
        row += 1
    return Snapshot(
        id=snapshot_id,
        kind=SnapshotKind.SKILLS,
        source_system="skill-matrix-export",
        scope="roster:all; operations:OP-SLM,OP-COL",
        declared_evidence_at=assessed_at,
        coverage_complete=True,
        content_digest="computed-at-publish",
        skills=tuple(rows),
    )


def skills_snapshot_stale() -> Snapshot:
    """Revision 1: assessed 2026-08-08, 45 days before the decision."""
    return skills_snapshot((8, 8), "SNAP-SKILL-2026-08-08-A")


def skills_snapshot_fresh() -> Snapshot:
    """Revision 2: assessed 2026-09-18, four days before the decision."""
    return skills_snapshot((9, 18), "SNAP-SKILL-2026-09-18-B")


def hero_snapshots_v1() -> tuple[Snapshot, ...]:
    return (
        _attendance_snapshot(default_attendance_rows(), "SNAP-ATT-2026-09-22-A"),
        assignments_snapshot(),
        plan_snapshot(),
        skills_snapshot_stale(),
        machine_state_snapshot(),
    )


def hero_snapshots_v2() -> tuple[Snapshot, ...]:
    return (
        _attendance_snapshot(default_attendance_rows(), "SNAP-ATT-2026-09-22-A"),
        assignments_snapshot(),
        plan_snapshot(),
        skills_snapshot_fresh(),
        machine_state_snapshot(),
    )


def hero_context(snapshots: tuple[Snapshot, ...]) -> ReplayRequestContext:
    return ReplayRequestContext(
        catalog=CATALOG,
        snapshots=snapshots,
        event=HERO_EVENT,
        decision_at=DECISION_AT,
        target=HERO_TARGET,
    )


# ---------------------------------------------------------------------------
# Registered execution configurations
# ---------------------------------------------------------------------------

from flooreplay.domain.evaluation import Expectation  # noqa: E402

CONFIGURATIONS: tuple[dict[str, Any], ...] = (
    {
        "id": "CFG-BASELINE-V1",
        "name": "Baseline policy",
        "policy_kind": "baseline-v1",
        "settings": DEFAULT_FRESHNESS,
        "known_limitation": "Ranks qualified, present candidates but deliberately omits "
        "assignment-overlap filtering. Expect occupied proposals to be rejected by C07.",
    },
    {
        "id": "CFG-IMPROVED-V1",
        "name": "Improved policy",
        "policy_kind": "improved-v1",
        "settings": DEFAULT_FRESHNESS,
        "known_limitation": "",
    },
    {
        "id": "CFG-DEFECT-SKILLFRESH",
        "name": "Demonstration defect: relaxed skill freshness",
        "policy_kind": "improved-v1",
        "settings": GateFreshnessSettings(skill_max_age_seconds=400 * 24 * 60 * 60),
        "known_limitation": "Intentionally wrong: a 400-day skill freshness budget. Exists to "
        "be caught by the stale-evidence expectation in the suite.",
    },
)


# ---------------------------------------------------------------------------
# Scenarios and expectations
# ---------------------------------------------------------------------------


class ScenarioFixture:
    def __init__(
        self,
        scenario_id: str,
        revision: int,
        title: str,
        tags: tuple[str, ...],
        defect_statement: str,
        context: ReplayRequestContext,
        expectations: dict[str, Expectation],
    ) -> None:
        self.scenario_id = scenario_id
        self.revision = revision
        self.title = title
        self.tags = tags
        self.defect_statement = defect_statement
        self.context = context
        self.expectations = expectations


def hero_scenarios() -> tuple[ScenarioFixture, ...]:
    return (
        ScenarioFixture(
            scenario_id="SCEN-HERO",
            revision=1,
            title="Hero: sleeve attach vacancy with stale skill evidence",
            tags=("hero", "evidence-freshness", "needs-context"),
            defect_statement="Catches a policy that runs on stale skill evidence instead of stopping.",
            context=hero_context(hero_snapshots_v1()),
            expectations={
                "CFG-BASELINE-V1": Expectation(
                    expected_outcome=None,
                    required_issue_codes=(IssueCode.SKILL_STALE,),
                    policy_execution_permitted=False,
                ),
                "CFG-IMPROVED-V1": Expectation(
                    required_issue_codes=(IssueCode.SKILL_STALE,),
                    policy_execution_permitted=False,
                ),
                # The demonstration defect fails this expectation on purpose:
                # its 400-day budget lets stale evidence through.
                "CFG-DEFECT-SKILLFRESH": Expectation(
                    required_issue_codes=(IssueCode.SKILL_STALE,),
                    policy_execution_permitted=False,
                ),
            },
        ),
        ScenarioFixture(
            scenario_id="SCEN-HERO",
            revision=2,
            title="Hero: sleeve attach vacancy with corrected skill evidence",
            tags=("hero", "deterministic-selection", "overlap-rejection"),
            defect_statement="Catches overlap-blind proposals (baseline) and eligibility "
            "regressions in the improved policy.",
            context=hero_context(hero_snapshots_v2()),
            expectations={
                "CFG-BASELINE-V1": Expectation(
                    expected_outcome=None,  # outcome asserted via constraints below
                    required_failed_constraints=(ConstraintCode.C07,),
                ),
                "CFG-IMPROVED-V1": Expectation(
                    required_operator="O219",
                    required_passed_constraints=(
                        ConstraintCode.C01,
                        ConstraintCode.C02,
                        ConstraintCode.C07,
                    ),
                ),
                "CFG-DEFECT-SKILLFRESH": Expectation(required_operator="O219"),
            },
        ),
    )


# ---------------------------------------------------------------------------
# Later-context review fixtures: one episode, three points in time.
# rev1 07:58 (original decision, healthy evidence)
# rev2 08:10 with refreshed evidence and a new plan revision -> STALE_RECOMMENDATION
# rev3 08:10 with the ORIGINAL (now stale) snapshots -> BLOCKED_CONTEXT
# ---------------------------------------------------------------------------

LATER_DECISION_AT = ist(8, 10)


def _refreshed_snapshot(snap: Snapshot, at: datetime, new_declared: bool = True) -> Snapshot:
    updates: dict[str, object] = {}
    if new_declared:
        updates["declared_evidence_at"] = at
    if snap.attendance is not None:
        updates["attendance"] = tuple(
            rec.model_copy(update={"observed_at": at}) for rec in snap.attendance
        )
    if snap.machine_state is not None:
        updates["machine_state"] = tuple(
            rec.model_copy(update={"observed_at": at}) for rec in snap.machine_state
        )
    return snap.model_copy(update=updates)


def _revised_plan(snap: Snapshot, verified_at: datetime) -> Snapshot:
    assert snap.plan is not None
    return snap.model_copy(
        update={
            "plan": snap.plan.model_copy(
                update={"revision": "PLAN-2026-09-22-C", "verified_at": verified_at}
            )
        }
    )


def _reid(snap: Snapshot, suffix: str) -> Snapshot:
    return snap.model_copy(update={"id": f"{snap.id}-{suffix}"})


def review_original_context() -> ReplayRequestContext:
    """rev1: the hero context exactly as decided at 07:58."""
    return hero_context(hero_snapshots_v2())


def review_refreshed_context() -> ReplayRequestContext:
    """rev2: 08:10, everything re-exported fresh, plan revision C verified."""
    snaps = []
    for snap in hero_snapshots_v2():
        if snap.kind.value == "PLAN":
            snaps.append(_reid(_revised_plan(snap, ist(8, 5)), "R2"))
        elif snap.kind.value == "SKILLS":
            snaps.append(_reid(snap, "R2"))  # 30-day budget: still fresh at 08:10
        else:
            snaps.append(_reid(_refreshed_snapshot(snap, ist(8, 6)), "R2"))
    return ReplayRequestContext(
        catalog=CATALOG,
        snapshots=tuple(snaps),
        event=HERO_EVENT.model_copy(update={"observed_at": ist(8, 2)}),
        decision_at=LATER_DECISION_AT,
        target=HERO_TARGET,
    )


def review_stale_context() -> ReplayRequestContext:
    """rev3: 08:10 decided against the original 07:5x exports: stale."""
    snaps = tuple(_reid(snap, "R3") for snap in hero_snapshots_v2())
    return ReplayRequestContext(
        catalog=CATALOG,
        snapshots=snaps,
        event=HERO_EVENT.model_copy(update={"observed_at": ist(8, 2)}),
        decision_at=LATER_DECISION_AT,
        target=HERO_TARGET,
    )
