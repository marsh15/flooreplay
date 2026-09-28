"""The context gate: is the pinned evidence good enough to act on?

Separates shared requirements (target, plan, machine, snapshot coverage and
freshness) from candidate-specific requirements (identity, attendance,
unavailability, skills, assignments). Missing evidence is never read as
absence: an unknown attendance row means UNKNOWN, not absent, and unknown
skill means UNKNOWN, not level zero.

Outcome discipline:
- Shared evidence problems (missing, stale, incomplete) block the policy
  and yield NEEDS_CONTEXT.
- Contradictory assertions across sources yield CONFLICTING_CONTEXT even
  when missing data is also present; both sets of findings are kept.
- Conclusive target defects (designated machine incompatible) yield
  NO_FEASIBLE_CANDIDATE: no candidate can ever be supported for this target.
- Candidate evaluation feeds the policies. A bad record for one operator
  never blocks a supported proposal for another.
"""

from __future__ import annotations

from datetime import timedelta

from . import intervals
from .types import (
    AssignmentRecord,
    AttendanceRecord,
    AttendanceStatus,
    Catalog,
    CoverageTarget,
    DomainOutcome,
    EvidenceRef,
    GateFreshnessSettings,
    Instant,
    Issue,
    IssueCode,
    IssueSeverity,
    MachineStateRecord,
    Operator,
    PinnedInputs,
    PlanSnapshotPayload,
    ReplayRequestContext,
    SkillRecord,
    Slot,
    Snapshot,
    SnapshotKind,
)


def _issue(
    code: IssueCode,
    severity: IssueSeverity,
    message: str,
    *,
    subject: str = "",
    evidence: tuple[EvidenceRef, ...] = (),
) -> Issue:
    return Issue(code=code, severity=severity, subject=subject, message=message, evidence=evidence)


def _fresh(observed_at: Instant, decision_at: Instant, max_age: timedelta) -> bool:
    """Freshness is evidence time vs the pinned decision time, never now()."""
    if observed_at > decision_at:
        return False  # future evidence was not knowable at decision time
    return decision_at - observed_at <= max_age


def _snapshot_of(pinned: PinnedInputs, kind: SnapshotKind) -> Snapshot | None:
    return next((s for s in pinned.snapshots if s.kind == kind), None)


def _plan_snapshot(pinned: PinnedInputs) -> Snapshot | None:
    return _snapshot_of(pinned, SnapshotKind.PLAN)


# ---------------------------------------------------------------------------
# Shared checks
# ---------------------------------------------------------------------------


