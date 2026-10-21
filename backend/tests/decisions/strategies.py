"""Shared Hypothesis strategies for the v2 decision tests.

Entity keys come from a deliberately tiny alphabet (3 lots, 2 colours, 2 lines, ...)
so independently drawn facts collide on the same entity and exercise supersession.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from hypothesis import strategies as st
from hypothesis.strategies import DrawFn, SearchStrategy

from flooreplay.decisions.types import Fact, FactKind, Quantity, SourceProfile, Unit

_EPOCH = datetime(2026, 1, 1, tzinfo=UTC)
_MINUTES_IN_2026 = 365 * 24 * 60
_MAX_LAG_MINUTES = 3 * 24 * 60  # how long after valid_from a fact may become known

LOTS = ("L1", "L2", "L3")
COLOURS = ("NAVY", "WHITE")
LINES = ("LINE-1", "LINE-2")
ORDERS = ("O1", "O2")
STYLES = ("S1", "S2")
TRIMS = ("ZIP", "LABEL")
QUALITIES = ("SJ180",)
DATES = ("2026-03-02", "2026-03-03")

_KEYS: dict[FactKind, tuple[str, ...]] = {
    FactKind.ORDER_REQUEST: tuple(f"order:{o}" for o in ORDERS),
    FactKind.BOM: tuple(f"bom:{s}" for s in STYLES),
    FactKind.FABRIC_LOT: tuple(f"lot:{lot}" for lot in LOTS),
    FactKind.FABRIC_QC: tuple(f"lot:{lot}" for lot in LOTS),
    FactKind.FABRIC_INBOUND: ("inbound:I1", "inbound:I2"),
    FactKind.FABRIC_ALLOCATION: tuple(
        f"alloc:{o}:{q}:{c}" for o in ORDERS for q in QUALITIES for c in COLOURS
    ),
    FactKind.TRIM_STATUS: tuple(f"trim:{s}:{t}" for s in STYLES for t in TRIMS),
    FactKind.LINE_CAPACITY: tuple(f"line:{ln}:{d}" for ln in LINES for d in DATES),
    FactKind.LINE_COMMITMENT: tuple(
        f"commit:{o}:{ln}:{d}" for o in ORDERS for ln in LINES for d in DATES
    ),
    FactKind.RESOLUTION: tuple(f"lot:{lot}" for lot in LOTS),
}

_SOURCE: dict[FactKind, SourceProfile] = {
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


@st.composite
def decimals_3dp(
    draw: DrawFn, min_value: Decimal = Decimal("0"), max_value: Decimal = Decimal("1000")
) -> Decimal:
    """A Decimal with exactly three decimal places in [min_value, max_value]."""
    low, high = int(min_value * 1000), int(max_value * 1000)
    return Decimal(draw(st.integers(min_value=low, max_value=high))).scaleb(-3)


@st.composite
def quantities(draw: DrawFn, unit: Unit | None = None) -> Quantity:
    """A non-negative Quantity of the given unit (any unit when None)."""
    chosen = unit if unit is not None else draw(st.sampled_from(list(Unit)))
    return Quantity(value=draw(decimals_3dp()), unit=chosen)


@st.composite
def instants(draw: DrawFn) -> datetime:
    """A UTC instant at minute resolution somewhere in 2026."""
    return _EPOCH + timedelta(minutes=draw(st.integers(0, _MINUTES_IN_2026)))


def entity_keys(kind: FactKind) -> SearchStrategy[str]:
    """An entity key for the kind, drawn from a small alphabet to force collisions."""
    return st.sampled_from(_KEYS[kind])


def _payload(kind: FactKind) -> SearchStrategy[dict[str, Any]]:
    """A payload that satisfies the kind's schema in `flooreplay.decisions.facts`."""

    def qty(name: str, unit: Unit) -> SearchStrategy[dict[str, Any]]:
        return quantities(unit).map(lambda x: {name: x.model_dump(mode="json")})

    def merge(
        base: dict[str, Any], extra: SearchStrategy[dict[str, Any]]
    ) -> SearchStrategy[dict[str, Any]]:
        return extra.map(lambda e: {**base, **e})

    kg = qty("qty", Unit.KG)
    match kind:
        case FactKind.ORDER_REQUEST:
            return st.builds(
                lambda pcs, value, partial: {
                    "buyer": "BUYER-1",
                    "style_id": "S1",
                    "colours": [{"colour": "NAVY", "qty_pcs": pcs}],
                    "ship_date": "2026-03-20",
                    "order_value_inr": str(value),
                    "partial_shipment_allowed": partial,
                },
                st.integers(1, 5000),
                decimals_3dp(),
                st.booleans(),
            )
        case FactKind.BOM:
            return qty("consumption_per_pc", Unit.KG).map(
                lambda q: {
                    "fabric_quality": "SJ180",
                    **q,
                    "trims": [{"trim_id": "ZIP", "qty_per_pc": "1"}],
                    "sam_minutes": "12.5",
                }
            )
        case FactKind.FABRIC_LOT:
            return merge({"fabric_quality": "SJ180", "colour": "NAVY"}, kg)
        case FactKind.FABRIC_QC:
            return merge(
                {
                    "issue": "shade_fail",
                    "review_state": "checks_passed",
                    "origin": "notes",
                },
                kg,
            )
        case FactKind.FABRIC_INBOUND:
            return merge(
                {
                    "fabric_quality": "SJ180",
                    "colour": "NAVY",
                    "eta": "2026-03-05",
                    "supplier": "SUP-1",
                },
                kg,
            )
        case FactKind.FABRIC_ALLOCATION:
            return kg
        case FactKind.TRIM_STATUS:
            return merge({"supplier": "SUP-1"}, qty("on_hand", Unit.PCS))
        case FactKind.LINE_CAPACITY:
            return qty("available_minutes", Unit.MINUTES)
        case FactKind.LINE_COMMITMENT:
            return qty("committed_minutes", Unit.MINUTES)
        case FactKind.RESOLUTION:
            return qty("usable_qty", Unit.KG).map(
                lambda q: {
                    "rule_id": "R1",
                    "left_fact_id": "F-left",
                    "right_fact_id": "F-right",
                    "resolved_payload": q,
                    "reviewer": "owner",
                }
            )


