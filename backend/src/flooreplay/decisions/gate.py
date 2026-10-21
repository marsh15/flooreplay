"""ContextGate: is the as-known evidence good enough to decide an order?

Pure: the only clock is `snapshot.cutoff`; there is no database, randomness or `now()`.
Ports the ideas of the archived gate (inclusive freshness, latest-wins, UNKNOWN is never
zero, findings that carry the facts they are about) to facts, policy-owned freshness and
declarative conflict rules.

Precedence is CONFLICTING > INCOMPLETE > STALE > READY and every finding is kept, so a
reviewer sees all the problems, not only the worst one. Findings in state READY (a conflict
that a resolution cleared) are kept as evidence and never raise the overall state.

Artifact coverage is passed explicitly: `coverage` maps an artifact id to the fabric
qualities that export declares it covers. The caller (the service layer) builds it from the
artifacts known at the cutoff; the gate only reads it. A quality with lots for a colour needs
no declaration. A quality with no lot for a colour is a known zero if some artifact in
`coverage` declares it, and INCOMPLETE otherwise. Fact payloads deliberately carry no
coverage, so facts stay pure observations.

Conflict rules join facts by entity_key and compare valid time as half-open intervals. An
observation kind with no `valid_to` ends when a newer observation of the same entity starts
(a later export replaces an earlier one); an event kind keeps its own interval.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection, Iterable, Mapping
from datetime import UTC, date, datetime, timedelta

from flooreplay.decisions.facts import (
    EVENT_KINDS,
    BomPayload,
    FabricInboundPayload,
    FabricLotPayload,
    OrderRequestPayload,
    ResolutionPayload,
    parse_payload,
)
from flooreplay.decisions.policy import ConflictRule, PolicyDocument, sewing_days
from flooreplay.decisions.snapshot import (
    COMPETING_REPLACEMENT,
    INVALID_PAYLOAD,
    CurrentStatus,
    Snapshot,
    current,
    events,
)
from flooreplay.decisions.types import (
    Fact,
    FactKind,
    FrozenModel,
    GateState,
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

_OPEN_END = datetime.max.replace(tzinfo=UTC)
_STATE_ORDER = {
    GateState.CONFLICTING: 0,
    GateState.INCOMPLETE: 1,
    GateState.STALE: 2,
    GateState.READY: 3,
}

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


def _typed[P](fact: Fact, model: type[P]) -> P:
    parsed = parse_payload(fact)
    if not isinstance(parsed, model):  # registry guarantees the model for the kind
        raise TypeError(f"{fact.kind.value} fact {fact.id} did not parse as {model.__name__}")
    return parsed


def _visible_of(snapshot: Snapshot, kind: FactKind) -> list[Fact]:
    return [f for f in snapshot.facts if f.kind == kind]


class _Gate:
    def __init__(
        self, snapshot: Snapshot, policy: PolicyDocument, coverage: Mapping[str, Collection[str]]
    ) -> None:
        self.snapshot = snapshot
        self.policy = policy
        self.covered_qualities = {q for qualities in coverage.values() for q in qualities}
        self.findings: list[GateFinding] = []
        self.relevant: set[str] = set()

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
        """STALE iff age = cutoff - valid_from > the source's limit (equal is fresh)."""
        if fact.source is SourceProfile.REVIEW_QUEUE:
            return  # reviewer decisions do not age
        limit_hours: int = getattr(self.policy.freshness_hours, fact.source.value)
        age = self.snapshot.cutoff - fact.valid_from
        if age > timedelta(hours=limit_hours):
            hours = age.total_seconds() / 3600
            self.add(
                STALE_EVIDENCE,
                GateState.STALE,
                fact.entity_key,
                (fact.id,),
                f"{fact.source.value} fact is {hours:.2f} h old at the cutoff; "
                f"the limit is {limit_hours} h",
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
        facts = tuple(tied)
        self.add(
            TIE_CONFLICT,
            GateState.CONFLICTING,
            entity_key,
            (f.id for f in facts),
            "facts with the same valid_from disagree on their content",
        )

    # -- the order -----------------------------------------------------------

    def run(self, order_id: str) -> None:
        order_fact = self.require(
            FactKind.ORDER_REQUEST, f"order:{order_id}", ORDER_REQUEST_MISSING, "order request"
        )
        if order_fact is not None:
            order = _typed(order_fact, OrderRequestPayload)
            bom_fact = self.require(
                FactKind.BOM, f"bom:{order.style_id}", BOM_MISSING, f"BOM for style {order.style_id}"
            )
            if bom_fact is not None:
                bom = _typed(bom_fact, BomPayload)
                colours = [c.colour for c in order.colours]
                self.fabric(bom, colours)
                for trim in bom.trims:
                    key = f"trim:{order.style_id}:{trim.trim_id}"
                    self.require(FactKind.TRIM_STATUS, key, TRIM_STATUS_MISSING, "trim status")
            self.capacity(order.ship_date)
        self.competing()
        self.invalid_payloads()
        self.rules()

    # -- fabric --------------------------------------------------------------

    def fabric(self, bom: BomPayload, colours: list[str]) -> None:
        quality = bom.fabric_quality
        wanted = set(colours)
        stocked: dict[str, list[Fact]] = defaultdict(list)

        by_key: dict[str, list[Fact]] = defaultdict(list)
        for fact in _visible_of(self.snapshot, FactKind.FABRIC_LOT):
            by_key[fact.entity_key].append(fact)
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
            self.fresh_check(result.fact)
            if lot.qty.unit != bom.consumption_per_pc.unit and (
                lot.gsm is None or lot.width_m is None
            ):
                self.add(
                    GSM_WIDTH_MISSING,
                    GateState.INCOMPLETE,
                    key,
                    (result.fact.id,),
                    f"lot is in {lot.qty.unit.value} but the BOM is in "
                    f"{bom.consumption_per_pc.unit.value}; gsm and width are both needed",
                )

        for colour in sorted(wanted):
            if not stocked[colour] and quality not in self.covered_qualities:
                self.add(
                    FABRIC_STOCK_UNCOVERED,
                    GateState.INCOMPLETE,
                    f"coverage:{quality}:{colour}",
                    (),
                    f"no lot of {quality} in {colour} and no stock export declares {quality} "
                    "covered; unknown is not zero",
                )

        # Entities that feed FABRIC/SAFETY besides the lots: inbound and allocations.
        for fact in _visible_of(self.snapshot, FactKind.FABRIC_INBOUND):
            inbound = _typed(fact, FabricInboundPayload)
            if inbound.fabric_quality == quality and inbound.colour in wanted:
                self.relevant.add(fact.entity_key)
        for fact in _visible_of(self.snapshot, FactKind.FABRIC_ALLOCATION):
            _, _, alloc_quality, alloc_colour = fact.entity_key.split(":", 3)
            if alloc_quality == quality and alloc_colour in wanted:
                self.relevant.add(fact.entity_key)

    # -- capacity ------------------------------------------------------------

    def capacity(self, ship_date: date) -> None:
        days = sewing_days(self.policy.capacity, ship_date)
        lines = self.policy.capacity.eligible_lines
        for line in lines:
            for day in days:
                key = f"line:{line}:{day.isoformat()}"
                self.require(FactKind.LINE_CAPACITY, key, LINE_CAPACITY_MISSING, "line capacity")
        day_texts = {d.isoformat() for d in days}
        for fact in _visible_of(self.snapshot, FactKind.LINE_COMMITMENT):
            _, _, line, day_text = fact.entity_key.split(":", 3)
            if line in lines and day_text in day_texts:
                self.relevant.add(fact.entity_key)

    # -- competing replacements ---------------------------------------------

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
        """A fact the snapshot excluded is missing evidence, not zero.

        An invalid lot cannot be matched to a quality or colour, so any invalid lot counts.
        """
        for item in self.snapshot.findings:
            if item.code != INVALID_PAYLOAD:
                continue
            if item.entity_key in self.relevant or item.kind is FactKind.FABRIC_LOT:
                self.add(
                    INVALID_PAYLOAD,
                    GateState.INCOMPLETE,
                    item.entity_key,
                    item.fact_ids,
                    f"fact {item.subject_id} was excluded from the snapshot: {item.detail}",
                )

    # -- declarative conflict rules -----------------------------------------

    def end_of(self, fact: Fact, starts: Mapping[tuple[FactKind, str], list[datetime]]) -> datetime:
        if fact.valid_to is not None:
            return fact.valid_to
        if fact.kind not in EVENT_KINDS:
            later = [s for s in starts[(fact.kind, fact.entity_key)] if s > fact.valid_from]
            if later:
                return min(later)
        return _OPEN_END

    def rules(self) -> None:
        starts: dict[tuple[FactKind, str], list[datetime]] = defaultdict(list)
        for fact in self.snapshot.facts:
            starts[(fact.kind, fact.entity_key)].append(fact.valid_from)
        for rule in self.policy.conflict_rules:
            self.apply_rule(rule, starts)

    def candidates(self, kind: FactKind) -> list[Fact]:
        """Visible, unsuperseded facts of `kind` on entities this order uses."""
        return [f for key in sorted(self.relevant) for f in events(self.snapshot, kind, key)]

    def apply_rule(
        self, rule: ConflictRule, starts: Mapping[tuple[FactKind, str], list[datetime]]
    ) -> None:
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
                    left.valid_from,
                    self.end_of(left, starts),
                    right.valid_from,
                    self.end_of(right, starts),
                ):
                    continue
                if not predicate(left, right):
                    continue
                resolution = self.resolution_for(rule, left, right, symmetric=same_kind)
                if resolution is None:
                    self.add(
                        CONFLICT_RULE,
                        GateState.CONFLICTING,
                        left.entity_key,
                        (left.id, right.id),
                        f"rule {rule.id}: {left.id} and {right.id} conflict and no "
                        "resolution is known at the cutoff",
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
        """A visible resolution (known by the cutoff) on the pair's entity naming this rule and pair."""
        wanted = {(rule.id, left.id, right.id)}
        if symmetric:
            wanted.add((rule.id, right.id, left.id))
        for fact in events(self.snapshot, FactKind.RESOLUTION, left.entity_key):
            if fact.known_at > self.snapshot.cutoff:
                continue
            payload = _typed(fact, ResolutionPayload)
            if (payload.rule_id, payload.left_fact_id, payload.right_fact_id) in wanted:
                return fact
        return None


def evaluate_gate(
    snapshot: Snapshot,
    order_id: str,
    policy: PolicyDocument,
    coverage: Mapping[str, Collection[str]] | None = None,
) -> GateResult:
    """The gate state and every finding for `order_id` at the snapshot's cutoff."""
    gate = _Gate(snapshot, policy, coverage or {})
    gate.run(order_id)
    findings = sorted(
        gate.findings,
        key=lambda f: (_STATE_ORDER[f.state], f.code, f.entity_key, f.rule_id or "", f.fact_ids),
    )
    return GateResult(
        state=combine_gate_states(f.state for f in findings), findings=tuple(findings)
    )