def _check_shared(
    ctx: ReplayRequestContext, settings: GateFreshnessSettings
) -> tuple[list[Issue], list[Issue]]:
    """Return (blocking evidence problems, conclusive target defects)."""
    catalog: Catalog = ctx.catalog
    target: CoverageTarget = ctx.target
    blocking: list[Issue] = []
    conclusive: list[Issue] = []
    pinned = PinnedInputs(catalog=catalog, snapshots=ctx.snapshots)

    plan = _plan_snapshot(pinned)
    if plan is None:
        blocking.append(
            _issue(
                IssueCode.PLAN_MISSING,
                IssueSeverity.BLOCKING,
                "No production-plan snapshot is pinned to this scenario revision.",
            )
        )
        return blocking, conclusive
    plan_payload = plan.plan
    assert plan_payload is not None  # Snapshot's model validator guarantees the kind's payload

    slot = next((s for s in plan_payload.slots if s.id == target.slot_id), None)
    if slot is None:
        blocking.append(
            _issue(
                IssueCode.TARGET_SLOT_UNKNOWN,
                IssueSeverity.BLOCKING,
                f"Target slot {target.slot_id} is not present in plan revision {plan_payload.revision}.",
                evidence=(EvidenceRef(snapshot_id=plan.id, field="slots"),),
            )
        )
    else:
        if not intervals.contains(slot.starts_at, slot.ends_at, target.starts_at, target.ends_at):
            blocking.append(
                _issue(
                    IssueCode.COVERAGE_OUTSIDE_SLOT,
                    IssueSeverity.BLOCKING,
                    "Requested coverage interval does not fit inside the target slot.",
                    evidence=(
                        EvidenceRef(snapshot_id=plan.id, source_ref=slot.id, field="starts_at/ends_at"),
                    ),
                )
            )
        if not intervals.contains(
            plan_payload.shift_starts_at,
            plan_payload.shift_ends_at,
            target.starts_at,
            target.ends_at,
        ):
            blocking.append(
                _issue(
                    IssueCode.COVERAGE_OUTSIDE_SLOT,
                    IssueSeverity.BLOCKING,
                    "Requested coverage interval does not fit inside the shift.",
                    evidence=(EvidenceRef(snapshot_id=plan.id, field="shift"),),
                )
            )

    if slot is not None:
        style = next((st for st in catalog.styles if st.id == slot.style_id), None)
        if style is None or slot.operation_id not in style.operation_ids:
            blocking.append(
                _issue(
                    IssueCode.TARGET_OPERATION_NOT_IN_STYLE,
                    IssueSeverity.BLOCKING,
                    f"Operation {slot.operation_id} does not belong to style {slot.style_id}.",
                )
            )

    machine = next((m for m in catalog.machines if m.id == target.machine_id), None)
    op_def = (
        next((o for o in catalog.operations if o.id == slot.operation_id), None) if slot else None
    )
    if machine is None:
        blocking.append(
            _issue(
                IssueCode.TARGET_MACHINE_UNKNOWN,
                IssueSeverity.BLOCKING,
                f"Designated machine {target.machine_id} is not in the pinned catalog.",
            )
        )
    elif op_def is not None and op_def.id not in machine.compatible_operation_ids:
        conclusive.append(
            _issue(
                IssueCode.TARGET_MACHINE_UNUSABLE,
                IssueSeverity.BLOCKING,
                f"Machine {machine.id} ({machine.kind}) is not compatible with operation {op_def.id}.",
            )
        )
    elif machine is not None:
        # A recorded-unusable designated machine conclusively excludes every
        # candidate: no proposal on it can ever validate. This is a known
        # fact, not missing context, so it never yields NEEDS_CONTEXT.
        state_owner: tuple[Snapshot, MachineStateRecord] | None = None
        for snap in pinned.snapshots:
            if snap.kind is not SnapshotKind.MACHINE_STATE or snap.machine_state is None:
                continue
            for rec in snap.machine_state:
                if rec.machine_id == machine.id:
                    state_owner = (snap, rec)
                    break
            if state_owner is not None:
                break
        if state_owner is not None and not state_owner[1].usable:
            machine_snapshot, state = state_owner
            conclusive.append(
                _issue(
                    IssueCode.TARGET_MACHINE_UNUSABLE,
                    IssueSeverity.BLOCKING,
                    f"Machine {machine.id} is recorded unusable: {state.detail}.",
                    evidence=(
                        EvidenceRef(
                            snapshot_id=machine_snapshot.id,
                            source_ref=state.source_ref,
                            field="usable",
                        ),
                    ),
                )
            )

    for kind, max_age, stale_code in (
        (
            SnapshotKind.ATTENDANCE,
            timedelta(seconds=settings.attendance_max_age_seconds),
            IssueCode.ATTENDANCE_STALE,
        ),
        (
            SnapshotKind.ASSIGNMENTS,
            timedelta(seconds=settings.assignment_max_age_seconds),
            IssueCode.ASSIGNMENTS_STALE,
        ),
        (
            SnapshotKind.MACHINE_STATE,
            timedelta(seconds=settings.machine_state_max_age_seconds),
            IssueCode.MACHINE_STATE_STALE,
        ),
    ):
        snapshot = _snapshot_of(pinned, kind)
        if snapshot is None:
            blocking.append(
                _issue(
                    IssueCode.SNAPSHOT_SCOPE_INCOMPLETE,
                    IssueSeverity.BLOCKING,
                    f"No {kind.value.lower()} snapshot is pinned.",
                )
            )
            continue
        if not snapshot.coverage_complete:
            scope_code = (
                IssueCode.ASSIGNMENTS_SCOPE_INCOMPLETE
                if kind is SnapshotKind.ASSIGNMENTS
                else IssueCode.SNAPSHOT_SCOPE_INCOMPLETE
            )
            blocking.append(
                _issue(
                    scope_code,
                    IssueSeverity.BLOCKING,
                    f"{kind.value.lower()} snapshot {snapshot.id} does not assert complete coverage "
                    f"(scope: {snapshot.scope}); 'free' cannot be concluded from an incomplete export.",
                    evidence=(EvidenceRef(snapshot_id=snapshot.id, field="coverage_complete"),),
                )
            )
        if snapshot.declared_evidence_at > ctx.decision_at:
            blocking.append(
                _issue(
                    IssueCode.FUTURE_EVIDENCE,
                    IssueSeverity.BLOCKING,
                    f"{kind.value.lower()} snapshot {snapshot.id} declares evidence time after the "
                    "decision time; it was not knowable when the decision is replayed.",
                    evidence=(EvidenceRef(snapshot_id=snapshot.id, field="declared_evidence_at"),),
                )
            )
        elif not _fresh(snapshot.declared_evidence_at, ctx.decision_at, max_age):
            blocking.append(
                _issue(
                    stale_code,
                    IssueSeverity.BLOCKING,
                    f"{kind.value.lower()} snapshot {snapshot.id} is older than the configured "
                    f"{int(max_age.total_seconds())}s budget relative to the decision time.",
                    evidence=(EvidenceRef(snapshot_id=snapshot.id, field="declared_evidence_at"),),
                )
            )

    plan_max_age = timedelta(seconds=settings.plan_verification_max_age_seconds)
    if plan_payload.verified_at > ctx.decision_at:
        blocking.append(
            _issue(
                IssueCode.FUTURE_EVIDENCE,
                IssueSeverity.BLOCKING,
                f"Plan revision {plan_payload.revision} was verified after the decision time.",
                evidence=(EvidenceRef(snapshot_id=plan.id, field="verified_at"),),
            )
        )
    elif not _fresh(plan_payload.verified_at, ctx.decision_at, plan_max_age):
        blocking.append(
            _issue(
                IssueCode.PLAN_STALE,
                IssueSeverity.BLOCKING,
                f"Plan revision {plan_payload.revision} was verified more than "
                f"{int(plan_max_age.total_seconds())}s before the decision time.",
                evidence=(EvidenceRef(snapshot_id=plan.id, field="verified_at"),),
            )
        )

    attendance = _snapshot_of(pinned, SnapshotKind.ATTENDANCE)
    if attendance is not None and attendance.attendance is not None:
        covered = {rec.operator_id for rec in attendance.attendance}
        roster_gap = [op.id for op in catalog.operators if op.active and op.id not in covered]
        if roster_gap and attendance.coverage_complete:
            shown = ", ".join(sorted(roster_gap)[:6])
            blocking.append(
                _issue(
                    IssueCode.ATTENDANCE_ROSTER_GAP,
                    IssueSeverity.BLOCKING,
                    f"Attendance snapshot claims complete coverage but {len(roster_gap)} roster "
                    f"operator(s) have no row: {shown}{'...' if len(roster_gap) > 6 else ''}.",
                    evidence=(
                        EvidenceRef(
                            snapshot_id=attendance.id,
                            field="attendance",
                            detail=f"missing rows for {len(roster_gap)} operators",
                        ),
                    ),
                )
            )

    blocking.extend(_contradictions(pinned))
    return blocking, conclusive