@st.composite
def facts(draw: DrawFn, kind: FactKind | None = None, future_dated: bool = False) -> Fact:
    """A valid standalone Fact (no supersession) of the given kind (any when None).

    No backdating: `known_at >= valid_from` (the export's as_of is never after the time it
    was recorded). `future_dated=True` draws `known_at < valid_from` for negative tests.
    """
    chosen = kind if kind is not None else draw(st.sampled_from(list(FactKind)))
    valid_from = draw(instants())
    valid_to = draw(
        st.none() | st.integers(1, 7 * 24 * 60).map(lambda m: valid_from + timedelta(minutes=m))
    )
    lag = draw(st.integers(1 if future_dated else 0, _MAX_LAG_MINUTES))
    known_at = valid_from + timedelta(minutes=-lag if future_dated else lag)
    return Fact(
        id=draw(st.from_regex(r"F[0-9]{1,4}", fullmatch=True)),
        kind=chosen,
        entity_key=draw(entity_keys(chosen)),
        payload=draw(_payload(chosen)),
        valid_from=valid_from,
        valid_to=valid_to,
        known_at=known_at,
        supersedes_id=None,
        source=_SOURCE[chosen],
        artifact_id=draw(st.none() | st.just("A1")),
    )


@st.composite
def fact_histories(draw: DrawFn, max_size: int = 8) -> list[Fact]:
    """Facts ordered by known_at with unique ids; supersedes_id only names an earlier fact of the same kind and entity_key."""
    kinds = draw(st.lists(st.sampled_from(list(FactKind)), min_size=1, max_size=2))
    drawn = draw(st.lists(st.sampled_from(kinds).flatmap(facts), min_size=1, max_size=max_size))
    ordered = sorted(drawn, key=lambda f: f.known_at)  # stable: ties keep draw order
    history: list[Fact] = []
    for index, fact in enumerate(ordered):
        earlier = [
            f
            for f in history
            if f.known_at < fact.known_at and (f.kind, f.entity_key) == (fact.kind, fact.entity_key)
        ]
        target = draw(st.sampled_from(earlier)).id if earlier and draw(st.booleans()) else None
        update: dict[str, Any] = {"id": f"F{index}", "supersedes_id": target}
        if target is not None:  # a correction fixes the same observation: same valid time
            original = next(f for f in history if f.id == target)
            update |= {"valid_from": original.valid_from, "valid_to": original.valid_to}
        history.append(fact.model_copy(update=update))
    return history


