"""Pure fact registry: entity-key shapes, typed payloads, semantic digests, correction checks.

Framework-free, database-free and IO-free. Ports `incident_engine.validate_corrections`.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, Final, NamedTuple

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, ValidationError, field_validator

from flooreplay.decisions.types import (
    Fact,
    FactKind,
    FrozenModel,
    Quantity,
    ReviewState,
    Unit,
    decision_digest,
)

# Payload fields that describe where a value came from, not what it is. They are
# parsed (so imports may carry them) but excluded from tie comparison.
NON_SEMANTIC_FIELDS: Final = frozenset({"row_number", "raw_text", "raw"})

_FABRIC_UNITS = frozenset({Unit.KG, Unit.M})


def _no_float(raw: Any) -> Any:
    if isinstance(raw, float):
        raise ValueError("floats are not allowed; give a decimal string or integer")
    return raw


Number = Annotated[Decimal, BeforeValidator(_no_float), Field(ge=0)]
PositiveNumber = Annotated[Decimal, BeforeValidator(_no_float), Field(gt=0)]


def _units(quantity: Quantity, allowed: Iterable[Unit]) -> Quantity:
    allowed = frozenset(allowed)
    if quantity.unit not in allowed:
        names = "/".join(sorted(u.value for u in allowed))
        raise ValueError(f"unit must be {names}, got {quantity.unit.value}")
    return quantity


# ---------------------------------------------------------------------------
# Payload schemas
# ---------------------------------------------------------------------------


class Payload(FrozenModel):
    """Base for payloads: strict, with the optional non-semantic provenance fields."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    row_number: int | None = None
    raw_text: str | None = None
    raw: str | None = None


class OrderColour(FrozenModel):
    colour: str = Field(min_length=1)
    qty_pcs: int = Field(ge=0)


class OrderRequestPayload(Payload):
    buyer: str
    style_id: str
    colours: list[OrderColour] = Field(min_length=1)
    ship_date: date
    order_value_inr: Number
    partial_shipment_allowed: bool

    @field_validator("colours")
    @classmethod
    def _sorted(cls, v: list[OrderColour]) -> list[OrderColour]:
        return sorted(v, key=lambda c: c.colour)


class BomTrim(FrozenModel):
    trim_id: str = Field(min_length=1)
    qty_per_pc: Number


class BomPayload(Payload):
    fabric_quality: str
    consumption_per_pc: Quantity
    trims: list[BomTrim]
    sam_minutes: PositiveNumber

    @field_validator("consumption_per_pc")
    @classmethod
    def _fabric_unit(cls, v: Quantity) -> Quantity:
        return _units(v, _FABRIC_UNITS)

    @field_validator("trims")
    @classmethod
    def _sorted(cls, v: list[BomTrim]) -> list[BomTrim]:
        return sorted(v, key=lambda t: t.trim_id)


class _FabricQty(Payload):
    qty: Quantity

    @field_validator("qty")
    @classmethod
    def _fabric_unit(cls, v: Quantity) -> Quantity:
        return _units(v, _FABRIC_UNITS)


class FabricLotPayload(_FabricQty):
    fabric_quality: str
    colour: str
    gsm: PositiveNumber | None = None
    width_m: PositiveNumber | None = None


class QcIssue(StrEnum):
    SHADE_FAIL = "shade_fail"
    GSM_FAIL = "gsm_fail"
    DEFECT = "defect"


class FabricQcPayload(_FabricQty):
    issue: QcIssue
    review_state: ReviewState
    origin: str
    extraction_id: str | None = None


class FabricInboundPayload(_FabricQty):
    fabric_quality: str
    colour: str
    eta: date
    supplier: str


class FabricAllocationPayload(_FabricQty):
    pass


class TrimStatusPayload(Payload):
    on_hand: Quantity
    inbound_qty: Quantity | None = None
    eta: date | None = None
    supplier: str

    @field_validator("on_hand", "inbound_qty")
    @classmethod
    def _pcs(cls, v: Quantity | None) -> Quantity | None:
        return None if v is None else _units(v, {Unit.PCS})


class LineCapacityPayload(Payload):
    available_minutes: Quantity
    efficiency_pct: PositiveNumber | None = None

    @field_validator("available_minutes")
    @classmethod
    def _minutes(cls, v: Quantity) -> Quantity:
        return _units(v, {Unit.MINUTES})


class LineCommitmentPayload(Payload):
    committed_minutes: Quantity

    @field_validator("committed_minutes")
    @classmethod
    def _minutes(cls, v: Quantity) -> Quantity:
        return _units(v, {Unit.MINUTES})


class ResolutionPayload(Payload):
    rule_id: str
    left_fact_id: str
    right_fact_id: str
    resolved_payload: dict[str, Any]
    reviewer: str


# ---------------------------------------------------------------------------
# Kind registry
# ---------------------------------------------------------------------------

_ID = r"[^:\s]+"
_DATE = r"\d{4}-\d{2}-\d{2}"


class KindSpec(NamedTuple):
    template: str  # human-readable shape, e.g. "lot:{lot_id}"
    pattern: re.Pattern[str]
    payload_model: type[Payload]


def _spec(template: str, payload_model: type[Payload]) -> KindSpec:
    regex = re.sub(r"\{(\w+)\}", lambda m: _DATE if m[1] == "date" else _ID, template)
    return KindSpec(template, re.compile(regex), payload_model)


