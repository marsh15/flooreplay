"""ContextGate: is the as-known evidence good enough to decide an order?

Pure: the only clock is `snapshot.cutoff`; there is no database, randomness or `now()`.
Ports the ideas of the archived gate (inclusive freshness, latest-wins, UNKNOWN is never
zero, findings that carry the facts they are about) to facts, policy-owned freshness and
declarative conflict rules.

Precedence is CONFLICTING > INCOMPLETE > STALE > READY and every finding is kept, so a
reviewer sees all the problems, not only the worst one. Findings in state READY (a conflict
that a resolution cleared) are kept as evidence and never raise the overall state.

Freshness. The limit for a fact comes from the *kind* (`NATIVE_SOURCE`), never from the
`source` the fact happens to carry: a reviewer correction of a stale lot is still a stale
lot. Every observation is aged by `valid_from` against the cutoff, inclusive. Only a
`resolution` (a decision, not an observation) is exempt.

Artifact coverage is passed explicitly: `coverage` maps an artifact id to a `CoverageDecl`
(profile, as_of, qualities). Only the newest `erp_fabric_stock` declaration (by as_of, ties
broken by the greatest artifact id) is used: an older export never makes a quality covered.
A quality with lots for a colour needs no declaration. A quality with no lot for a colour is
a known zero if the used artifact declares it (aged by that artifact's as_of) and INCOMPLETE
otherwise. `GateResult.coverage_used` echoes the artifact used so a decision digest can
include it. Callers pass only artifacts known at the cutoff.

Conflict rules join facts by entity_key and compare valid time as half-open intervals.
Observation kinds contribute only their current fact (`current()`; the tied facts on a
payload tie); their `valid_to` is ignored, as in the snapshot. Event kinds contribute every
visible fact with its own interval.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Final

from pydantic import field_validator

from flooreplay.decisions.facts import (
    EVENT_KINDS,
    BomPayload,
    FabricAllocationPayload,
    FabricInboundPayload,
    FabricLotPayload,
    FabricQcPayload,
    OrderRequestPayload,
    ResolutionPayload,
    parse_payload,
)
from flooreplay.decisions.policy import ConflictRule, PolicyDocument, sewing_days
from flooreplay.decisions.snapshot import (
    COMPETING_REPLACEMENT,
    INVALID_PAYLOAD,
    CurrentStatus,
    Finding,
    Snapshot,
    current,
    events,
)
from flooreplay.decisions.types import (
    Fact,
    FactKind,
    FrozenModel,
    GateState,
    Instant,
    SourceProfile,
    combine_gate_states,
)
from flooreplay.domain import intervals

# Finding codes.
ORDER_REQUEST_MISSING = "order_request_missing"
BOM_MISSING = "bom_missing"
FABRIC_STOCK_UNCOVERED = "fabric_stock_uncovered"
TRIM_STATUS_MISSING = "trim_status_missing"
LINE_CAPACITY_MISSING = "line_capacity_missing"
GSM_WIDTH_MISSING = "gsm_width_missing"
STALE_EVIDENCE = "stale_evidence"
TIE_CONFLICT = "tie_conflict"
CONFLICT_RULE = "conflict_rule"
CONFLICT_RESOLVED = "conflict_resolved"
BAD_DATES = "bad_dates"

_OPEN_END = datetime.max.replace(tzinfo=UTC)
_STATE_ORDER = {
    GateState.CONFLICTING: 0,
    GateState.INCOMPLETE: 1,
    GateState.STALE: 2,
    GateState.READY: 3,
}

# The export each kind of observation arrives in, and so the freshness limit that applies.
NATIVE_SOURCE: Final[Mapping[FactKind, SourceProfile]] = {
    FactKind.ORDER_REQUEST: SourceProfile.ORDER_REQUESTS,
    FactKind.BOM: SourceProfile.ORDER_REQUESTS,
    FactKind.FABRIC_LOT: SourceProfile.ERP_FABRIC_STOCK,
    FactKind.FABRIC_ALLOCATION: SourceProfile.ERP_FABRIC_STOCK,
    FactKind.TRIM_STATUS: SourceProfile.SHEET_TRIMS_STATUS,
    FactKind.LINE_CAPACITY: SourceProfile.SHIFT_CAPACITY,
    FactKind.LINE_COMMITMENT: SourceProfile.SHIFT_CAPACITY,
    FactKind.FABRIC_INBOUND: SourceProfile.SUPPLIER_UPDATES,
}

# Kinds an order decision reads; an excluded (invalid) fact of one of these is missing evidence.
CONSUMED_KINDS: Final = frozenset(
    {
        FactKind.ORDER_REQUEST,
        FactKind.BOM,
        FactKind.FABRIC_LOT,
        FactKind.FABRIC_QC,
        FactKind.FABRIC_INBOUND,
        FactKind.FABRIC_ALLOCATION,
        FactKind.TRIM_STATUS,
        FactKind.LINE_CAPACITY,
        FactKind.LINE_COMMITMENT,
    }
)


def native_source(fact: Fact) -> SourceProfile | None:
    """The freshness source for a fact by kind; None for a resolution (a decision, not data)."""
    if fact.kind is FactKind.RESOLUTION:
        return None
    if fact.kind is FactKind.FABRIC_QC:
        # A QC claim comes from a note or from a supplier's update; it says which.
        origin = _typed(fact, FabricQcPayload).origin
        return SourceProfile.SUPPLIER_UPDATES if origin == "supplier_updates" else SourceProfile.NOTES
    return NATIVE_SOURCE[fact.kind]


class CoverageDecl(FrozenModel):
    """What one stock export declares it covers."""

    profile: SourceProfile
    as_of: Instant
    qualities: frozenset[str]

    @field_validator("qualities", mode="before")
    @classmethod
    def _not_a_bare_string(cls, v: object) -> object:
        if isinstance(v, str | bytes):
            raise ValueError("qualities must be a collection of quality ids, not one string")
        return v


class CoverageUsed(FrozenModel):
    artifact_id: str
    as_of: Instant
    qualities: tuple[str, ...]  # sorted


class GateFinding(FrozenModel):
    code: str
    state: GateState
    entity_key: str
    fact_ids: tuple[str, ...]
    detail: str
    rule_id: str | None = None  # set on conflict_rule / conflict_resolved


class GateResult(FrozenModel):
    state: GateState
    findings: tuple[GateFinding, ...]
    coverage_used: CoverageUsed | None = None


def _typed[P](fact: Fact, model: type[P]) -> P:
    parsed = parse_payload(fact)
    if not isinstance(parsed, model):  # registry guarantees the model for the kind
        raise TypeError(f"{fact.kind.value} fact {fact.id} did not parse as {model.__name__}")
    return parsed


def _visible_of(snapshot: Snapshot, kind: FactKind) -> list[Fact]:
    return [f for f in snapshot.facts if f.kind == kind]


def newest_erp_coverage(
    coverage: Mapping[str, CoverageDecl], cutoff: datetime
) -> tuple[str, CoverageDecl] | None:
    """The one stock-export declaration the gate trusts: newest as_of, then greatest id."""
    usable = [
        (decl.as_of, artifact_id)
        for artifact_id, decl in coverage.items()
        if decl.profile is SourceProfile.ERP_FABRIC_STOCK and decl.as_of <= cutoff
    ]
    if not usable:
        return None
    _, artifact_id = max(usable)
    return artifact_id, coverage[artifact_id]


class _Gate:
    def __init__(
        self, snapshot: Snapshot, policy: PolicyDocument, coverage: Mapping[str, CoverageDecl]
    ) -> None:
        self.snapshot = snapshot
        self.policy = policy
        self.used = newest_erp_coverage(coverage, snapshot.cutoff)
        self.findings: list[GateFinding] = []
        self.relevant: set[str] = set()
        self.optional_observations: set[tuple[FactKind, str]] = set()
        self.rule_fact_ids: set[str] = set()
        # What is known about the order so far; None means "not known", never "none".
        self.order_id = ""
        self.style_id: str | None = None
        self.colours: set[str] | None = None
        self.quality: str | None = None
        self.trim_ids: set[str] | None = None
        self.window: set[str] | None = None

    def add(
        self,
        code: str,
        state: GateState,
        entity_key: str,
        fact_ids: Iterable[str],
        detail: str,
        rule_id: str | None = None,
    ) -> None:
        self.findings.append(
            GateFinding(
                code=code,
                state=state,
                entity_key=entity_key,
                fact_ids=tuple(fact_ids),
                detail=detail,
                rule_id=rule_id,
            )
        )

    # -- single required entity ------------------------------------------------

    def fresh_check(self, fact: Fact) -> None:
        """STALE iff age = cutoff - valid_from > the kind's limit (equal is fresh)."""
        source = native_source(fact)
        if source is None:
            return
        limit_hours: int = getattr(self.policy.freshness_hours, source.value)
        age = self.snapshot.cutoff - fact.valid_from
        if age > timedelta(hours=limit_hours):
            hours = age.total_seconds() / 3600
            self.add(
                STALE_EVIDENCE,
                GateState.STALE,
                fact.entity_key,
                (fact.id,),
                f"{fact.kind.value} fact is {hours:.2f} h old at the cutoff; "
                f"the {source.value} limit is {limit_hours} h",
            )

    def require(
        self, kind: FactKind, entity_key: str, missing_code: str, what: str
    ) -> Fact | None:
        """The current fact of a required entity, or None after recording why not."""
        self.relevant.add(entity_key)
        result = current(self.snapshot, kind, entity_key)
        if result.status is CurrentStatus.UNKNOWN:
            self.add(
                missing_code,
                GateState.INCOMPLETE,
                entity_key,
                (),
                f"no {what} is known at the cutoff; unknown is not zero",
            )
            return None
        if result.status is CurrentStatus.COMPETING:
            return None  # reported once by competing(), which covers every relevant entity
        if result.status is CurrentStatus.TIE_CONFLICT or result.fact is None:
            self.tie(entity_key, result.facts)
            return None
        self.fresh_check(result.fact)
        return result.fact

    def tie(self, entity_key: str, tied: Iterable[Fact]) -> None:
        self.add(
            TIE_CONFLICT,
            GateState.CONFLICTING,
            entity_key,
            (f.id for f in tied),
            "facts with the same valid_from disagree on their content",
        )

    # -- the order -----------------------------------------------------------

    def run(self, order_id: str) -> None:
        self.order_id = order_id
        order_fact = self.require(
            FactKind.ORDER_REQUEST, f"order:{order_id}", ORDER_REQUEST_MISSING, "order request"
        )
        if order_fact is not None:
            order = _typed(order_fact, OrderRequestPayload)
            self.style_id = order.style_id
            self.colours = {c.colour for c in order.colours}
            bom_fact = self.require(
                FactKind.BOM, f"bom:{order.style_id}", BOM_MISSING, f"BOM for style {order.style_id}"
            )
            if bom_fact is not None:
                bom = _typed(bom_fact, BomPayload)
                self.quality = bom.fabric_quality
                self.trim_ids = {t.trim_id for t in bom.trims}
                self.fabric(bom, sorted(self.colours))
                for trim in bom.trims:
                    key = f"trim:{order.style_id}:{trim.trim_id}"
                    self.require(FactKind.TRIM_STATUS, key, TRIM_STATUS_MISSING, "trim status")
            self.capacity(order_fact, order)
        self.competing()
        self.rules()
        self.optional_ties()
        self.invalid_payloads()

    # -- fabric --------------------------------------------------------------

    def fabric(self, bom: BomPayload, colours: list[str]) -> None:
        quality = bom.fabric_quality
        bom_unit = bom.consumption_per_pc.unit
        wanted = set(colours)
        stocked: dict[str, list[Fact]] = {c: [] for c in colours}
        lot_colour: dict[str, str] = {}
        has_factors: dict[str, bool] = {c: False for c in colours}

        by_key: dict[str, list[Fact]] = {}
        for fact in _visible_of(self.snapshot, FactKind.FABRIC_LOT):
            by_key.setdefault(fact.entity_key, []).append(fact)
        for key in sorted(by_key):
            matches = [
                p
                for p in (_typed(f, FabricLotPayload) for f in by_key[key])
                if p.fabric_quality == quality and p.colour in wanted
            ]
            if not matches:
                continue
            self.relevant.add(key)
            result = current(self.snapshot, FactKind.FABRIC_LOT, key)
            if result.status is CurrentStatus.COMPETING:
                continue  # reported once by competing()
            if result.status is CurrentStatus.TIE_CONFLICT or result.fact is None:
                self.tie(key, result.facts)
                continue
            lot = _typed(result.fact, FabricLotPayload)
            if lot.fabric_quality != quality or lot.colour not in wanted:
                continue  # the newest observation moved the lot elsewhere
            stocked[lot.colour].append(result.fact)
            lot_colour[key] = lot.colour
            self.fresh_check(result.fact)
            if lot.gsm is not None and lot.width_m is not None:
                has_factors[lot.colour] = True
            elif lot.qty.unit != bom_unit:
                self.unit_gap(key, result.fact, f"lot is in {lot.qty.unit.value}", bom_unit.value)

        self.known_zero_check(quality, colours, stocked)

        # Inbound, allocations and QC feed FABRIC/SAFETY too. A unit that differs from the
        # BOM's needs GSM and width from a current lot of the same quality and colour.
        for fact in _visible_of(self.snapshot, FactKind.FABRIC_INBOUND):
            inbound = _typed(fact, FabricInboundPayload)
            if inbound.fabric_quality == quality and inbound.colour in wanted:
                self.relevant.add(fact.entity_key)
                self.optional_observations.add((FactKind.FABRIC_INBOUND, fact.entity_key))
        for fact in _visible_of(self.snapshot, FactKind.FABRIC_ALLOCATION):
            parts = fact.entity_key.split(":")
            if len(parts) == 4 and parts[2] == quality and parts[3] in wanted:
                self.relevant.add(fact.entity_key)
                self.optional_observations.add((FactKind.FABRIC_ALLOCATION, fact.entity_key))

        for kind, key in sorted(self.optional_observations, key=lambda p: (p[0].value, p[1])):
            if kind not in (FactKind.FABRIC_INBOUND, FactKind.FABRIC_ALLOCATION):
                continue
            result = current(self.snapshot, kind, key)
            if result.fact is None:
                continue
            if kind is FactKind.FABRIC_INBOUND:
                inbound = _typed(result.fact, FabricInboundPayload)
                colour, unit = inbound.colour, inbound.qty.unit
            else:
                colour, unit = key.split(":")[3], _typed(result.fact, FabricAllocationPayload).qty.unit
            if unit != bom_unit and not has_factors.get(colour, False):
                self.unit_gap(key, result.fact, f"{kind.value} is in {unit.value}", bom_unit.value)
        for key in sorted(lot_colour):
            for qc in events(self.snapshot, FactKind.FABRIC_QC, key):
                unit = _typed(qc, FabricQcPayload).qty.unit
                if unit != bom_unit and not has_factors[lot_colour[key]]:
                    self.unit_gap(key, qc, f"QC claim is in {unit.value}", bom_unit.value)

    def unit_gap(self, key: str, fact: Fact, what: str, bom_unit: str) -> None:
        self.add(
            GSM_WIDTH_MISSING,
            GateState.INCOMPLETE,
            key,
            (fact.id,),
            f"{what} but the BOM is in {bom_unit}; a current lot of the same quality and "
            "colour needs both gsm and width",
        )

    def known_zero_check(
        self, quality: str, colours: list[str], stocked: Mapping[str, list[Fact]]
    ) -> None:
        """A colour with no lot is a known zero only if the newest stock export covers the quality."""
        bare = [c for c in colours if not stocked[c]]
        if not bare:
            return
        covered = self.used is not None and quality in self.used[1].qualities
        for colour in bare:
            if not covered:
                self.add(
                    FABRIC_STOCK_UNCOVERED,
                    GateState.INCOMPLETE,
                    f"coverage:{quality}:{colour}",
                    (),
                    f"no lot of {quality} in {colour} and the newest stock export does not "
                    f"declare {quality} covered; unknown is not zero",
                )
        if covered and self.used is not None:
            artifact_id, decl = self.used
            limit = self.policy.freshness_hours.erp_fabric_stock
            age = self.snapshot.cutoff - decl.as_of
            if age > timedelta(hours=limit):
                self.add(
                    STALE_EVIDENCE,
                    GateState.STALE,
                    f"coverage:{artifact_id}",
                    (),
                    f"the stock export behind a known zero is {age.total_seconds() / 3600:.2f} h "
                    f"old at the cutoff; the erp_fabric_stock limit is {limit} h",
                )

    # -- capacity ------------------------------------------------------------

    def capacity(self, order_fact: Fact, order: OrderRequestPayload) -> None:
        try:
            days = sewing_days(self.policy.capacity, order.ship_date)
        except OverflowError:
            self.add(
                BAD_DATES,
                GateState.INCOMPLETE,
                order_fact.entity_key,
                (order_fact.id,),
                f"the sewing window for ship date {order.ship_date} is outside the calendar",
            )
            return
        self.window = {d.isoformat() for d in days}
        lines = self.policy.capacity.eligible_lines
        for line in lines:
            for day in days:
                key = f"line:{line}:{day.isoformat()}"
                self.require(FactKind.LINE_CAPACITY, key, LINE_CAPACITY_MISSING, "line capacity")
        for fact in _visible_of(self.snapshot, FactKind.LINE_COMMITMENT):
            parts = fact.entity_key.split(":")
            if len(parts) == 4 and parts[2] in lines and parts[3] in self.window:
                self.relevant.add(fact.entity_key)
                self.optional_observations.add((FactKind.LINE_COMMITMENT, fact.entity_key))

    # -- competing replacements and excluded facts -------------------------------

    def competing(self) -> None:
        """Two visible replacements of one fact are never silently resolved."""
        for item in self.snapshot.findings:
            if item.code != COMPETING_REPLACEMENT or item.entity_key not in self.relevant:
                continue  # competition over something this order does not use
            self.add(
                COMPETING_REPLACEMENT,
                GateState.CONFLICTING,
                item.entity_key,
                item.fact_ids,
                f"fact {item.subject_id} has several visible replacements",
            )

    def invalid_payloads(self) -> None:
        """A fact the snapshot excluded is missing evidence, never zero."""
        for item in self.snapshot.findings:
            if item.code == INVALID_PAYLOAD and self.invalid_is_relevant(item):
                self.add(
                    INVALID_PAYLOAD,
                    GateState.INCOMPLETE,
                    item.entity_key,
                    item.fact_ids,
                    f"fact {item.subject_id} was excluded from the snapshot: {item.detail}",
                )

    def invalid_is_relevant(self, item: Finding) -> bool:
        """Could the excluded fact have been evidence for this order?

        Narrowed by the entity_key text when it parses; anything that cannot be placed
        (unparseable key, bad_entity_key, unknown context) counts as relevant.
        """
        kind, parts = item.kind, item.entity_key.split(":")
        if kind not in CONSUMED_KINDS:
            return False
        if item.detail == "bad_entity_key":
            return True
        shapes = {
            FactKind.ORDER_REQUEST: 2,
            FactKind.BOM: 2,
            FactKind.TRIM_STATUS: 3,
            FactKind.LINE_CAPACITY: 3,
            FactKind.LINE_COMMITMENT: 4,
            FactKind.FABRIC_ALLOCATION: 4,
        }
        if kind in shapes and len(parts) != shapes[kind]:
            return True
        match kind:
            case FactKind.ORDER_REQUEST:
                return parts[1] == self.order_id
            case FactKind.BOM:
                return self.style_id is None or parts[1] == self.style_id
            case FactKind.TRIM_STATUS:
                return (self.style_id is None or parts[1] == self.style_id) and (
                    self.trim_ids is None or parts[2] in self.trim_ids
                )
            case FactKind.LINE_CAPACITY:
                return parts[1] in self.policy.capacity.eligible_lines and (
                    self.window is None or parts[2] in self.window
                )
            case FactKind.LINE_COMMITMENT:
                return parts[2] in self.policy.capacity.eligible_lines and (
                    self.window is None or parts[3] in self.window
                )
            case FactKind.FABRIC_ALLOCATION:
                return (self.quality is None or parts[2] == self.quality) and (
                    self.colours is None or parts[3] in self.colours
                )
            case FactKind.FABRIC_QC:
                return item.entity_key in self.relevant
            case _:  # fabric_lot and fabric_inbound keys say nothing about quality or colour
                return True

    # -- declarative conflict rules -----------------------------------------

    def candidates(self, kind: FactKind) -> list[Fact]:
        """Facts of `kind` the rules may pair, on entities this order uses.

        Events: every visible fact. Observations: the current fact only, or the tied facts
        when the newest observations disagree.
        """
        out: list[Fact] = []
        for key in sorted(self.relevant):
            if kind in EVENT_KINDS:
                out.extend(events(self.snapshot, kind, key))
                continue
            result = current(self.snapshot, kind, key)
            if result.status is CurrentStatus.FOUND and result.fact is not None:
                out.append(result.fact)
            elif result.status is CurrentStatus.TIE_CONFLICT:
                out.extend(result.facts)
        return out

    @staticmethod
    def end_of(fact: Fact) -> datetime:
        """Observations stay valid until superseded (valid_to is ignored); events keep theirs."""
        if fact.kind in EVENT_KINDS and fact.valid_to is not None:
            return fact.valid_to
        return _OPEN_END

    def rules(self) -> None:
        for rule in self.policy.conflict_rules:
            self.apply_rule(rule)

    def apply_rule(self, rule: ConflictRule) -> None:
        predicate = self.policy.predicate_for(rule)
        lefts = self.candidates(rule.left_kind)
        rights = self.candidates(rule.right_kind)
        same_kind = rule.left_kind == rule.right_kind
        for left in lefts:
            for right in rights:
                if left.entity_key != right.entity_key or left.id == right.id:
                    continue
                if same_kind and left.id > right.id:
                    continue  # unordered pair: look at it once
                if not intervals.overlaps(
                    left.valid_from, self.end_of(left), right.valid_from, self.end_of(right)
                ):
                    continue
                if not predicate(left, right):
                    continue
                self.rule_fact_ids.update((left.id, right.id))
                resolution = self.resolution_for(rule, left, right, symmetric=same_kind)
                if resolution is None:
                    self.add(
                        CONFLICT_RULE,
                        GateState.CONFLICTING,
                        left.entity_key,
                        (left.id, right.id),
                        f"rule {rule.id}: {left.id} and {right.id} conflict and no "
                        "reviewed resolution is known at the cutoff",
                        rule.id,
                    )
                else:
                    self.add(
                        CONFLICT_RESOLVED,
                        GateState.READY,
                        left.entity_key,
                        (left.id, right.id, resolution.id),
                        f"rule {rule.id}: resolved by {resolution.id}",
                        rule.id,
                    )

    def resolution_for(
        self, rule: ConflictRule, left: Fact, right: Fact, *, symmetric: bool
    ) -> Fact | None:
        """A visible, reviewed resolution on the pair's entity naming this rule and pair.

        Visible means known by the cutoff, so it counts only from its own known_at. A
        resolution must come from the review queue and name a reviewer.
        """
        wanted = {(rule.id, left.id, right.id)}
        if symmetric:
            wanted.add((rule.id, right.id, left.id))
        for fact in events(self.snapshot, FactKind.RESOLUTION, left.entity_key):
            if fact.source is not SourceProfile.REVIEW_QUEUE:
                continue
            payload = _typed(fact, ResolutionPayload)
            if not payload.reviewer.strip():
                continue
            if (payload.rule_id, payload.left_fact_id, payload.right_fact_id) in wanted:
                return fact
        return None

    def optional_ties(self) -> None:
        """A payload tie on a used entity that is not required, unless a rule already owns it."""
        for kind, key in sorted(self.optional_observations, key=lambda p: (p[0].value, p[1])):
            result = current(self.snapshot, kind, key)
            if result.status is CurrentStatus.TIE_CONFLICT and not (
                {f.id for f in result.facts} & self.rule_fact_ids
            ):
                self.tie(key, result.facts)


def evaluate_gate(
    snapshot: Snapshot,
    order_id: str,
    policy: PolicyDocument,
    coverage: Mapping[str, CoverageDecl] | None = None,
) -> GateResult:
    """The gate state and every finding for `order_id` at the snapshot's cutoff."""
    gate = _Gate(snapshot, policy, coverage or {})
    gate.run(order_id)
    findings = sorted(
        gate.findings,
        key=lambda f: (_STATE_ORDER[f.state], f.code, f.entity_key, f.rule_id or "", f.fact_ids),
    )
    used = None
    if gate.used is not None:
        artifact_id, decl = gate.used
        used = CoverageUsed(
            artifact_id=artifact_id, as_of=decl.as_of, qualities=tuple(sorted(decl.qualities))
        )
    return GateResult(
        state=combine_gate_states(f.state for f in findings),
        findings=tuple(findings),
        coverage_used=used,
    )
