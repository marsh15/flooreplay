"""Pure constraints: FABRIC, SAFETY, TRIMS, CAPACITY, OVERTIME and APPROVAL.

`evaluate_constraints(snapshot, order_id, policy, gate_result)` returns one `ConstraintResult`
per (constraint, subject) in a deterministic order (constraint enum order, then subject).
It reports PASS, FAIL or NOT_EVALUATED with the facts used and the arithmetic as ordered
`Step{label, expression, value}`; it never decides the recommendation (that is T9).

Rules that hold throughout:

* Unknown is never zero. An input that is missing, conflicting or in a unit that cannot be
  converted makes the constraint NOT_EVALUATED. The one exception is a fabric colour with no lot
  of a quality that the stock export the gate used (`gate_result.coverage_used`) declares
  covered: that is a known zero.
* Required amounts round up (CEILING) and available amounts round down (FLOOR) at 0.001, so
  more supply never flips PASS to FAIL and more quantity never flips FAIL to PASS. A
  converted deduction (QC claim, other order's allocation) is a requirement-like amount and
  rounds up; converted supply (lot, inbound, resolution usable_qty) rounds down.
* kg and m convert only through GSM and width of a current lot of the same quality and colour
  (the lot's own, if it has both). Without them the constraint is NOT_EVALUATED.
* Observations come from `snapshot.current()`; a missing, tied or competing observation that
  the constraint needs is NOT_EVALUATED. QC claims are events and are all read.

FABRIC usable stock. Per lot, `lot.qty - sum(QC qty)` over claims in `checks_passed` or
`confirmed`. A `needs_review` claim cannot be trusted: it is not subtracted, and its fact id is
reported in `pending_review_fact_ids` (T9 forces NEEDS_REVIEW), unless a resolution names it.
`corrected` and `rejected` claims are neither subtracted nor pending. A visible `review_queue`
resolution with a reviewer and a readable `resolved_payload.usable_qty` replaces the lot's
usable amount (the newest by known_at, then id); QC claims on that lot are then not subtracted.
Per-lot usable stock is not floored at zero, so an over-claim stays visible; the SAFETY base
is floored at zero.

CAPACITY efficiency (documented rule, logged in docs/v2/changelog.md). Per line-day the free
minutes are `max(0, available_minutes - committed_minutes of other orders)`. If EVERY eligible
line-day fact in the sewing window gives `efficiency_pct`, efficiency is the free-minute
weighted average `sum(free x eff) / sum(free)` and `required = total_sam x sum(free) /
sum(free x eff)`; otherwise it is `policy.capacity.default_efficiency_pct`. Weighting by free
minutes (not raw available minutes) makes PASS iff `sum(free x eff) >= total_sam`, which is
monotone in every line's minutes. A fact efficiency outside (0, 1] is NOT_EVALUATED.

No database, clock or randomness is used here.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import (
    ROUND_CEILING,
    ROUND_HALF_EVEN,
    Context,
    Decimal,
    DivisionByZero,
    InvalidOperation,
    Overflow,
    localcontext,
)

from flooreplay.decisions.facts import (
    BomPayload,
    FabricAllocationPayload,
    FabricInboundPayload,
    FabricLotPayload,
    FabricQcPayload,
    LineCapacityPayload,
    LineCommitmentPayload,
    OrderColour,
    OrderRequestPayload,
    ResolutionPayload,
    TrimStatusPayload,
    parse_payload,
)
from flooreplay.decisions.gate import GateResult
from flooreplay.decisions.policy import PolicyDocument, cut_date, sewing_days
from flooreplay.decisions.snapshot import CurrentStatus, Snapshot, current, events
from flooreplay.decisions.types import (
    ConstraintId,
    ConstraintStatus,
    Fact,
    FactKind,
    FrozenModel,
    Quantity,
    ReviewState,
    SourceProfile,
    Unit,
    canonical,
    quantize_available,
    quantize_required,
)
from flooreplay.decisions.types import kg_to_m as _kg_to_m

_CTX = Context(
    prec=60,
    rounding=ROUND_HALF_EVEN,
    Emin=-999_999,
    Emax=999_999,
    traps=[InvalidOperation, DivisionByZero, Overflow],
)
_ZERO = Decimal(0)
_EFFICIENCY_DISPLAY = Decimal("0.000001")
_CONSTRAINT_ORDER = {c: i for i, c in enumerate(ConstraintId)}


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


class Step(FrozenModel):
    """One line of arithmetic: the formula with the numbers substituted, and its value."""

    label: str
    expression: str
    value: str  # canonical Decimal text followed by the unit, e.g. "220.5 kg"


class OvertimeNeed(FrozenModel):
    """What overtime would have to be, for T9's `overtime` condition."""

    lines: int
    days: int
    cap_hours_per_line_day: int
    hours_per_line_per_day: int | None  # None when there is no line-day to carry overtime