def _contradictions(pinned: PinnedInputs) -> list[Issue]:
    """Incompatible facts about the same predicate and overlapping applicability."""
    issues: list[Issue] = []

    attendance_snap = _snapshot_of(pinned, SnapshotKind.ATTENDANCE)
    if attendance_snap is not None and attendance_snap.attendance:
        statuses: dict[tuple[str, str], set[str]] = {}
        for rec in attendance_snap.attendance:
            statuses.setdefault((rec.operator_id, rec.observed_at.isoformat()), set()).add(
                rec.status.value
            )
        for (op_id, observed), values in statuses.items():
            if len(values) > 1:
                issues.append(
                    _issue(
                        IssueCode.CONTRADICTORY_ASSERTIONS,
                        IssueSeverity.BLOCKING,
                        f"Attendance for {op_id} at {observed} asserts conflicting statuses: "
                        f"{sorted(values)}.",
                        subject=op_id,
                        evidence=(EvidenceRef(snapshot_id=attendance_snap.id, field="attendance"),),
                    )
                )

    skills_snap = _snapshot_of(pinned, SnapshotKind.SKILLS)
    if skills_snap is not None and skills_snap.skills:
        levels: dict[tuple[str, str, str], set[int]] = {}
        for skill_rec in skills_snap.skills:
            levels.setdefault(
                (skill_rec.operator_id, skill_rec.operation_id, skill_rec.assessed_at.isoformat()),
                set(),
            ).add(skill_rec.level)
        for (op_id, operation_id, assessed), level_values in levels.items():
            if len(level_values) > 1:
                issues.append(
                    _issue(
                        IssueCode.CONTRADICTORY_ASSERTIONS,
                        IssueSeverity.BLOCKING,
                        f"Skill evidence for {op_id} on {operation_id} assessed at {assessed} "
                        f"asserts conflicting levels: {sorted(level_values)}.",
                        subject=op_id,
                        evidence=(EvidenceRef(snapshot_id=skills_snap.id, field="skills"),),
                    )
                )
    return issues


