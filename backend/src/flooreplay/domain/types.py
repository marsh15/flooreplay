"""Pure domain contracts for the replay engine.

Everything in this module is framework-free, database-free and IO-free.
The engine consumes these types and produces these types; persistence and
HTTP layers translate to and from them. Naive datetimes are rejected at
the boundary: every instant in FloorReplay carries an explicit UTC offset.
"""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Self

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

ID_PATTERN = re.compile(r"^[A-Z][A-Z0-9]*(-[A-Z0-9]+)*$")

OperatorId = Annotated[str, Field(pattern=ID_PATTERN)]
LineId = Annotated[str, Field(pattern=ID_PATTERN)]
SlotId = Annotated[str, Field(pattern=ID_PATTERN)]
MachineId = Annotated[str, Field(pattern=ID_PATTERN)]
OperationId = Annotated[str, Field(pattern=ID_PATTERN)]
StyleId = Annotated[str, Field(pattern=ID_PATTERN)]


def _require_tz(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("naive datetimes are not allowed; give an explicit UTC offset")
    return value


Instant = Annotated[
    datetime, AfterValidator(_require_tz), Field(description="UTC-offset-aware instant")
]


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# ---------------------------------------------------------------------------
# Catalog: the bounded world a replay happens inside.
# ---------------------------------------------------------------------------


class Line(FrozenModel):
    id: LineId
    name: str


class Operator(FrozenModel):
    id: OperatorId
    display_name: str
    home_line_id: LineId | None = None
    active: bool = True
    aliases: tuple[str, ...] = ()


class OperationDef(FrozenModel):
    id: OperationId
    name: str
    required_skill_level: int = Field(ge=1, le=4)


class Style(FrozenModel):
    id: StyleId
    code: str
    name: str
    operation_ids: tuple[OperationId, ...]


class Machine(FrozenModel):
    id: MachineId
    kind: str
    compatible_operation_ids: tuple[OperationId, ...]


class Catalog(FrozenModel):
    factory_name: str
    timezone: str  # IANA zone the factory operates in, e.g. Asia/Kolkata
    lines: tuple[Line, ...]
    operators: tuple[Operator, ...]
    operations: tuple[OperationDef, ...]
    styles: tuple[Style, ...]
    machines: tuple[Machine, ...]


# ---------------------------------------------------------------------------
# Source snapshots: immutable evidence with declared provenance.
# ---------------------------------------------------------------------------


class SnapshotKind(StrEnum):
    ATTENDANCE = "ATTENDANCE"
    ASSIGNMENTS = "ASSIGNMENTS"
    PLAN = "PLAN"
    SKILLS = "SKILLS"
    MACHINE_STATE = "MACHINE_STATE"


class AttendanceStatus(StrEnum):
    PRESENT = "PRESENT"
    ABSENT = "ABSENT"
    UNKNOWN = "UNKNOWN"


class AttendanceRecord(FrozenModel):
    operator_id: OperatorId
    status: AttendanceStatus
    observed_at: Instant
    source_ref: str  # pointer to the original row for inspection


class AssignmentRecord(FrozenModel):
    operator_id: OperatorId
    slot_id: SlotId | None = None
    machine_id: MachineId | None = None
    starts_at: Instant
    ends_at: Instant
    source_ref: str


class MachineStateRecord(FrozenModel):
    machine_id: MachineId
    usable: bool
    observed_at: Instant
    detail: str = ""
    source_ref: str


class SkillRecord(FrozenModel):
    operator_id: OperatorId
    operation_id: OperationId
    level: int = Field(ge=1, le=4)
    assessed_at: Instant
    source_ref: str


class Slot(FrozenModel):
    id: SlotId
    line_id: LineId
    style_id: StyleId
    operation_id: OperationId
    machine_id: MachineId
    starts_at: Instant
    ends_at: Instant
    planned_operator_id: OperatorId | None = None


class PlanSnapshotPayload(FrozenModel):
    revision: str
    verified_at: Instant
    shift_starts_at: Instant
    shift_ends_at: Instant
    slots: tuple[Slot, ...]


class Snapshot(FrozenModel):
    """One immutable piece of evidence, normalized."""

    id: str
    kind: SnapshotKind
    source_system: str
    scope: str  # human-readable coverage claim, e.g. "roster:all; interval:shift"
    declared_evidence_at: Instant  # when the source says this data was true
    coverage_complete: bool  # source asserts no rows are missing within scope
    content_digest: str
    # Only the payload matching `kind` is set.
    attendance: tuple[AttendanceRecord, ...] | None = None
    assignments: tuple[AssignmentRecord, ...] | None = None
    plan: PlanSnapshotPayload | None = None
    skills: tuple[SkillRecord, ...] | None = None
    machine_state: tuple[MachineStateRecord, ...] | None = None

    @model_validator(mode="after")
    def _payload_matches_kind(self) -> Self:
        field_of_kind = {
            SnapshotKind.ATTENDANCE: "attendance",
            SnapshotKind.ASSIGNMENTS: "assignments",
            SnapshotKind.PLAN: "plan",
            SnapshotKind.SKILLS: "skills",
            SnapshotKind.MACHINE_STATE: "machine_state",
        }
        for kind, field in field_of_kind.items():
            value = getattr(self, field)
            if kind == self.kind and value is None:
                raise ValueError(f"snapshot of kind {kind.value} must carry a {field} payload")
            if kind != self.kind and value is not None:
                raise ValueError(f"snapshot of kind {self.kind.value} must not carry a {field} payload")
        return self


# ---------------------------------------------------------------------------
# The episode: what happened on the floor, and what decision we replay.
# ---------------------------------------------------------------------------


class EventKind(StrEnum):
    OPERATOR_UNAVAILABLE = "OPERATOR_UNAVAILABLE"


class UnavailabilityEvent(FrozenModel):
    kind: EventKind = EventKind.OPERATOR_UNAVAILABLE
    subject_operator_id: OperatorId
    observed_at: Instant
    summary: str
    source_ref: str


class CoverageTarget(FrozenModel):
    """The vacant slot being replayed for."""

    line_id: LineId
    slot_id: SlotId
    machine_id: MachineId
    starts_at: Instant
    ends_at: Instant


class PinnedInputs(FrozenModel):
    catalog: Catalog
    snapshots: tuple[Snapshot, ...]

    def snapshot(self, kind: SnapshotKind) -> Snapshot:
        for snapshot in self.snapshots:
            if snapshot.kind == kind:
                return snapshot
        raise KeyError(kind)


# ---------------------------------------------------------------------------
# Outcomes. Three separate axes, never collapsed into one.
# ---------------------------------------------------------------------------


class ExecutionLifecycle(StrEnum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    ERRORED = "ERRORED"
    INTERRUPTED = "INTERRUPTED"


class DomainOutcome(StrEnum):
    NEEDS_CONTEXT = "NEEDS_CONTEXT"
    CONFLICTING_CONTEXT = "CONFLICTING_CONTEXT"
    NO_FEASIBLE_CANDIDATE = "NO_FEASIBLE_CANDIDATE"
    REJECTED_BY_CONSTRAINT = "REJECTED_BY_CONSTRAINT"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"


class Verdict(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_EVALUATED = "NOT_EVALUATED"


class IssueSeverity(StrEnum):
    BLOCKING = "BLOCKING"
    MATERIAL = "MATERIAL"  # matters only when no supported candidate exists
    INFO = "INFO"


class IssueCode(StrEnum):
    # Shared context issues
    SNAPSHOT_SCOPE_INCOMPLETE = "SNAPSHOT_SCOPE_INCOMPLETE"
    ATTENDANCE_ROSTER_GAP = "ATTENDANCE_ROSTER_GAP"
    ATTENDANCE_STALE = "ATTENDANCE_STALE"
    ASSIGNMENTS_STALE = "ASSIGNMENTS_STALE"
    ASSIGNMENTS_SCOPE_INCOMPLETE = "ASSIGNMENTS_SCOPE_INCOMPLETE"
    MACHINE_STATE_STALE = "MACHINE_STATE_STALE"
    PLAN_STALE = "PLAN_STALE"
    PLAN_MISSING = "PLAN_MISSING"
    TARGET_SLOT_UNKNOWN = "TARGET_SLOT_UNKNOWN"
    TARGET_MACHINE_UNKNOWN = "TARGET_MACHINE_UNKNOWN"
    TARGET_MACHINE_UNUSABLE = "TARGET_MACHINE_UNUSABLE"
    TARGET_OPERATION_NOT_IN_STYLE = "TARGET_OPERATION_NOT_IN_STYLE"
    COVERAGE_INTERVAL_INVALID = "COVERAGE_INTERVAL_INVALID"
    COVERAGE_OUTSIDE_SLOT = "COVERAGE_OUTSIDE_SLOT"
    FUTURE_EVIDENCE = "FUTURE_EVIDENCE"
    CONTRADICTORY_ASSERTIONS = "CONTRADICTORY_ASSERTIONS"
    # Candidate-specific issues
    OPERATOR_UNKNOWN = "OPERATOR_UNKNOWN"
    OPERATOR_INACTIVE = "OPERATOR_INACTIVE"
    ATTENDANCE_UNKNOWN = "ATTENDANCE_UNKNOWN"
    OPERATOR_ABSENT = "OPERATOR_ABSENT"
    OPERATOR_UNAVAILABLE = "OPERATOR_UNAVAILABLE"
    SKILL_UNKNOWN = "SKILL_UNKNOWN"
    SKILL_INSUFFICIENT = "SKILL_INSUFFICIENT"
    SKILL_STALE = "SKILL_STALE"
    OVERLAPPING_ASSIGNMENT = "OVERLAPPING_ASSIGNMENT"
    MACHINE_RESERVED = "MACHINE_RESERVED"


class EvidenceRef(FrozenModel):
    """Points at the exact source row or canonical fact behind a finding."""

    snapshot_id: str
    source_ref: str = ""
    field: str = ""
    detail: str = ""

    def render(self) -> str:
        return f"{self.snapshot_id}:{self.source_ref}" if self.source_ref else self.snapshot_id


class Issue(FrozenModel):
    code: IssueCode
    severity: IssueSeverity
    subject: str = ""  # operator or machine id when candidate-specific
    message: str
    evidence: tuple[EvidenceRef, ...] = ()


class ConstraintCode(StrEnum):
    C01 = "C01"  # operator exists and is active
    C02 = "C02"  # present and not explicitly unavailable
    C03 = "C03"  # interval fits shift and target slot
    C04 = "C04"  # skill meets operation requirement
    C05 = "C05"  # skill evidence sufficiently fresh
    C06 = "C06"  # designated machine exists, compatible, usable
    C07 = "C07"  # no overlapping assignment
    C08 = "C08"  # operation belongs to style revision
    C09 = "C09"  # proposal references pinned plan and slot
    C10 = "C10"  # machine has no incompatible overlapping reservation
    C11 = "C11"  # proposal references the supplied context digest
    C12 = "C12"  # operator is not the unavailable subject


class ConstraintResult(FrozenModel):
    code: ConstraintCode
    verdict: Verdict
    reason_code: str = ""
    message: str
    evidence: tuple[EvidenceRef, ...] = ()


class PolicyActionType(StrEnum):
    PROPOSE_SLOT_COVERAGE = "PROPOSE_SLOT_COVERAGE"


class Proposal(FrozenModel):
    action_type: PolicyActionType = PolicyActionType.PROPOSE_SLOT_COVERAGE
    operator_id: OperatorId
    target_slot_id: SlotId
    machine_id: MachineId
    operation_id: OperationId
    style_id: StyleId
    plan_revision: str
    starts_at: Instant
    ends_at: Instant
    context_digest: str
    ranking_factors: tuple[tuple[str, str], ...] = ()


class CandidateExclusion(FrozenModel):
    operator_id: OperatorId
    issue_codes: tuple[IssueCode, ...]


class Abstention(FrozenModel):
    reason_code: str
    candidate_exclusions: tuple[CandidateExclusion, ...] = ()


class GateFreshnessSettings(FrozenModel):
    attendance_max_age_seconds: int = 5 * 60
    assignment_max_age_seconds: int = 5 * 60
    machine_state_max_age_seconds: int = 5 * 60
    plan_verification_max_age_seconds: int = 4 * 60 * 60
    skill_max_age_seconds: int = 30 * 24 * 60 * 60


class ReplayRequestContext(FrozenModel):
    """Everything a replay needs, assembled from pinned artifacts."""

    catalog: Catalog
    snapshots: tuple[Snapshot, ...]
    event: UnavailabilityEvent
    decision_at: Instant
    target: CoverageTarget


class ReplayOutcome(FrozenModel):
    """The complete, deterministic result of one replay execution."""

    outcome: DomainOutcome
    gate_issues: tuple[Issue, ...] = ()
    proposal: Proposal | None = None
    abstention: Abstention | None = None
    constraints: tuple[ConstraintResult, ...] = ()
    context_digest: str = ""
    ranked_candidates: tuple[OperatorId, ...] = ()
