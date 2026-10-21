"""A coherent READY world for decision tests.

`ready_world()` builds a small, consistent set of facts under `DEFAULT_POLICY_V1` that the
ContextGate calls READY: one order, its BOM, lots for both colours, a status for every BOM
trim, and line capacity for lines L1-L4 on every working day of the sewing window. Every
test perturbs exactly one thing with `without(...)`, `with_facts(...)` or `replace_fact(...)`.

Later tasks (constraints, recommend, replay) reuse this module, so the builders are public.
The world is immutable; every method returns a new world.

Shape (all times UTC):
    cutoff      2026-03-02 09:00
    order O1    style S1, NAVY 600 + WHITE 400 pcs, ships 2026-03-30
    window      cut_date 2026-03-09, sewing 2026-03-10 .. 2026-03-26, Sundays off
    exports     as_of cutoff - 1h, known five minutes later
"""

from __future__ import annotations

import calendar
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from typing import Any

from flooreplay.decisions.gate import CoverageDecl, GateResult, evaluate_gate
from flooreplay.decisions.policy import DEFAULT_POLICY_V1, PolicyDocument
from flooreplay.decisions.snapshot import Snapshot, snapshot_at
from flooreplay.decisions.types import Fact, FactKind, SourceProfile

CUTOFF = datetime(2026, 3, 2, 9, 0, tzinfo=UTC)
AS_OF = CUTOFF - timedelta(hours=1)  # every export's as_of: one hour old, fresh under all limits
SHIP_DATE = date(2026, 3, 30)
ORDER_ID = "O1"
STYLE_ID = "S1"
QUALITY = "SJ180"
COLOURS: tuple[str, ...] = ("NAVY", "WHITE")
LINES: tuple[str, ...] = ("L1", "L2", "L3", "L4")
TRIM_IDS: tuple[str, ...] = ("LABEL", "ZIP")
ERP_ARTIFACT = "artifact-erp-1"

ORDER_KEY = f"order:{ORDER_ID}"
BOM_KEY = f"bom:{STYLE_ID}"

_SOURCE_OF: dict[FactKind, SourceProfile] = {
    FactKind.ORDER_REQUEST: SourceProfile.ORDER_REQUESTS,
    FactKind.BOM: SourceProfile.ORDER_REQUESTS,
    FactKind.FABRIC_LOT: SourceProfile.ERP_FABRIC_STOCK,
    FactKind.FABRIC_QC: SourceProfile.NOTES,
    FactKind.FABRIC_INBOUND: SourceProfile.SUPPLIER_UPDATES,
    FactKind.FABRIC_ALLOCATION: SourceProfile.ERP_FABRIC_STOCK,
    FactKind.TRIM_STATUS: SourceProfile.SHEET_TRIMS_STATUS,
    FactKind.LINE_CAPACITY: SourceProfile.SHIFT_CAPACITY,
    FactKind.LINE_COMMITMENT: SourceProfile.SHIFT_CAPACITY,
    FactKind.RESOLUTION: SourceProfile.REVIEW_QUEUE,
}


def kg(value: str) -> dict[str, str]:
    return {"value": value, "unit": "kg"}


def make_fact(
    fact_id: str,
    kind: FactKind,
    entity_key: str,
    payload: Mapping[str, Any],
    *,
    valid_from: datetime = AS_OF,
    valid_to: datetime | None = None,
    known_at: datetime | None = None,
    supersedes_id: str | None = None,
    source: SourceProfile | None = None,
    artifact_id: str | None = None,
) -> Fact:
    """A Fact with the source profile implied by its kind; known five minutes after valid_from."""
    return Fact(
        id=fact_id,
        kind=kind,
        entity_key=entity_key,
        payload=dict(payload),
        valid_from=valid_from,
        valid_to=valid_to,
        known_at=known_at if known_at is not None else valid_from + timedelta(minutes=5),
        supersedes_id=supersedes_id,
        source=source if source is not None else _SOURCE_OF[kind],
        artifact_id=artifact_id,
    )