class ConstraintResult(FrozenModel):
    constraint: ConstraintId
    subject: str  # colour, trim_id, or "order"
    status: ConstraintStatus
    fact_ids: tuple[str, ...]  # sorted
    steps: tuple[Step, ...]
    detail: str
    consumed_by: tuple[str, ...] = ()  # SAFETY FAIL: allocation facts that took the stock
    pending_review_fact_ids: tuple[str, ...] = ()  # FABRIC/SAFETY: needs_review QC not trusted
    required: Quantity | None = None  # FABRIC req, SAFETY floor, TRIMS need, CAPACITY required
    available: Quantity | None = None  # FABRIC free, SAFETY margin, TRIMS/CAPACITY available
    overtime: OvertimeNeed | None = None


# ---------------------------------------------------------------------------
# Formatting and arithmetic helpers
# ---------------------------------------------------------------------------


def _t(value: Decimal | int) -> str:
    """Canonical plain decimal text."""
    return str(canonical(Decimal(value)))


def _amt(value: Decimal | int, unit: str) -> str:
    return f"{_t(value)} {unit}"


def _sum_text(terms: Iterable[str]) -> str:
    items = list(terms)
    return " + ".join(items) if items else "0"


def _typed[P](fact: Fact, model: type[P]) -> P:
    parsed = parse_payload(fact)
    if not isinstance(parsed, model):  # the registry guarantees the model for the kind
        raise TypeError(f"{fact.kind.value} fact {fact.id} did not parse as {model.__name__}")
    return parsed


class _Unevaluable(Exception):
    """An input is missing, conflicting or unconvertible; carries the facts involved."""

    def __init__(self, reason: str, fact_ids: Iterable[str] = ()) -> None:
        super().__init__(reason)
        self.reason = reason
        self.fact_ids = tuple(sorted(set(fact_ids)))


@dataclass(frozen=True)
class _Factors:
    gsm: Decimal
    width_m: Decimal
    fact_id: str

    def note(self) -> str:
        return f"gsm {_t(self.gsm)} × width {_t(self.width_m)} m"


def _factors_of(fact: Fact, lot: FabricLotPayload) -> _Factors | None:
    if lot.gsm is None or lot.width_m is None:
        return None
    return _Factors(lot.gsm, lot.width_m, fact.id)


def _convert(
    qty: Quantity,
    unit: Unit,
    factors: _Factors | None,
    *,
    round_up: bool,
    fact: Fact,
    ids: set[str],
) -> tuple[Decimal, str | None]:
    """`qty` in `unit`: (value, note). Rounds up for requirements, down for supply."""
    if qty.unit == unit:
        return qty.value, None
    if factors is None:
        raise _Unevaluable(
            f"fact {fact.id} is in {qty.unit.value} but the BOM is in {unit.value}; "
            "a current lot of the same quality and colour needs both gsm and width",
            (fact.id,),
        )
    ids.add(factors.fact_id)
    if qty.unit is Unit.KG:
        raw = _kg_to_m(qty.value, factors.gsm, factors.width_m)
    else:
        raw = qty.value * factors.gsm * factors.width_m / 1000
    value = quantize_required(raw) if round_up else quantize_available(raw)
    return value, f"{_t(qty.value)} {qty.unit.value} at {factors.note()}"


def _term(value: Decimal, note: str | None) -> str:
    return _t(value) if note is None else f"{_t(value)} [{note}]"


@dataclass
class _FabricCalc:
    colour: str
    error: _Unevaluable | None = None
    unit: str = ""
    req: Decimal = _ZERO
    usable: Decimal = _ZERO
    inbound: Decimal = _ZERO
    committed: Decimal = _ZERO
    free: Decimal = _ZERO
    steps: list[Step] = field(default_factory=list)
    fact_ids: set[str] = field(default_factory=set)
    consumed_by: list[str] = field(default_factory=list)
    pending: set[str] = field(default_factory=set)
    notes: list[str] = field(default_factory=list)
    safety_floor_pct: Decimal = _ZERO


@dataclass
class _CapacityCalc:
    result: ConstraintResult
    required: Decimal = _ZERO
    available: Decimal = _ZERO
    lines: int = 0
    days: int = 0
    fact_ids: tuple[str, ...] = ()
    evaluated: bool = False


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


