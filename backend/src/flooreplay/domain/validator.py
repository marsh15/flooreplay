"""Deterministic validation of a proposal.

The validator re-derives every check from the pinned evidence. It never
reads the policy's eligibility decisions: the policy proposes, the
validator independently verifies. Each rule returns PASS, FAIL, or
NOT_EVALUATED with a reason code and evidence; an unknown operator fails
C01 and makes dependent checks NOT_EVALUATED instead of manufacturing
observations.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta

from . import intervals
from .types import (
    AssignmentRecord,
    AttendanceRecord,
    ConstraintCode,
    ConstraintResult,
    EvidenceRef,
    GateFreshnessSettings,
    Machine,
    MachineStateRecord,
    OperationDef,
    PlanSnapshotPayload,
    Proposal,
    ReplayRequestContext,
    SkillRecord,
    Slot,
    SnapshotKind,
    Verdict,
)


def _result(
    code: ConstraintCode,
    verdict: Verdict,
    message: str,
    *,
    reason_code: str = "",
    evidence: tuple[EvidenceRef, ...] = (),
) -> ConstraintResult:
    return ConstraintResult(
        code=code, verdict=verdict, reason_code=reason_code, message=message, evidence=evidence
    )


def _ne(code: ConstraintCode) -> ConstraintResult:
    return _result(
        code,
        Verdict.NOT_EVALUATED,
        "Operator is unknown; dependent checks cannot be evaluated.",
        reason_code="DEPENDENT_ON_C01",
    )


class _Evidence:
    """Indexed access to the pinned evidence, with source references."""

    def __init__(self, ctx: ReplayRequestContext) -> None:
        self.attendance_by_op: dict[str, AttendanceRecord] = {}
        self.assignments: list[AssignmentRecord] = []
        self.skills_by_key: dict[tuple[str, str], SkillRecord] = {}
        self.machine_state_by_id: dict[str, MachineStateRecord] = {}
        self.plan: PlanSnapshotPayload | None = None
        self.snapshot_ids: dict[SnapshotKind, str] = {}
        for snap in ctx.snapshots:
            self.snapshot_ids[snap.kind] = snap.id
            if snap.attendance is not None:
                self.attendance_by_op = {rec.operator_id: rec for rec in snap.attendance}
            if snap.assignments is not None:
                self.assignments = list(snap.assignments)
            if snap.skills is not None:
                self.skills_by_key = {(r.operator_id, r.operation_id): r for r in snap.skills}
            if snap.machine_state is not None:
                self.machine_state_by_id = {r.machine_id: r for r in snap.machine_state}
            if snap.plan is not None:
                self.plan = snap.plan

    def ref(self, kind: SnapshotKind, source_ref: str = "", field: str = "") -> EvidenceRef:
        return EvidenceRef(
            snapshot_id=self.snapshot_ids.get(kind, kind.value),
            source_ref=source_ref,
            field=field,
        )

    def slot(self, slot_id: str) -> Slot | None:
        if self.plan is None:
            return None
        return next((s for s in self.plan.slots if s.id == slot_id), None)


def validate_proposal(
    proposal: Proposal,
    ctx: ReplayRequestContext,
    settings: GateFreshnessSettings,
    context_digest: str,
) -> list[ConstraintResult]:
    ev = _Evidence(ctx)
    plan = ev.plan

    operator = next((o for o in ctx.catalog.operators if o.id == proposal.operator_id), None)
    machine = next((m for m in ctx.catalog.machines if m.id == proposal.machine_id), None)
    op_def = next((o for o in ctx.catalog.operations if o.id == proposal.operation_id), None)
    slot = ev.slot(proposal.target_slot_id)

    if operator is None:
        c01 = _result(
            ConstraintCode.C01,
            Verdict.FAIL,
            f"Operator {proposal.operator_id} does not exist in the pinned catalog.",
            reason_code="OPERATOR_UNKNOWN",
        )
        return [
            c01,
            _ne(ConstraintCode.C02),
            _c03(proposal, plan),
            _ne(ConstraintCode.C04),
            _ne(ConstraintCode.C05),
            _c06(proposal, machine, op_def, ev.machine_state_by_id, ev),
            _ne(ConstraintCode.C07),
            _c08(proposal, ctx, slot),
            _c09(proposal, plan, ctx),
            _c10(proposal, ev.assignments, slot, ev),
            _c11(proposal, context_digest),
            _ne(ConstraintCode.C12),
        ]

    c01 = (
        _result(ConstraintCode.C01, Verdict.PASS, f"Operator {operator.id} exists and is active.")
        if operator.active
        else _result(
            ConstraintCode.C01,
            Verdict.FAIL,
            f"Operator {operator.id} is marked inactive in the catalog.",
            reason_code="OPERATOR_INACTIVE",
        )
    )

    return [
        c01,
        _c02(proposal, ctx, operator.id, ev),
        _c03(proposal, plan),
        *_c04_c05(proposal, ctx, operator.id, op_def, ev, settings),
        _c06(proposal, machine, op_def, ev.machine_state_by_id, ev),
        _c07(proposal, operator.id, ev.assignments, slot, ev),
        _c08(proposal, ctx, slot),
        _c09(proposal, plan, ctx),
        _c10(proposal, ev.assignments, slot, ev),
        _c11(proposal, context_digest),
        _c12(proposal, ctx, operator.id),
    ]


def _c02(
    proposal: Proposal, ctx: ReplayRequestContext, operator_id: str, ev: _Evidence
) -> ConstraintResult:
    att = ev.attendance_by_op.get(operator_id)
    if att is None or att.status.value == "UNKNOWN":
        return _result(
            ConstraintCode.C02,
            Verdict.FAIL,
            f"Attendance for {operator_id} is unknown; a proposal requires recorded presence.",
            reason_code="ATTENDANCE_UNKNOWN",
            evidence=(ev.ref(SnapshotKind.ATTENDANCE, att.source_ref if att else "", "status"),),
        )
    if att.status.value == "ABSENT":
        return _result(
            ConstraintCode.C02,
            Verdict.FAIL,
            f"Operator {operator_id} is recorded absent at {att.observed_at.isoformat()}.",
            reason_code="OPERATOR_ABSENT",
            evidence=(ev.ref(SnapshotKind.ATTENDANCE, att.source_ref, "status"),),
        )
    if operator_id == ctx.event.subject_operator_id:
        return _result(
            ConstraintCode.C02,
            Verdict.FAIL,
            f"Operator {operator_id} is the reported unavailable subject of this episode.",
            reason_code="OPERATOR_UNAVAILABLE",
            evidence=(EvidenceRef(snapshot_id="event", source_ref=ctx.event.source_ref),),
        )
    return _result(
        ConstraintCode.C02,
        Verdict.PASS,
        f"Operator {operator_id} is recorded present and is not the unavailable subject.",
        evidence=(ev.ref(SnapshotKind.ATTENDANCE, att.source_ref, "status"),),
    )


def _c03(proposal: Proposal, plan: PlanSnapshotPayload | None) -> ConstraintResult:
    if plan is None:
        return _result(
            ConstraintCode.C03, Verdict.NOT_EVALUATED, "No pinned plan.", reason_code="NO_PLAN"
        )
    slot = next((s for s in plan.slots if s.id == proposal.target_slot_id), None)
    if slot is None:
        return _result(
            ConstraintCode.C03,
            Verdict.FAIL,
            f"Target slot {proposal.target_slot_id} is not in the pinned plan.",
            reason_code="SLOT_UNKNOWN",
        )
    try:
        intervals.validate(proposal.starts_at, proposal.ends_at, "coverage interval")
    except ValueError as exc:
        return _result(ConstraintCode.C03, Verdict.FAIL, str(exc), reason_code="INVALID_INTERVAL")
    if not intervals.contains(slot.starts_at, slot.ends_at, proposal.starts_at, proposal.ends_at):
        return _result(
            ConstraintCode.C03,
            Verdict.FAIL,
            "Coverage interval does not fit inside the target slot.",
            reason_code="OUTSIDE_SLOT",
        )
    if not intervals.contains(
        plan.shift_starts_at, plan.shift_ends_at, proposal.starts_at, proposal.ends_at
    ):
        return _result(
            ConstraintCode.C03,
            Verdict.FAIL,
            "Coverage interval does not fit inside the shift.",
            reason_code="OUTSIDE_SHIFT",
        )
    return _result(
        ConstraintCode.C03,
        Verdict.PASS,
        "Coverage interval fits inside both the target slot and the shift.",
    )


def _c04_c05(
    proposal: Proposal,
    ctx: ReplayRequestContext,
    operator_id: str,
    op_def: OperationDef | None,
    ev: _Evidence,
    settings: GateFreshnessSettings,
) -> tuple[ConstraintResult, ConstraintResult]:
    skill = ev.skills_by_key.get((operator_id, proposal.operation_id))
    required = op_def.required_skill_level if op_def else 1
    if skill is None:
        return (
            _result(
                ConstraintCode.C04,
                Verdict.FAIL,
                f"No skill evidence for {operator_id} on {proposal.operation_id}.",
                reason_code="SKILL_UNKNOWN",
                evidence=(ev.ref(SnapshotKind.SKILLS, field="skills"),),
            ),
            _result(
                ConstraintCode.C05,
                Verdict.FAIL,
                "Skill freshness cannot be established without a skill record.",
                reason_code="SKILL_UNKNOWN",
                evidence=(ev.ref(SnapshotKind.SKILLS, field="skills"),),
            ),
        )

    level_result = (
        _result(
            ConstraintCode.C04,
            Verdict.PASS,
            f"Operator {operator_id} holds skill level {skill.level} "
            f"(required {required}) on {proposal.operation_id}.",
            evidence=(ev.ref(SnapshotKind.SKILLS, skill.source_ref),),
        )
        if skill.level >= required
        else _result(
            ConstraintCode.C04,
            Verdict.FAIL,
            f"Operator {operator_id} holds skill level {skill.level}; "
            f"level {required} is required on {proposal.operation_id}.",
            reason_code="SKILL_INSUFFICIENT",
            evidence=(ev.ref(SnapshotKind.SKILLS, skill.source_ref),),
        )
    )
    skill_ev = ev.ref(SnapshotKind.SKILLS, skill.source_ref, "assessed_at")
    if skill.assessed_at > ctx.decision_at:
        freshness = _result(
            ConstraintCode.C05,
            Verdict.FAIL,
            "Skill was assessed after the decision time; not knowable when deciding.",
            reason_code="FUTURE_EVIDENCE",
            evidence=(skill_ev,),
        )
    elif ctx.decision_at - skill.assessed_at <= timedelta(seconds=settings.skill_max_age_seconds):
        freshness = _result(
            ConstraintCode.C05,
            Verdict.PASS,
            f"Skill evidence is fresh (assessed {skill.assessed_at.isoformat()}).",
            evidence=(skill_ev,),
        )
    else:
        freshness = _result(
            ConstraintCode.C05,
            Verdict.FAIL,
            f"Skill evidence is stale: assessed {skill.assessed_at.isoformat()}, "
            f"budget is {settings.skill_max_age_seconds}s before the decision time.",
            reason_code="SKILL_STALE",
            evidence=(skill_ev,),
        )
    return level_result, freshness


def _c06(
    proposal: Proposal,
    machine: Machine | None,
    op_def: OperationDef | None,
    machine_state: Mapping[str, MachineStateRecord],
    ev: _Evidence,
) -> ConstraintResult:
    if machine is None:
        return _result(
            ConstraintCode.C06,
            Verdict.FAIL,
            f"Machine {proposal.machine_id} is not in the pinned catalog.",
            reason_code="MACHINE_UNKNOWN",
        )
    if op_def is not None and op_def.id not in machine.compatible_operation_ids:
        return _result(
            ConstraintCode.C06,
            Verdict.FAIL,
            f"Machine {proposal.machine_id} is not compatible with {proposal.operation_id}.",
            reason_code="MACHINE_INCOMPATIBLE",
        )
    state = machine_state.get(proposal.machine_id)
    if state is None:
        return _result(
            ConstraintCode.C06,
            Verdict.FAIL,
            f"No machine-state evidence for {proposal.machine_id}.",
            reason_code="MACHINE_STATE_UNKNOWN",
            evidence=(ev.ref(SnapshotKind.MACHINE_STATE),),
        )
    if not state.usable:
        return _result(
            ConstraintCode.C06,
            Verdict.FAIL,
            f"Machine {proposal.machine_id} is recorded unusable: {state.detail}.",
            reason_code="MACHINE_UNUSABLE",
            evidence=(ev.ref(SnapshotKind.MACHINE_STATE, state.source_ref),),
        )
    return _result(
        ConstraintCode.C06,
        Verdict.PASS,
        f"Machine {proposal.machine_id} exists, is compatible, and is recorded usable.",
        evidence=(ev.ref(SnapshotKind.MACHINE_STATE, state.source_ref),),
    )


def _c07(
    proposal: Proposal,
    operator_id: str,
    assignments: list[AssignmentRecord],
    slot: Slot | None,
    ev: _Evidence,
) -> ConstraintResult:
    overlapping = [
        a
        for a in assignments
        if a.operator_id == operator_id
        and intervals.overlaps(a.starts_at, a.ends_at, proposal.starts_at, proposal.ends_at)
        # The vacancy removes only the target slot's commitment for the
        # original operator; all other commitments stand.
        and not (slot is not None and a.slot_id == slot.id)
    ]
    if overlapping:
        a = overlapping[0]
        return _result(
            ConstraintCode.C07,
            Verdict.FAIL,
            f"Operator {operator_id} has an overlapping assignment "
            f"({a.starts_at.isoformat()} to {a.ends_at.isoformat()}, slot {a.slot_id or 'unslotted'}).",
            reason_code="OVERLAPPING_ASSIGNMENT",
            evidence=(ev.ref(SnapshotKind.ASSIGNMENTS, a.source_ref, "interval"),),
        )
    return _result(
        ConstraintCode.C07,
        Verdict.PASS,
        f"Operator {operator_id} has no assignment overlapping the coverage interval.",
        evidence=(ev.ref(SnapshotKind.ASSIGNMENTS),),
    )


def _c08(proposal: Proposal, ctx: ReplayRequestContext, slot: Slot | None) -> ConstraintResult:
    style = next((st for st in ctx.catalog.styles if st.id == proposal.style_id), None)
    if style is None:
        return _result(
            ConstraintCode.C08,
            Verdict.FAIL,
            f"Style {proposal.style_id} is not in the pinned catalog.",
            reason_code="STYLE_UNKNOWN",
        )
    if proposal.operation_id not in style.operation_ids:
        return _result(
            ConstraintCode.C08,
            Verdict.FAIL,
            f"Operation {proposal.operation_id} is not part of style {style.code}.",
            reason_code="OPERATION_NOT_IN_STYLE",
        )
    return _result(
        ConstraintCode.C08,
        Verdict.PASS,
        f"Operation {proposal.operation_id} belongs to style {style.code}.",
    )


def _c09(
    proposal: Proposal, plan: PlanSnapshotPayload | None, ctx: ReplayRequestContext
) -> ConstraintResult:
    if plan is None:
        return _result(ConstraintCode.C09, Verdict.FAIL, "No pinned plan.", reason_code="NO_PLAN")
    if proposal.plan_revision != plan.revision:
        return _result(
            ConstraintCode.C09,
            Verdict.FAIL,
            f"Proposal references plan revision {proposal.plan_revision}; "
            f"the pinned plan is {plan.revision}.",
            reason_code="PLAN_MISMATCH",
        )
    slot = next((s for s in plan.slots if s.id == proposal.target_slot_id), None)
    if slot is None:
        return _result(
            ConstraintCode.C09,
            Verdict.FAIL,
            f"Target slot {proposal.target_slot_id} is not in the pinned plan.",
            reason_code="SLOT_UNKNOWN",
        )
    mismatches = []
    if slot.machine_id != proposal.machine_id:
        mismatches.append("machine")
    if slot.operation_id != proposal.operation_id:
        mismatches.append("operation")
    if slot.style_id != proposal.style_id:
        mismatches.append("style")
    if slot.line_id != ctx.target.line_id:
        mismatches.append("line")
    if mismatches:
        return _result(
            ConstraintCode.C09,
            Verdict.FAIL,
            "Proposal does not match the pinned slot on: " + ", ".join(mismatches) + ".",
            reason_code="SLOT_MISMATCH",
        )
    return _result(
        ConstraintCode.C09,
        Verdict.PASS,
        f"Proposal references the pinned plan and slot {proposal.target_slot_id}.",
    )


def _c10(
    proposal: Proposal,
    assignments: list[AssignmentRecord],
    slot: Slot | None,
    ev: _Evidence,
) -> ConstraintResult:
    reservations = [
        a
        for a in assignments
        if a.machine_id == proposal.machine_id
        and intervals.overlaps(a.starts_at, a.ends_at, proposal.starts_at, proposal.ends_at)
        # The target slot's own machine usage is the vacancy being filled.
        and not (slot is not None and a.slot_id == slot.id)
    ]
    if reservations:
        a = reservations[0]
        return _result(
            ConstraintCode.C10,
            Verdict.FAIL,
            f"Machine {proposal.machine_id} has an overlapping reservation by {a.operator_id} "
            f"({a.starts_at.isoformat()} to {a.ends_at.isoformat()}).",
            reason_code="MACHINE_RESERVED",
            evidence=(ev.ref(SnapshotKind.ASSIGNMENTS, a.source_ref, "interval"),),
        )
    return _result(
        ConstraintCode.C10,
        Verdict.PASS,
        f"No overlapping reservation on machine {proposal.machine_id}.",
        evidence=(ev.ref(SnapshotKind.ASSIGNMENTS),),
    )


def _c11(proposal: Proposal, context_digest: str) -> ConstraintResult:
    if proposal.context_digest == context_digest:
        return _result(
            ConstraintCode.C11, Verdict.PASS, "Proposal references the supplied context digest."
        )
    return _result(
        ConstraintCode.C11,
        Verdict.FAIL,
        "Proposal does not reference the supplied context digest.",
        reason_code="CONTEXT_DIGEST_MISMATCH",
    )


def _c12(proposal: Proposal, ctx: ReplayRequestContext, operator_id: str) -> ConstraintResult:
    if operator_id != ctx.event.subject_operator_id:
        return _result(ConstraintCode.C12, Verdict.PASS, "Operator is not the unavailable subject.")
    return _result(
        ConstraintCode.C12,
        Verdict.FAIL,
        "Operator is the reported unavailable subject of this episode.",
        reason_code="OPERATOR_UNAVAILABLE",
        evidence=(EvidenceRef(snapshot_id="event", source_ref=ctx.event.source_ref),),
    )