def order_fact(
    fact_id: str = "w-order",
    *,
    order_id: str = ORDER_ID,
    colours: Iterable[tuple[str, int]] = (("NAVY", 600), ("WHITE", 400)),
    ship_date: date = SHIP_DATE,
    style_id: str = STYLE_ID,
    **kwargs: Any,
) -> Fact:
    kwargs.setdefault("valid_from", CUTOFF - timedelta(hours=12))
    return make_fact(
        fact_id,
        FactKind.ORDER_REQUEST,
        f"order:{order_id}",
        {
            "buyer": "BUYER-1",
            "style_id": style_id,
            "colours": [{"colour": c, "qty_pcs": q} for c, q in colours],
            "ship_date": ship_date,
            "order_value_inr": "2500000",
            "partial_shipment_allowed": True,
        },
        **kwargs,
    )


def bom_fact(
    fact_id: str = "w-bom",
    *,
    style_id: str = STYLE_ID,
    unit: str = "kg",
    consumption: str = "0.35",
    trim_ids: Iterable[str] = TRIM_IDS,
    **kwargs: Any,
) -> Fact:
    kwargs.setdefault("valid_from", CUTOFF - timedelta(hours=12))
    return make_fact(
        fact_id,
        FactKind.BOM,
        f"bom:{style_id}",
        {
            "fabric_quality": QUALITY,
            "consumption_per_pc": {"value": consumption, "unit": unit},
            "trims": [{"trim_id": t, "qty_per_pc": "1"} for t in trim_ids],
            "sam_minutes": "12.5",
        },
        **kwargs,
    )


def lot_fact(
    fact_id: str,
    lot_id: str,
    colour: str,
    qty: str = "500",
    *,
    quality: str = QUALITY,
    unit: str = "kg",
    gsm: str | None = None,
    width_m: str | None = None,
    **kwargs: Any,
) -> Fact:
    kwargs.setdefault("artifact_id", ERP_ARTIFACT)
    payload: dict[str, Any] = {
        "fabric_quality": quality,
        "colour": colour,
        "qty": {"value": qty, "unit": unit},
    }
    if gsm is not None:
        payload["gsm"] = gsm
    if width_m is not None:
        payload["width_m"] = width_m
    return make_fact(fact_id, FactKind.FABRIC_LOT, f"lot:{lot_id}", payload, **kwargs)


def qc_fact(
    fact_id: str,
    lot_id: str,
    qty: str = "50",
    *,
    review_state: str = "checks_passed",
    issue: str = "shade_fail",
    **kwargs: Any,
) -> Fact:
    return make_fact(
        fact_id,
        FactKind.FABRIC_QC,
        f"lot:{lot_id}",
        {"issue": issue, "qty": kg(qty), "review_state": review_state, "origin": "notes"},
        **kwargs,
    )


def inbound_fact(
    fact_id: str,
    ref: str,
    colour: str = "NAVY",
    qty: str = "200",
    *,
    eta: date = date(2026, 3, 6),
    **kwargs: Any,
) -> Fact:
    return make_fact(
        fact_id,
        FactKind.FABRIC_INBOUND,
        f"inbound:{ref}",
        {
            "fabric_quality": QUALITY,
            "colour": colour,
            "qty": kg(qty),
            "eta": eta,
            "supplier": "SUP-1",
        },
        **kwargs,
    )


def trim_fact(
    fact_id: str, trim_id: str, on_hand: str = "100000", *, style_id: str = STYLE_ID, **kwargs: Any
) -> Fact:
    return make_fact(
        fact_id,
        FactKind.TRIM_STATUS,
        f"trim:{style_id}:{trim_id}",
        {"on_hand": {"value": on_hand, "unit": "pcs"}, "supplier": "SUP-2"},
        **kwargs,
    )


def capacity_fact(
    fact_id: str, line_id: str, day: date, minutes: str = "3000", **kwargs: Any
) -> Fact:
    return make_fact(
        fact_id,
        FactKind.LINE_CAPACITY,
        f"line:{line_id}:{day.isoformat()}",
        {"available_minutes": {"value": minutes, "unit": "minutes"}},
        **kwargs,
    )


def resolution_fact(
    fact_id: str,
    entity_key: str,
    *,
    rule_id: str,
    left_fact_id: str,
    right_fact_id: str,
    **kwargs: Any,
) -> Fact:
    return make_fact(
        fact_id,
        FactKind.RESOLUTION,
        entity_key,
        {
            "rule_id": rule_id,
            "left_fact_id": left_fact_id,
            "right_fact_id": right_fact_id,
            "resolved_payload": {"usable_qty": kg("450")},
            "reviewer": "owner",
        },
        **kwargs,
    )