_T0 = datetime(2026, 3, 1, 8, 0, tzinfo=UTC)


def _lot(
    fid: str,
    valid_from: datetime,
    valid_to: datetime | None,
    known_at: datetime,
    kg: str,
    supersedes_id: str | None,
    key: str = "lot:L1",
) -> Fact:
    return Fact(
        id=fid,
        kind=FactKind.FABRIC_LOT,
        entity_key=key,
        payload={"fabric_quality": "SJ180", "colour": "NAVY", "qty": {"value": kg, "unit": "kg"}},
        valid_from=valid_from,
        valid_to=valid_to,
        known_at=known_at,
        supersedes_id=supersedes_id,
        source=SourceProfile.ERP_FABRIC_STOCK,
        artifact_id=None,
    )


@st.composite
def chain_histories(draw: DrawFn, max_depth: int = 5) -> list[Fact]:
    """One lot observation corrected repeatedly (A <- B <- C ...), sometimes forking.

    Biased towards deep chains: each correction usually targets the latest fact, sometimes an
    earlier one (a fork, so two replacements compete). Corrections keep the original's valid
    time and become known strictly later.
    """
    depth = draw(st.integers(2, max_depth))
    root_known = _T0 + timedelta(minutes=draw(st.integers(0, 600)))
    history = [_lot("C0", _T0, None, root_known, str(draw(st.sampled_from((100, 200)))), None)]
    for index in range(1, depth):
        latest = history[-1]
        target = draw(st.sampled_from([latest, latest, *history]))
        known = max(f.known_at for f in history) + timedelta(minutes=draw(st.integers(1, 600)))
        kg = str(draw(st.sampled_from((100, 200, 300))))
        history.append(_lot(f"C{index}", _T0, None, known, kg, target.id))
    return history


@st.composite
def tied_lot_histories(draw: DrawFn, max_size: int = 6) -> list[Fact]:
    """Lot observations for two entities with `valid_from` drawn from two values, so facts of
    one entity often share a valid_from (ties) with equal or different payloads."""
    history: list[Fact] = []
    for index in range(draw(st.integers(1, max_size))):
        key = draw(st.sampled_from(("lot:L1", "lot:L2")))
        kg = str(draw(st.sampled_from((100, 200))))
        target = None
        same_entity = [f for f in history if f.entity_key == key]
        if same_entity and draw(st.booleans()):
            target = draw(st.sampled_from(same_entity))
        if target is None:
            valid_from = _T0 + timedelta(days=draw(st.integers(0, 1)))
            known = valid_from + timedelta(minutes=draw(st.integers(0, 600)))
            history.append(_lot(f"T{index}", valid_from, None, known, kg, None, key))
        else:
            known = target.known_at + timedelta(minutes=draw(st.integers(1, 600)))
            history.append(
                _lot(f"T{index}", target.valid_from, target.valid_to, known, kg, target.id, key)
            )
    return history