class _Evaluator:
    def __init__(
        self, snapshot: Snapshot, order_id: str, policy: PolicyDocument, gate_result: GateResult
    ) -> None:
        self.snapshot = snapshot
        self.order_id = order_id
        self.policy = policy
        self.gate_result = gate_result
        self.order_fact: Fact | None = None
        self.order: OrderRequestPayload | None = None
        self.order_error: _Unevaluable | None = None
        self.bom_fact: Fact | None = None
        self.bom: BomPayload | None = None
        self.bom_error: _Unevaluable | None = None
        self._load_order_and_bom()

    # -- loading ---------------------------------------------------------------

    def _current(self, kind: FactKind, key: str, what: str) -> Fact:
        result = current(self.snapshot, kind, key)
        if result.status is CurrentStatus.UNKNOWN:
            raise _Unevaluable(f"no {what} is known at the cutoff; unknown is not zero")
        if result.status is CurrentStatus.COMPETING:
            raise _Unevaluable(
                f"{what} has competing replacements", (f.id for f in result.facts)
            )
        if result.fact is None:
            raise _Unevaluable(
                f"{what}: facts with the same valid_from disagree", (f.id for f in result.facts)
            )
        return result.fact

    def _load_order_and_bom(self) -> None:
        try:
            self.order_fact = self._current(
                FactKind.ORDER_REQUEST, f"order:{self.order_id}", "order request"
            )
            self.order = _typed(self.order_fact, OrderRequestPayload)
        except _Unevaluable as exc:
            self.order_error = exc
            return
        try:
            self.bom_fact = self._current(
                FactKind.BOM, f"bom:{self.order.style_id}", f"BOM for style {self.order.style_id}"
            )
            self.bom = _typed(self.bom_fact, BomPayload)
        except _Unevaluable as exc:
            self.bom_error = exc

    def _order_bom(self) -> tuple[Fact, OrderRequestPayload, Fact, BomPayload]:
        if self.order_error is not None:
            raise self.order_error
        if self.bom_error is not None:
            raise self.bom_error
        assert self.order_fact and self.order and self.bom_fact and self.bom
        return self.order_fact, self.order, self.bom_fact, self.bom

    def _cut_date(self, order: OrderRequestPayload) -> date:
        try:
            return cut_date(self.policy.capacity, order.ship_date)
        except OverflowError as exc:
            raise _Unevaluable(
                f"the cut date for ship date {order.ship_date} is outside the calendar"
            ) from exc

    def _before_cut(self, order: OrderRequestPayload, days: int) -> date:
        try:
            return self._cut_date(order) - timedelta(days=days)
        except OverflowError as exc:
            raise _Unevaluable("the arrival cut-off is outside the calendar") from exc

    # -- entry -------------------------------------------------------------------

    def run(self) -> list[ConstraintResult]:
        enabled = set(self.policy.enabled_constraints)
        out: list[ConstraintResult] = []
        if self.order_error is not None:
            for constraint in (
                ConstraintId.FABRIC,
                ConstraintId.SAFETY,
                ConstraintId.TRIMS,
                ConstraintId.CAPACITY,
                ConstraintId.APPROVAL,
            ):
                if constraint in enabled:
                    out.append(self._not_evaluated(constraint, "order", self.order_error))
            return self._sorted(out)
        assert self.order is not None
        if enabled & {ConstraintId.FABRIC, ConstraintId.SAFETY}:
            for entry in self.order.colours:
                calc = self._fabric(entry)
                if ConstraintId.FABRIC in enabled:
                    out.append(self._fabric_result(calc))
                if ConstraintId.SAFETY in enabled:
                    out.append(self._safety_result(calc))
        if ConstraintId.TRIMS in enabled:
            out.extend(self._trims())
        if enabled & {ConstraintId.CAPACITY, ConstraintId.OVERTIME}:
            capacity = self._capacity()
            if ConstraintId.CAPACITY in enabled:
                out.append(capacity.result)
            if (
                ConstraintId.OVERTIME in enabled
                and capacity.evaluated
                and capacity.result.status is ConstraintStatus.FAIL
            ):
                out.append(self._overtime(capacity))
        if ConstraintId.APPROVAL in enabled:
            out.append(self._approval())
        return self._sorted(out)

    @staticmethod
    def _sorted(results: list[ConstraintResult]) -> list[ConstraintResult]:
        return sorted(results, key=lambda r: (_CONSTRAINT_ORDER[r.constraint], r.subject))

    @staticmethod
    def _not_evaluated(
        constraint: ConstraintId, subject: str, exc: _Unevaluable, prefix: str = ""
    ) -> ConstraintResult:
        return ConstraintResult(
            constraint=constraint,
            subject=subject,
            status=ConstraintStatus.NOT_EVALUATED,
            fact_ids=exc.fact_ids,
            steps=(),
            detail=f"{prefix}{exc.reason}",
        )

    # -- FABRIC ------------------------------------------------------------------

    def _fabric(self, entry: OrderColour) -> _FabricCalc:
        calc = _FabricCalc(colour=entry.colour)
        try:
            self._fabric_into(calc, entry)
        except _Unevaluable as exc:
            calc.error = exc
            calc.fact_ids.update(exc.fact_ids)
        return calc

    def _lots(self, quality: str, colour: str) -> list[tuple[Fact, FabricLotPayload]]:
        """The current lot of every entity that is, or was last seen as, this quality and colour."""
        by_key: dict[str, list[Fact]] = defaultdict(list)
        for fact in self.snapshot.facts:
            if fact.kind is FactKind.FABRIC_LOT:
                by_key[fact.entity_key].append(fact)

        def matches(lot: FabricLotPayload) -> bool:
            return lot.fabric_quality == quality and lot.colour == colour

        out: list[tuple[Fact, FabricLotPayload]] = []
        for key in sorted(by_key):
            if not any(matches(_typed(f, FabricLotPayload)) for f in by_key[key]):
                continue
            result = current(self.snapshot, FactKind.FABRIC_LOT, key)
            if result.status is not CurrentStatus.FOUND or result.fact is None:
                raise _Unevaluable(
                    f"lot {key} is conflicting at the cutoff", (f.id for f in by_key[key])
                )
            lot = _typed(result.fact, FabricLotPayload)
            if matches(lot):
                out.append((result.fact, lot))
        return out

    @staticmethod
    def _colour_factors(lots: list[tuple[Fact, FabricLotPayload]]) -> _Factors | None:
        """GSM and width of the colour: the newest lot that has both (ties by entity_key)."""
        candidates = sorted(
            (c for c in lots if c[1].gsm is not None and c[1].width_m is not None),
            key=lambda c: (c[0].entity_key, c[0].id),
        )
        if not candidates:
            return None
        fact, lot = max(candidates, key=lambda c: c[0].valid_from)
        return _factors_of(fact, lot)

    def _resolution(self, key: str) -> tuple[Fact, ResolutionPayload] | None:
        found: list[tuple[Fact, ResolutionPayload]] = []
        for fact in events(self.snapshot, FactKind.RESOLUTION, key):
            if fact.source is not SourceProfile.REVIEW_QUEUE:
                continue
            payload = _typed(fact, ResolutionPayload)
            if payload.reviewer.strip() and "usable_qty" in payload.resolved_payload:
                found.append((fact, payload))
        if not found:
            return None
        return max(found, key=lambda p: (p[0].known_at, p[0].id))

    @staticmethod
    def _usable_qty(fact: Fact, payload: ResolutionPayload) -> Quantity:
        raw = payload.resolved_payload["usable_qty"]
        try:
            qty = Quantity.model_validate(dict(raw))
        except (ValueError, TypeError) as exc:
            raise _Unevaluable(
                f"resolution {fact.id} has an unreadable usable_qty", (fact.id,)
            ) from exc
        if qty.unit not in (Unit.KG, Unit.M) or qty.value < 0:
            raise _Unevaluable(f"resolution {fact.id} has an invalid usable_qty", (fact.id,))
        return qty

    def _fabric_into(self, calc: _FabricCalc, entry: OrderColour) -> None:
        order_fact, order, bom_fact, bom = self._order_bom()
        colour, quality = entry.colour, bom.fabric_quality
        unit = bom.consumption_per_pc.unit
        consumption = bom.consumption_per_pc.value
        wastage = self.policy.fabric.wastage_pct
        ids = calc.fact_ids
        ids.update((order_fact.id, bom_fact.id))
        calc.unit = unit.value
        calc.safety_floor_pct = self.policy.fabric.safety_floor_pct
        steps = calc.steps

        calc.req = quantize_required(Decimal(entry.qty_pcs) * consumption * (1 + wastage))
        steps.append(
            Step(
                label="required",
                expression=(
                    f"{entry.qty_pcs} pcs × {_t(consumption)} {unit.value}/pc × (1 + {_t(wastage)})"
                ),
                value=_amt(calc.req, unit.value),
            )
        )

        lots = self._lots(quality, colour)
        factors = self._colour_factors(lots)
        usable_values: list[Decimal] = []
        if not lots:
            used = self.gate_result.coverage_used
            if used is None or quality not in used.qualities:
                raise _Unevaluable(
                    f"no lot of {quality} in {colour} and no stock export the gate used declares "
                    f"{quality} covered; unknown is not zero"
                )
            calc.notes.append(
                f"no lot of {quality} in {colour}: known zero from stock export {used.artifact_id}"
            )
        for fact, lot in lots:
            usable_values.append(self._lot_usable(calc, fact, lot, unit, factors))
        calc.usable = sum(usable_values, _ZERO)
        steps.append(
            Step(
                label="usable_onhand",
                expression=(
                    _sum_text(_t(v) for v in usable_values)
                    if usable_values
                    else "0 (known zero from the stock export's coverage)"
                ),
                value=_amt(calc.usable, unit.value),
            )
        )

        # Inbound: only what lands by cut_date - inbound_buffer_days.
        limit = self._before_cut(order, self.policy.fabric.inbound_buffer_days)
        counted: list[str] = []
        late: list[str] = []
        inbound_by_key: dict[str, list[Fact]] = defaultdict(list)
        for fact in self.snapshot.facts:
            if fact.kind is FactKind.FABRIC_INBOUND:
                inbound_by_key[fact.entity_key].append(fact)

        def inbound_matches(item: FabricInboundPayload) -> bool:
            return item.fabric_quality == quality and item.colour == colour

        for key in sorted(inbound_by_key):
            if not any(inbound_matches(_typed(f, FabricInboundPayload)) for f in inbound_by_key[key]):
                continue
            fact = self._current(FactKind.FABRIC_INBOUND, key, f"inbound {key}")
            item = _typed(fact, FabricInboundPayload)
            if not inbound_matches(item):
                continue
            value, note = _convert(item.qty, unit, factors, round_up=False, fact=fact, ids=ids)
            ids.add(fact.id)
            if item.eta <= limit:
                calc.inbound += value
                counted.append(_term(value, note))
            else:
                late.append(f"{_term(value, note)} [{key} eta {item.eta} after {limit}]")
        expression = _sum_text(counted)
        if late:
            expression += f" (not counted: {', '.join(late)})"
        steps.append(
            Step(label="inbound", expression=expression, value=_amt(calc.inbound, unit.value))
        )

        # Committed to other orders; this order's own allocations are not a claim on its stock.
        committed: list[str] = []
        for key in sorted({f.entity_key for f in self.snapshot.facts
                           if f.kind is FactKind.FABRIC_ALLOCATION}):
            parts = key.split(":")
            if len(parts) != 4 or parts[2] != quality or parts[3] != colour:
                continue
            if parts[1] == self.order_id:
                continue
            fact = self._current(FactKind.FABRIC_ALLOCATION, key, f"allocation {key}")
            alloc = _typed(fact, FabricAllocationPayload)
            value, note = _convert(alloc.qty, unit, factors, round_up=True, fact=fact, ids=ids)
            ids.add(fact.id)
            calc.committed += value
            committed.append(_term(value, note))
            if value > 0:
                calc.consumed_by.append(fact.id)
        steps.append(
            Step(
                label="committed",
                expression=_sum_text(committed),
                value=_amt(calc.committed, unit.value),
            )
        )

        calc.free = calc.usable + calc.inbound - calc.committed
        steps.append(
            Step(
                label="free",
                expression=f"{_t(calc.usable)} + {_t(calc.inbound)} − {_t(calc.committed)}",
                value=_amt(calc.free, unit.value),
            )
        )
        steps.append(
            Step(
                label="margin",
                expression=f"{_t(calc.free)} − {_t(calc.req)}",
                value=_amt(calc.free - calc.req, unit.value),
            )
        )

    def _lot_usable(
        self,
        calc: _FabricCalc,
        fact: Fact,
        lot: FabricLotPayload,
        unit: Unit,
        colour_factors: _Factors | None,
    ) -> Decimal:
        key = fact.entity_key
        ids = calc.fact_ids
        ids.add(fact.id)
        factors = _factors_of(fact, lot) or colour_factors
        supply, note = _convert(lot.qty, unit, factors, round_up=False, fact=fact, ids=ids)
        resolution = self._resolution(key)
        cleared: set[str] = set()
        if resolution is not None:
            res_fact, res_payload = resolution
            ids.add(res_fact.id)
            cleared = {res_payload.left_fact_id, res_payload.right_fact_id}
            usable_qty = self._usable_qty(res_fact, res_payload)
            usable, usable_note = _convert(
                usable_qty, unit, factors, round_up=False, fact=res_fact, ids=ids
            )
            expression = f"resolution {res_fact.id} usable_qty {_term(usable, usable_note)}"
        else:
            terms = [_term(supply, note)]
            usable = supply
        for qc in events(self.snapshot, FactKind.FABRIC_QC, key):
            claim = _typed(qc, FabricQcPayload)
            if claim.review_state is ReviewState.NEEDS_REVIEW:
                if qc.id not in cleared:
                    calc.pending.add(qc.id)
                    ids.add(qc.id)
                continue
            if resolution is not None:
                continue
            if claim.review_state in (ReviewState.CHECKS_PASSED, ReviewState.CONFIRMED):
                deduction, deduction_note = _convert(
                    claim.qty, unit, factors, round_up=True, fact=qc, ids=ids
                )
                ids.add(qc.id)
                usable -= deduction
                terms.append(_term(deduction, deduction_note))
        if resolution is None:
            expression = " − ".join(terms)
        calc.steps.append(
            Step(label=f"usable:{key}", expression=expression, value=_amt(usable, unit.value))
        )
        return usable

    def _fabric_result(self, calc: _FabricCalc) -> ConstraintResult:
        if calc.error is not None:
            return self._not_evaluated(ConstraintId.FABRIC, calc.colour, calc.error)
        unit = Unit(calc.unit)
        passed = calc.free >= calc.req
        relation = ">=" if passed else "<"
        detail = "; ".join(
            [f"free {_amt(calc.free, calc.unit)} {relation} required {_amt(calc.req, calc.unit)}"]
            + calc.notes
        )
        return ConstraintResult(
            constraint=ConstraintId.FABRIC,
            subject=calc.colour,
            status=ConstraintStatus.PASS if passed else ConstraintStatus.FAIL,
            fact_ids=tuple(sorted(calc.fact_ids)),
            steps=tuple(calc.steps),
            detail=detail,
            pending_review_fact_ids=tuple(sorted(calc.pending)),
            required=Quantity(value=calc.req, unit=unit),
            available=Quantity(value=calc.free, unit=unit),
        )

    # -- SAFETY ------------------------------------------------------------------

    def _safety_result(self, calc: _FabricCalc) -> ConstraintResult:
        if calc.error is not None:
            return self._not_evaluated(
                ConstraintId.SAFETY, calc.colour, calc.error, "FABRIC inputs unavailable: "
            )
        unit = Unit(calc.unit)
        margin = calc.free - calc.req
        raw_base = calc.usable + calc.inbound
        base = max(_ZERO, raw_base)
        floor = quantize_required(calc.safety_floor_pct * base)
        headroom = margin - floor
        passed = headroom >= 0
        steps = [
            Step(
                label="free",
                expression=f"{_t(calc.usable)} + {_t(calc.inbound)} − {_t(calc.committed)}",
                value=_amt(calc.free, calc.unit),
            ),
            Step(
                label="margin",
                expression=f"{_t(calc.free)} − {_t(calc.req)}",
                value=_amt(margin, calc.unit),
            ),
            Step(
                label="base",
                expression=f"{_t(calc.usable)} + {_t(calc.inbound)}"
                + (" (floored at 0)" if raw_base < 0 else ""),
                value=_amt(base, calc.unit),
            ),
            Step(
                label="floor",
                expression=f"{_t(calc.safety_floor_pct)} × {_t(base)}",
                value=_amt(floor, calc.unit),
            ),
            Step(
                label="headroom",
                expression=f"{_t(margin)} − {_t(floor)}",
                value=_amt(headroom, calc.unit),
            ),
        ]
        detail = f"headroom {_amt(headroom, calc.unit)} {'>=' if passed else '<'} 0 after the safety floor"
        return ConstraintResult(
            constraint=ConstraintId.SAFETY,
            subject=calc.colour,
            status=ConstraintStatus.PASS if passed else ConstraintStatus.FAIL,
            fact_ids=tuple(sorted(calc.fact_ids)),
            steps=tuple(steps),
            detail=detail,
            consumed_by=() if passed else tuple(sorted(calc.consumed_by)),
            pending_review_fact_ids=tuple(sorted(calc.pending)),
            required=Quantity(value=floor, unit=unit),
            available=Quantity(value=margin, unit=unit),
        )

    # -- TRIMS -------------------------------------------------------------------

    def _trims(self) -> list[ConstraintResult]:
        try:
            order_fact, order, bom_fact, bom = self._order_bom()
        except _Unevaluable as exc:
            return [self._not_evaluated(ConstraintId.TRIMS, "order", exc)]
        results: list[ConstraintResult] = []
        for trim in bom.trims:
            try:
                results.append(self._trim(order_fact, order, bom_fact, bom, trim.trim_id, trim.qty_per_pc))
            except _Unevaluable as exc:
                results.append(self._not_evaluated(ConstraintId.TRIMS, trim.trim_id, exc))
        return results

    def _trim(
        self,
        order_fact: Fact,
        order: OrderRequestPayload,
        bom_fact: Fact,
        bom: BomPayload,
        trim_id: str,
        qty_per_pc: Decimal,
    ) -> ConstraintResult:
        total = sum(c.qty_pcs for c in order.colours)
        wastage = self.policy.trims.wastage_pct
        need = quantize_required(Decimal(total) * qty_per_pc * (1 + wastage))
        fact = self._current(
            FactKind.TRIM_STATUS, f"trim:{order.style_id}:{trim_id}", f"trim status for {trim_id}"
        )
        status = _typed(fact, TrimStatusPayload)
        limit = self._before_cut(order, self.policy.trims.buffer_days)
        on_hand = quantize_available(status.on_hand.value)
        counted = _ZERO
        if status.inbound_qty is None:
            inbound_text = "0 (no inbound)"
        else:
            inbound = quantize_available(status.inbound_qty.value)
            if status.eta is None:
                inbound_text = f"0 ({_t(inbound)} inbound has no eta)"
            elif status.eta <= limit:
                counted = inbound
                inbound_text = f"{_t(inbound)} (eta {status.eta} <= {limit})"
            else:
                inbound_text = f"0 ({_t(inbound)} arrives {status.eta}, after {limit})"
        available = on_hand + counted
        margin = available - need
        passed = available >= need
        steps = (
            Step(
                label="need",
                expression=(
                    f"{total} pcs × {_t(qty_per_pc)} pcs/pc × (1 + {_t(wastage)})"
                ),
                value=_amt(need, "pcs"),
            ),
            Step(label="on_hand", expression=_t(on_hand), value=_amt(on_hand, "pcs")),
            Step(label="inbound", expression=inbound_text, value=_amt(counted, "pcs")),
            Step(
                label="available",
                expression=f"{_t(on_hand)} + {_t(counted)}",
                value=_amt(available, "pcs"),
            ),
            Step(
                label="margin",
                expression=f"{_t(available)} − {_t(need)}",
                value=_amt(margin, "pcs"),
            ),
        )
        return ConstraintResult(
            constraint=ConstraintId.TRIMS,
            subject=trim_id,
            status=ConstraintStatus.PASS if passed else ConstraintStatus.FAIL,
            fact_ids=tuple(sorted({order_fact.id, bom_fact.id, fact.id})),
            steps=steps,
            detail=f"available {_amt(available, 'pcs')} {'>=' if passed else '<'} need {_amt(need, 'pcs')}",
            required=Quantity(value=need, unit=Unit.PCS),
            available=Quantity(value=available, unit=Unit.PCS),
        )

    # -- CAPACITY and OVERTIME -----------------------------------------------------

    def _capacity(self) -> _CapacityCalc:
        try:
            return self._capacity_into()
        except _Unevaluable as exc:
            return _CapacityCalc(
                result=self._not_evaluated(ConstraintId.CAPACITY, "order", exc),
            )

    def _capacity_into(self) -> _CapacityCalc:
        order_fact, order, bom_fact, bom = self._order_bom()
        params = self.policy.capacity
        try:
            days = sewing_days(params, order.ship_date)
            cut = cut_date(params, order.ship_date)
            first = cut + timedelta(days=1)
            last = order.ship_date - timedelta(days=params.finishing_days)
        except OverflowError as exc:
            raise _Unevaluable(
                f"the sewing window for ship date {order.ship_date} is outside the calendar"
            ) from exc
        lines = params.eligible_lines
        day_texts = {d.isoformat() for d in days}
        ids = {order_fact.id, bom_fact.id}

        # Commitments of OTHER orders, per (line, day).
        committed: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
        for key in sorted({f.entity_key for f in self.snapshot.facts
                           if f.kind is FactKind.LINE_COMMITMENT}):
            parts = key.split(":")
            if len(parts) != 4 or parts[1] == self.order_id:
                continue
            commit_line, commit_day = parts[2], parts[3]
            if commit_line not in lines or commit_day not in day_texts:
                continue
            fact = self._current(FactKind.LINE_COMMITMENT, key, f"commitment {key}")
            committed[(commit_line, commit_day)] += _typed(fact, LineCommitmentPayload).committed_minutes.value
            ids.add(fact.id)

        total_qty = sum(c.qty_pcs for c in order.colours)
        sam_total = Decimal(total_qty) * bom.sam_minutes
        line_steps: list[Step] = []
        line_totals: list[Decimal] = []
        free_total = _ZERO
        weighted_total = _ZERO
        efficiencies: list[Decimal | None] = []
        for line in lines:
            raw_available = _ZERO
            raw_committed = _ZERO
            line_free = _ZERO
            for day in days:
                iso = day.isoformat()
                fact = self._current(
                    FactKind.LINE_CAPACITY, f"line:{line}:{iso}", f"line capacity for {line} on {iso}"
                )
                payload = _typed(fact, LineCapacityPayload)
                ids.add(fact.id)
                minutes = payload.available_minutes.value
                taken = committed.get((line, iso), _ZERO)
                free = max(_ZERO, minutes - taken)
                raw_available += minutes
                raw_committed += taken
                line_free += free
                efficiencies.append(payload.efficiency_pct)
                if payload.efficiency_pct is not None:
                    weighted_total += free * payload.efficiency_pct
            free_total += line_free
            line_totals.append(line_free)
            line_steps.append(
                Step(
                    label=f"available:{line}",
                    expression=(
                        f"Σ over {len(days)} days of max(0, available − committed): "
                        f"{_t(raw_available)} − {_t(raw_committed)}"
                    ),
                    value=_amt(line_free, "minutes"),
                )
            )

        all_given = bool(efficiencies) and all(e is not None for e in efficiencies)
        if all_given and any(not (0 < e <= 1) for e in efficiencies if e is not None):
            raise _Unevaluable(
                "a line-day efficiency_pct is outside (0, 1]; it must be a fraction", ids
            )
        steps: list[Step] = [
            Step(
                label="sam_total",
                expression=f"{total_qty} pcs × {_t(bom.sam_minutes)} min",
                value=_amt(sam_total, "minutes"),
            )
        ]
        if all_given and free_total > 0 and weighted_total > 0:
            efficiency = (weighted_total / free_total).quantize(_EFFICIENCY_DISPLAY)
            required = quantize_required(sam_total * free_total / weighted_total)
            steps.append(
                Step(
                    label="efficiency",
                    expression=f"{_t(weighted_total)} / {_t(free_total)}",
                    value=_t(efficiency),
                )
            )
            required_expression = f"{_t(sam_total)} / ({_t(weighted_total)} / {_t(free_total)})"
        else:
            default = params.default_efficiency_pct
            required = quantize_required(sam_total / default)
            steps.append(
                Step(
                    label="efficiency",
                    expression=f"default_efficiency_pct {_t(default)}",
                    value=_t(default),
                )
            )
            required_expression = f"{_t(sam_total)} / {_t(default)}"
        steps.append(
            Step(label="required", expression=required_expression, value=_amt(required, "minutes"))
        )
        off = ", ".join(d.value for d in params.non_working_weekdays) or "none"
        steps.append(
            Step(
                label="window",
                expression=(
                    f"cut_date {cut} = ship {order.ship_date} − {params.cut_to_ship_days} d; "
                    f"{first}..{last}, excluding {off} and {len(params.holidays)} holidays"
                ),
                value=f"{len(days)} days",
            )
        )
        steps.extend(line_steps)
        available = free_total
        steps.append(
            Step(
                label="available",
                expression=_sum_text(_t(v) for v in line_totals),
                value=_amt(available, "minutes"),
            )
        )
        steps.append(
            Step(
                label="margin",
                expression=f"{_t(available)} − {_t(required)}",
                value=_amt(available - required, "minutes"),
            )
        )
        passed = available >= required
        fact_ids = tuple(sorted(ids))
        result = ConstraintResult(
            constraint=ConstraintId.CAPACITY,
            subject="order",
            status=ConstraintStatus.PASS if passed else ConstraintStatus.FAIL,
            fact_ids=fact_ids,
            steps=tuple(steps),
            detail=(
                f"available {_amt(available, 'minutes')} {'>=' if passed else '<'} "
                f"required {_amt(required, 'minutes')}"
            ),
            required=Quantity(value=required, unit=Unit.MINUTES),
            available=Quantity(value=available, unit=Unit.MINUTES),
        )
        return _CapacityCalc(
            result=result,
            required=required,
            available=available,
            lines=len(lines),
            days=len(days),
            fact_ids=fact_ids,
            evaluated=True,
        )

    def _overtime(self, capacity: _CapacityCalc) -> ConstraintResult:
        cap_hours = self.policy.capacity.ot_cap_hours_per_line_day
        shortfall = capacity.required - capacity.available
        line_days = capacity.lines * capacity.days
        ot_available = Decimal(line_days * cap_hours * 60)
        steps = [
            Step(
                label="shortfall",
                expression=f"{_t(capacity.required)} − {_t(capacity.available)}",
                value=_amt(shortfall, "minutes"),
            ),
            Step(
                label="ot_available",
                expression=f"{capacity.lines} lines × {capacity.days} days × {cap_hours} h × 60",
                value=_amt(ot_available, "minutes"),
            ),
        ]
        hours: int | None = None
        if line_days > 0:
            hours = int((shortfall / Decimal(line_days * 60)).to_integral_value(ROUND_CEILING))
            steps.append(
                Step(
                    label="hours_per_line_per_day",
                    expression=(
                        f"ceil({_t(shortfall)} / ({capacity.lines} × {capacity.days} × 60))"
                    ),
                    value=f"{hours} hours",
                )
            )
        passed = shortfall <= ot_available
        return ConstraintResult(
            constraint=ConstraintId.OVERTIME,
            subject="order",
            status=ConstraintStatus.PASS if passed else ConstraintStatus.FAIL,
            fact_ids=capacity.fact_ids,
            steps=tuple(steps),
            detail=(
                f"shortfall {_amt(shortfall, 'minutes')} "
                f"{'<=' if passed else '>'} overtime available {_amt(ot_available, 'minutes')}"
            ),
            overtime=OvertimeNeed(
                lines=capacity.lines,
                days=capacity.days,
                cap_hours_per_line_day=cap_hours,
                hours_per_line_per_day=hours,
            ),
        )

    # -- APPROVAL ----------------------------------------------------------------

    def _approval(self) -> ConstraintResult:
        assert self.order_fact is not None and self.order is not None
        limits = self.policy.approval
        value = self.order.order_value_inr
        total = sum(c.qty_pcs for c in self.order.colours)
        problems: list[str] = []
        if value > limits.max_value_inr:
            problems.append(
                f"order value {_amt(value, 'INR')} exceeds the limit {_amt(limits.max_value_inr, 'INR')}"
            )
        if total > limits.max_qty_pcs:
            problems.append(
                f"total quantity {_amt(total, 'pcs')} exceeds the limit {_amt(limits.max_qty_pcs, 'pcs')}"
            )
        steps = (
            Step(
                label="value",
                expression=f"{_t(value)} <= {_t(limits.max_value_inr)}",
                value=_amt(value, "INR"),
            ),
            Step(
                label="quantity",
                expression=f"{total} <= {limits.max_qty_pcs}",
                value=_amt(total, "pcs"),
            ),
        )
        return ConstraintResult(
            constraint=ConstraintId.APPROVAL,
            subject="order",
            status=ConstraintStatus.FAIL if problems else ConstraintStatus.PASS,
            fact_ids=(self.order_fact.id,),
            steps=steps,
            detail="; ".join(problems) if problems else "within the approval limits",
        )


def evaluate_constraints(
    snapshot: Snapshot, order_id: str, policy: PolicyDocument, gate_result: GateResult
) -> tuple[ConstraintResult, ...]:
    """Every enabled constraint for `order_id` at the snapshot's cutoff, in a fixed order.

    `gate_result.coverage_used` is the stock export the gate trusted for known zeros.
    """
    with localcontext(_CTX):
        return tuple(_Evaluator(snapshot, order_id, policy, gate_result).run())

