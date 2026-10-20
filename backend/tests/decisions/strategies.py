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
    def dump(q: SearchStrategy[Quantity], name: str) -> SearchStrategy[dict[str, Any]]:
        return q.map(lambda x: {name: x.model_dump(mode="json")})

    match kind:
        case (
            FactKind.FABRIC_LOT
            | FactKind.FABRIC_QC
            | FactKind.FABRIC_INBOUND
            | FactKind.FABRIC_ALLOCATION
        ):
            return dump(quantities(Unit.KG), "qty")
        case FactKind.TRIM_STATUS:
            return dump(quantities(Unit.PCS), "on_hand")
        case FactKind.LINE_CAPACITY:
            return dump(quantities(Unit.MINUTES), "available_minutes")
        case FactKind.LINE_COMMITMENT:
            return dump(quantities(Unit.MINUTES), "committed_minutes")
        case _:
            return st.just({})


@st.composite
def facts(draw: DrawFn, kind: FactKind | None = None) -> Fact:
    """A valid standalone Fact (no supersession) of the given kind (any when None)."""
    chosen = kind if kind is not None else draw(st.sampled_from(list(FactKind)))
    valid_from = draw(instants())
    valid_to = draw(
        st.none() | st.integers(1, 7 * 24 * 60).map(lambda m: valid_from + timedelta(minutes=m))
    )
    return Fact(
        id=draw(st.from_regex(r"F[0-9]{1,4}", fullmatch=True)),
        kind=chosen,
        entity_key=draw(entity_keys(chosen)),
        payload=draw(_payload(chosen)),
        valid_from=valid_from,
        valid_to=valid_to,
        known_at=draw(instants()),
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
        history.append(fact.model_copy(update={"id": f"F{index}", "supersedes_id": target}))
    return history