# ---------------------------------------------------------------------------
# Candidate evaluation
# ---------------------------------------------------------------------------


class CandidateFinding:
    """Per-candidate eligibility outcome, with evidence, for policy use.

    core_eligible: every requirement except assignment overlap. This is the
    deliberate blind spot of the baseline policy.
    fully_supported: every requirement, overlap included.
    """

    __slots__ = (
        "operator_id",
        "core_eligible",
        "fully_supported",
        "evidence_supported",
        "issues",
        "skill_level",
        "home_line_id",
    )

    def __init__(
        self,
        operator_id: str,
        core_eligible: bool,
        fully_supported: bool,
        issues: list[Issue],
        skill_level: int,
        home_line_id: str | None,
    ) -> None:
        self.operator_id = operator_id
        self.core_eligible = core_eligible
        self.fully_supported = fully_supported
        # Supported by adequate evidence, ignoring assignment overlap: no
        # material unknown/stale gaps. This is the evidence-level bar every
        # policy must clear before it is allowed to run at all.
        self.evidence_supported = core_eligible and not any(
            i.severity is IssueSeverity.MATERIAL for i in issues
        )
        self.issues = issues
        self.skill_level = skill_level
        self.home_line_id = home_line_id


def _evaluate_candidate(
    ctx: ReplayRequestContext,
    settings: GateFreshnessSettings,
    operator: Operator,
    slot: Slot,
    required_level: int,
    snapshot_ids: dict[SnapshotKind, str],
    attendance_by_op: dict[str, AttendanceRecord],
    assignments_by_op: dict[str, list[AssignmentRecord]],
    skills_by_key: dict[tuple[str, str], SkillRecord],
) -> CandidateFinding:
    op_id = operator.id
    issues: list[Issue] = []

    att = attendance_by_op.get(op_id)
    if att is None or att.status is AttendanceStatus.UNKNOWN:
        issues.append(
            _issue(
                IssueCode.ATTENDANCE_UNKNOWN,
                IssueSeverity.MATERIAL,
                f"Attendance for {op_id} is unknown; missing rows are never read as absent.",
                subject=op_id,
                evidence=(
                    EvidenceRef(
                        snapshot_id=snapshot_ids[SnapshotKind.ATTENDANCE],
                        source_ref=att.source_ref if att else "",
                        field="status",
                    ),
                ),
            )
        )
    elif att.observed_at > ctx.decision_at:
        # Parity with skill evidence: a row observed after the decision time
        # was not knowable when deciding, and is flagged rather than trusted.
        issues.append(
            _issue(
                IssueCode.FUTURE_EVIDENCE,
                IssueSeverity.MATERIAL,
                f"Attendance for {op_id} was observed after the decision time.",
                subject=op_id,
                evidence=(
                    EvidenceRef(
                        snapshot_id=snapshot_ids[SnapshotKind.ATTENDANCE],
                        source_ref=att.source_ref,
                        field="observed_at",
                    ),
                ),
            )
        )
    elif att.status is AttendanceStatus.ABSENT:
        issues.append(
            _issue(
                IssueCode.OPERATOR_ABSENT,
                IssueSeverity.BLOCKING,
                f"{op_id} is recorded absent.",
                subject=op_id,
                evidence=(
                    EvidenceRef(
                        snapshot_id=snapshot_ids[SnapshotKind.ATTENDANCE],
                        source_ref=att.source_ref,
                        field="status",
                    ),
                ),
            )
        )

    if op_id == ctx.event.subject_operator_id:
        issues.append(
            _issue(
                IssueCode.OPERATOR_UNAVAILABLE,
                IssueSeverity.BLOCKING,
                f"{op_id} is the reported unavailable subject of this episode.",
                subject=op_id,
                evidence=(EvidenceRef(snapshot_id="event", source_ref=ctx.event.source_ref),),
            )
        )

    skill = skills_by_key.get((op_id, slot.operation_id))
    skill_level = 0
    if skill is None:
        issues.append(
            _issue(
                IssueCode.SKILL_UNKNOWN,
                IssueSeverity.MATERIAL,
                f"Skill evidence for {op_id} on {slot.operation_id} is unknown; "
                "missing skill is never level zero.",
                subject=op_id,
                evidence=(
                    EvidenceRef(
                        snapshot_id=snapshot_ids.get(SnapshotKind.SKILLS, ""), field="skills"
                    ),
                ),
            )
        )
    else:
        skill_level = skill.level
        skill_ref = EvidenceRef(
            snapshot_id=snapshot_ids.get(SnapshotKind.SKILLS, ""),
            source_ref=skill.source_ref,
        )
        if skill.level < required_level:
            issues.append(
                _issue(
                    IssueCode.SKILL_INSUFFICIENT,
                    IssueSeverity.BLOCKING,
                    f"{op_id} holds skill level {skill.level} on {slot.operation_id}; "
                    f"level {required_level} is required.",
                    subject=op_id,
                    evidence=(skill_ref, EvidenceRef(snapshot_id=skill_ref.snapshot_id, source_ref=skill.source_ref, field="level")),
                )
            )
        if skill.assessed_at > ctx.decision_at:
            issues.append(
                _issue(
                    IssueCode.FUTURE_EVIDENCE,
                    IssueSeverity.MATERIAL,
                    f"Skill for {op_id} on {slot.operation_id} was assessed after the decision time.",
                    subject=op_id,
                    evidence=(EvidenceRef(snapshot_id=skill_ref.snapshot_id, source_ref=skill.source_ref, field="assessed_at"),),
                )
            )
        elif not _fresh(
            skill.assessed_at, ctx.decision_at, timedelta(seconds=settings.skill_max_age_seconds)
        ):
            issues.append(
                _issue(
                    IssueCode.SKILL_STALE,
                    IssueSeverity.MATERIAL,
                    f"Skill for {op_id} on {slot.operation_id} was assessed more than "
                    f"{settings.skill_max_age_seconds // 86400} day(s) before the decision time.",
                    subject=op_id,
                    evidence=(EvidenceRef(snapshot_id=skill_ref.snapshot_id, source_ref=skill.source_ref, field="assessed_at"),),
                )
            )

    overlapping = [
        a
        for a in assignments_by_op.get(op_id, [])
        if intervals.overlaps(a.starts_at, a.ends_at, ctx.target.starts_at, ctx.target.ends_at)
        # The vacancy removes the original operator's commitment to the target
        # slot only; every other commitment stands.
        and a.slot_id != slot.id
    ]
    for a in overlapping:
        issues.append(
            _issue(
                IssueCode.OVERLAPPING_ASSIGNMENT,
                IssueSeverity.BLOCKING,
                f"{op_id} already has an assignment overlapping the coverage interval "
                f"({a.starts_at.isoformat()} to {a.ends_at.isoformat()}, slot {a.slot_id or 'unslotted'}).",
                subject=op_id,
                evidence=(
                    EvidenceRef(
                        snapshot_id=snapshot_ids.get(SnapshotKind.ASSIGNMENTS, ""),
                        source_ref=a.source_ref,
                        field="starts_at/ends_at",
                    ),
                ),
            )
        )

    blocking = [i for i in issues if i.severity is IssueSeverity.BLOCKING]
    material = [i for i in issues if i.severity is IssueSeverity.MATERIAL]
    overlap_only = bool(blocking) and all(
        i.code is IssueCode.OVERLAPPING_ASSIGNMENT for i in blocking
    )
    return CandidateFinding(
        operator_id=op_id,
        core_eligible=not blocking or overlap_only,
        fully_supported=not blocking and not material,
        issues=issues,
        skill_level=skill_level,
        home_line_id=operator.home_line_id,
    )