def working_days(policy: PolicyDocument, ship_date: date) -> list[date]:
    """The sewing window, derived independently of `policy.sewing_days` (ordinals, no timedelta).

    Working days in [ship - cut_to_ship + 1, ship - finishing], skipping the non-working
    weekdays (by calendar name) and the holidays.
    """
    cap = policy.capacity
    first = ship_date.toordinal() - cap.cut_to_ship_days + 1
    last = ship_date.toordinal() - cap.finishing_days
    off = {d.value for d in cap.non_working_weekdays}
    holidays = {h.toordinal() for h in cap.holidays}
    return [
        date.fromordinal(n)
        for n in range(first, last + 1)
        if calendar.day_name[date.fromordinal(n).weekday()][:3].upper() not in off
        and n not in holidays
    ]


def cover(
    *qualities: str,
    artifact_id: str = ERP_ARTIFACT,
    as_of: datetime = AS_OF,
    profile: SourceProfile = SourceProfile.ERP_FABRIC_STOCK,
) -> dict[str, CoverageDecl]:
    """A one-artifact coverage mapping."""
    return {
        artifact_id: CoverageDecl(profile=profile, as_of=as_of, qualities=frozenset(qualities))
    }


@dataclass(frozen=True)
class World:
    facts: tuple[Fact, ...]
    cutoff: datetime = CUTOFF
    order_id: str = ORDER_ID
    policy: PolicyDocument = DEFAULT_POLICY_V1
    coverage: Mapping[str, CoverageDecl] = field(default_factory=lambda: cover(QUALITY))

    def snapshot(self, cutoff: datetime | None = None) -> Snapshot:
        return snapshot_at(self.facts, cutoff if cutoff is not None else self.cutoff)

    def gate(self, cutoff: datetime | None = None) -> GateResult:
        return evaluate_gate(self.snapshot(cutoff), self.order_id, self.policy, self.coverage)

    def get(self, fact_id: str) -> Fact:
        return next(f for f in self.facts if f.id == fact_id)

    def without(
        self,
        *,
        kind: FactKind | None = None,
        entity_key: str | None = None,
        fact_id: str | None = None,
        where: Callable[[Fact], bool] | None = None,
    ) -> World:
        """Drop every fact matching all the given criteria."""

        def matches(f: Fact) -> bool:
            return (
                (kind is None or f.kind == kind)
                and (entity_key is None or f.entity_key == entity_key)
                and (fact_id is None or f.id == fact_id)
                and (where is None or where(f))
            )

        return replace(self, facts=tuple(f for f in self.facts if not matches(f)))

    def with_facts(self, *extra: Fact) -> World:
        return replace(self, facts=(*self.facts, *extra))

    def replace_fact(self, fact_id: str, **changes: Any) -> World:
        """Swap one fact for a copy with the given field changes."""
        return replace(
            self,
            facts=tuple(f.model_copy(update=changes) if f.id == fact_id else f for f in self.facts),
        )

    def with_policy(self, policy: PolicyDocument) -> World:
        return replace(self, policy=policy)

    def with_coverage(self, coverage: Mapping[str, CoverageDecl]) -> World:
        return replace(self, coverage=coverage)

    def at(self, cutoff: datetime) -> World:
        return replace(self, cutoff=cutoff)


def ready_world(
    policy: PolicyDocument = DEFAULT_POLICY_V1, ship_date: date = SHIP_DATE
) -> World:
    """A world the gate calls READY: nothing missing, stale or conflicting."""
    facts: list[Fact] = [
        order_fact(ship_date=ship_date),
        bom_fact(),
        lot_fact("w-lot-navy", "LOT-N1", "NAVY", "500"),
        lot_fact("w-lot-white", "LOT-W1", "WHITE", "300"),
    ]
    facts += [trim_fact(f"w-trim-{t}", t) for t in TRIM_IDS]
    for line in policy.capacity.eligible_lines:
        for day in working_days(policy, ship_date):
            facts.append(capacity_fact(f"w-cap-{line}-{day.isoformat()}", line, day))
    return World(facts=tuple(facts), policy=policy)