KIND_REGISTRY: Final[Mapping[FactKind, KindSpec]] = {
    FactKind.ORDER_REQUEST: _spec("order:{order_id}", OrderRequestPayload),
    FactKind.BOM: _spec("bom:{style_id}", BomPayload),
    FactKind.FABRIC_LOT: _spec("lot:{lot_id}", FabricLotPayload),
    FactKind.FABRIC_QC: _spec("lot:{lot_id}", FabricQcPayload),
    FactKind.FABRIC_INBOUND: _spec("inbound:{ref}", FabricInboundPayload),
    FactKind.FABRIC_ALLOCATION: _spec(
        "alloc:{order_id}:{quality}:{colour}", FabricAllocationPayload
    ),
    FactKind.TRIM_STATUS: _spec("trim:{style_id}:{trim_id}", TrimStatusPayload),
    FactKind.LINE_CAPACITY: _spec("line:{line_id}:{date}", LineCapacityPayload),
    FactKind.LINE_COMMITMENT: _spec("commit:{order_id}:{line_id}:{date}", LineCommitmentPayload),
    # Keyed by the entity it resolves: any other kind's shape fits (see _entity_key_matches).
    FactKind.RESOLUTION: KindSpec(
        "<the conflicted entity_key>", re.compile("(?!)"), ResolutionPayload
    ),
}


class FactValidationError(ValueError):
    """A fact's entity_key or payload does not match its kind."""

    def __init__(self, code: str, message: str, fact_id: str) -> None:
        super().__init__(f"{message} (fact {fact_id})")
        self.code = code
        self.fact_id = fact_id


def _entity_key_matches(kind: FactKind, key: str) -> bool:
    if kind is FactKind.RESOLUTION:
        return any(
            spec.pattern.fullmatch(key)
            for other, spec in KIND_REGISTRY.items()
            if other is not FactKind.RESOLUTION
        )
    return KIND_REGISTRY[kind].pattern.fullmatch(key) is not None


def parse_payload(fact: Fact) -> Payload:
    """The fact's payload as its typed model; FactValidationError when it does not parse."""
    model = KIND_REGISTRY[fact.kind].payload_model
    try:
        return model.model_validate(fact.payload)
    except ValidationError as exc:
        raise FactValidationError("bad_payload", f"payload invalid: {exc}", fact.id) from exc


def validate_fact(fact: Fact) -> Fact:
    """Check the entity_key shape and payload for the kind; return the fact with a normalised payload."""
    if not _entity_key_matches(fact.kind, fact.entity_key):
        shape = KIND_REGISTRY[fact.kind].template
        raise FactValidationError(
            "bad_entity_key",
            f"entity_key {fact.entity_key!r} does not match {fact.kind.value} shape {shape}",
            fact.id,
        )
    parsed = parse_payload(fact)
    # Rebuild through validation so any Fact-level payload canonicalisation re-runs.
    return Fact.model_validate({**fact.model_dump(), "payload": parsed.model_dump(mode="json")})


def semantic_digest(fact: Fact) -> str:
    """Digest of the parsed payload without NON_SEMANTIC_FIELDS: the tie-comparison identity."""
    parsed: BaseModel = parse_payload(fact)
    return decision_digest(parsed.model_dump(mode="python", exclude=set(NON_SEMANTIC_FIELDS)))


# ---------------------------------------------------------------------------
# Correction graph
# ---------------------------------------------------------------------------


class CorrectionErrorCode(StrEnum):
    DUPLICATE_ID = "duplicate_id"
    UNKNOWN_TARGET = "unknown_target"
    CYCLE = "cycle"
    KIND_MISMATCH = "kind_mismatch"
    ENTITY_MISMATCH = "entity_mismatch"
    NOT_AFTER_TARGET = "not_after_target"


class CorrectionError(ValueError):
    def __init__(self, code: CorrectionErrorCode, message: str, fact_id: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.fact_id = fact_id


def validate_corrections(facts: Iterable[Fact]) -> None:
    """Validate the whole correction graph of `facts`; raise CorrectionError on the first problem.

    Callers pass the full list at write time, and only the visible subset at read time.
    """
    rows = sorted(facts, key=lambda f: f.id)
    by_id = {f.id: f for f in rows}
    if len(by_id) != len(rows):
        raise CorrectionError(CorrectionErrorCode.DUPLICATE_ID, "duplicate fact id")
    for fact in rows:
        if fact.supersedes_id is None:
            continue
        target = by_id.get(fact.supersedes_id)
        if target is None:
            raise CorrectionError(
                CorrectionErrorCode.UNKNOWN_TARGET,
                f"fact {fact.id} supersedes unknown fact {fact.supersedes_id}",
                fact.id,
            )
        seen = {fact.id}
        cursor: Fact | None = target
        while cursor is not None:
            if cursor.id in seen:
                raise CorrectionError(
                    CorrectionErrorCode.CYCLE,
                    f"correction graph has a cycle at {cursor.id}",
                    fact.id,
                )
            seen.add(cursor.id)
            cursor = by_id.get(cursor.supersedes_id) if cursor.supersedes_id else None
        if fact.kind != target.kind:
            raise CorrectionError(
                CorrectionErrorCode.KIND_MISMATCH,
                f"fact {fact.id} is {fact.kind.value}, its target is {target.kind.value}",
                fact.id,
            )
        if fact.entity_key != target.entity_key:
            raise CorrectionError(
                CorrectionErrorCode.ENTITY_MISMATCH,
                f"fact {fact.id} is for {fact.entity_key}, its target for {target.entity_key}",
                fact.id,
            )
        if fact.known_at <= target.known_at:
            raise CorrectionError(
                CorrectionErrorCode.NOT_AFTER_TARGET,
                f"fact {fact.id} must be known strictly after {target.id}",
                fact.id,
            )