class GateResult:
    __slots__ = (
        "blocked_outcome",
        "shared_issues",
        "candidates",
        "material_candidate_issues",
        "plan_payload",
        "slot",
    )

    def __init__(
        self,
        blocked_outcome: DomainOutcome | None,
        shared_issues: list[Issue],
        candidates: list[CandidateFinding],
        material_candidate_issues: list[Issue],
        plan_payload: PlanSnapshotPayload | None,
        slot: Slot | None,
    ) -> None:
        self.blocked_outcome = blocked_outcome
        self.shared_issues = shared_issues
        self.candidates = candidates
        self.material_candidate_issues = material_candidate_issues
        self.plan_payload = plan_payload
        self.slot = slot


def evaluate_gate(ctx: ReplayRequestContext, settings: GateFreshnessSettings) -> GateResult:
    blocking, conclusive = _check_shared(ctx, settings)
    pinned = PinnedInputs(catalog=ctx.catalog, snapshots=ctx.snapshots)
    plan = _plan_snapshot(pinned)
    plan_payload: PlanSnapshotPayload | None = plan.plan if plan is not None else None
    slot = (
        next((s for s in plan_payload.slots if s.id == ctx.target.slot_id), None)
        if plan_payload is not None
        else None
    )

    contradictions = [i for i in blocking if i.code is IssueCode.CONTRADICTORY_ASSERTIONS]
    evidence_blocks = [i for i in blocking if i.code is not IssueCode.CONTRADICTORY_ASSERTIONS]

    if contradictions:
        # Contradictions dominate: report both sets, block the policy.
        return GateResult(
            DomainOutcome.CONFLICTING_CONTEXT, blocking, [], [], plan_payload, slot
        )
    if conclusive:
        return GateResult(
            DomainOutcome.NO_FEASIBLE_CANDIDATE, evidence_blocks + conclusive, [], [], plan_payload, slot
        )
    if evidence_blocks:
        return GateResult(DomainOutcome.NEEDS_CONTEXT, blocking, [], [], plan_payload, slot)

    attendance_snap = _snapshot_of(pinned, SnapshotKind.ATTENDANCE)
    attendance_by_op: dict[str, AttendanceRecord] = {}
    if attendance_snap is not None and attendance_snap.attendance is not None:
        # Deterministic selection: when an export carries history for one
        # operator, the row with the latest observed_at is the operative one.
        # List order must never decide which evidence counts.
        for att_rec in attendance_snap.attendance:
            current_att = attendance_by_op.get(att_rec.operator_id)
            if current_att is None or att_rec.observed_at > current_att.observed_at:
                attendance_by_op[att_rec.operator_id] = att_rec
    assignments_snap = _snapshot_of(pinned, SnapshotKind.ASSIGNMENTS)
    assignments_by_op: dict[str, list[AssignmentRecord]] = {}
    if assignments_snap is not None and assignments_snap.assignments is not None:
        for asg_rec in assignments_snap.assignments:
            assignments_by_op.setdefault(asg_rec.operator_id, []).append(asg_rec)
    skills_snap = _snapshot_of(pinned, SnapshotKind.SKILLS)
    skills_by_key: dict[tuple[str, str], SkillRecord] = {}
    if skills_snap is not None and skills_snap.skills is not None:
        # Same rule as attendance: latest assessed_at wins, never list order.
        for skill_rec in skills_snap.skills:
            key = (skill_rec.operator_id, skill_rec.operation_id)
            current_skill = skills_by_key.get(key)
            if current_skill is None or skill_rec.assessed_at > current_skill.assessed_at:
                skills_by_key[key] = skill_rec
    snapshot_ids: dict[SnapshotKind, str] = {}
    for kind in SnapshotKind:
        snap = _snapshot_of(pinned, kind)
        if snap is not None:
            snapshot_ids[kind] = snap.id

    assert slot is not None  # shared checks guarantee the slot exists here
    op_def = next((o for o in ctx.catalog.operations if o.id == slot.operation_id), None)
    required_level = op_def.required_skill_level if op_def else 1

    candidates: list[CandidateFinding] = []
    material: list[Issue] = []
    for operator in ctx.catalog.operators:
        if not operator.active:
            continue
        finding = _evaluate_candidate(
            ctx,
            settings,
            operator,
            slot,
            required_level,
            snapshot_ids,
            attendance_by_op,
            assignments_by_op,
            skills_by_key,
        )
        candidates.append(finding)
        material.extend(i for i in finding.issues if i.severity is IssueSeverity.MATERIAL)

    return GateResult(None, [], candidates, material, plan_payload, slot)
