"""Pure v2 contracts: units, quantities, enums, facts and the canonical digest.

Framework-free, database-free and IO-free. All arithmetic is Decimal: required
amounts round up and available amounts round down at 0.001, so the
monotonicity properties hold. Floats are rejected rather than coerced.
"""

from __future__ import annotations

import json
import unicodedata
from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_EVEN, Decimal, localcontext
from enum import Enum, StrEnum
from typing import Annotated, Any, Self

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator, model_validator

from flooreplay.domain.hashing import digest

# Copied from domain/types.py on purpose: that module is deleted in T31.


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
# Enums
# ---------------------------------------------------------------------------


class Unit(StrEnum):
    KG = "kg"  # fabric by weight
    M = "m"  # fabric by length
    PCS = "pcs"  # trims and garments
    MINUTES = "minutes"  # line capacity


class FactKind(StrEnum):
    ORDER_REQUEST = "order_request"
    BOM = "bom"
    FABRIC_LOT = "fabric_lot"
    FABRIC_QC = "fabric_qc"
    FABRIC_INBOUND = "fabric_inbound"
    FABRIC_ALLOCATION = "fabric_allocation"
    TRIM_STATUS = "trim_status"
    LINE_CAPACITY = "line_capacity"
    LINE_COMMITMENT = "line_commitment"
    RESOLUTION = "resolution"


class SourceProfile(StrEnum):
    ERP_FABRIC_STOCK = "erp_fabric_stock"
    SHEET_TRIMS_STATUS = "sheet_trims_status"
    SHIFT_CAPACITY = "shift_capacity"
    SUPPLIER_UPDATES = "supplier_updates"
    NOTES = "notes"
    ORDER_REQUESTS = "order_requests"
    REVIEW_QUEUE = "review_queue"


class GateState(StrEnum):
    READY = "READY"
    STALE = "STALE"
    INCOMPLETE = "INCOMPLETE"
    CONFLICTING = "CONFLICTING"


# Lowest to highest: the worst state wins.
_GATE_RANK = {
    GateState.READY: 0,
    GateState.STALE: 1,
    GateState.INCOMPLETE: 2,
    GateState.CONFLICTING: 3,
}


def combine_gate_states(states: Iterable[GateState]) -> GateState:
    """CONFLICTING > INCOMPLETE > STALE > READY; no states means READY."""
    return max(states, key=_GATE_RANK.__getitem__, default=GateState.READY)


class ConstraintId(StrEnum):
    FABRIC = "FABRIC"
    SAFETY = "SAFETY"
    TRIMS = "TRIMS"
    CAPACITY = "CAPACITY"
    OVERTIME = "OVERTIME"
    APPROVAL = "APPROVAL"


class ConstraintStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_EVALUATED = "NOT_EVALUATED"


class Recommendation(StrEnum):
    ACCEPT = "ACCEPT"
    ACCEPT_WITH_CONDITIONS = "ACCEPT_WITH_CONDITIONS"
    DECLINE = "DECLINE"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class ReviewState(StrEnum):
    CHECKS_PASSED = "checks_passed"
    NEEDS_REVIEW = "needs_review"
    CONFIRMED = "confirmed"
    CORRECTED = "corrected"
    REJECTED = "rejected"


class Verdict(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"


class Classification(StrEnum):
    UNCHANGED_PASS = "UNCHANGED_PASS"
    UNCHANGED_FAIL = "UNCHANGED_FAIL"
    FIXED = "FIXED"
    REGRESSION = "REGRESSION"
    NOT_COMPARABLE = "NOT_COMPARABLE"


# ---------------------------------------------------------------------------
# Units and rounding
# ---------------------------------------------------------------------------

_STEP = Decimal("0.001")


class UnitMismatch(ValueError):
    """Arithmetic between quantities of different units."""


def quantize_required(d: Decimal) -> Decimal:
    """Round a required amount up (CEILING) to 0.001."""
    return d.quantize(_STEP, rounding=ROUND_CEILING)


def quantize_available(d: Decimal) -> Decimal:
    """Round an available amount down (FLOOR) to 0.001."""
    return d.quantize(_STEP, rounding=ROUND_FLOOR)


def kg_to_m(kg: Decimal, gsm: Decimal, width_m: Decimal) -> Decimal:
    """metres = kg x 1000 / (gsm x width_m). Not quantized: the caller picks the direction."""
    if gsm <= 0 or width_m <= 0:
        raise ValueError("gsm and width_m must be positive")
    with localcontext() as ctx:
        ctx.prec = 28
        return kg * 1000 / (gsm * width_m)


class Quantity(FrozenModel):
    value: Decimal
    unit: Unit

    @field_validator("value", mode="before")
    @classmethod
    def _decimal_only(cls, raw: Any) -> Decimal:
        if isinstance(raw, bool) or not isinstance(raw, str | int | Decimal):
            raise ValueError("quantity value must be a str, int or Decimal, never a float")
        try:
            value = Decimal(raw)
            if not value.is_finite():
                raise ValueError("quantity value must be finite")
            return value.quantize(_STEP, rounding=ROUND_HALF_EVEN)
        except ArithmeticError as exc:
            raise ValueError(f"not a representable decimal number: {raw!r}") from exc

    def _same_unit(self, other: Quantity) -> None:
        if self.unit != other.unit:
            raise UnitMismatch(f"cannot combine {self.unit.value} with {other.unit.value}")

    def __add__(self, other: Quantity) -> Quantity:
        self._same_unit(other)
        return Quantity(value=self.value + other.value, unit=self.unit)

    def __sub__(self, other: Quantity) -> Quantity:
        self._same_unit(other)
        return Quantity(value=self.value - other.value, unit=self.unit)


# ---------------------------------------------------------------------------
# Facts
# ---------------------------------------------------------------------------


class Fact(FrozenModel):
    id: str
    kind: FactKind
    entity_key: str
    payload: dict[str, Any]
    valid_from: Instant
    valid_to: Instant | None
    known_at: Instant
    supersedes_id: str | None
    source: SourceProfile
    artifact_id: str | None

    @model_validator(mode="after")
    def _valid_interval(self) -> Self:
        if self.valid_to is not None and self.valid_to <= self.valid_from:
            raise ValueError("valid_to must be after valid_from")
        return self


# ---------------------------------------------------------------------------
# Canonical form and digest
# ---------------------------------------------------------------------------


def _decimal_text(d: Decimal) -> str:
    if not d.is_finite():
        raise ValueError("non-finite decimals are not canonicalizable")
    if d == 0:
        return "0"
    return format(d.normalize(), "f")


def canonical(value: Any) -> Any:
    """v2 canonical form: plain JSON-able values, deterministic text, explicit list order."""
    if isinstance(value, BaseModel):
        return canonical(value.model_dump(mode="python"))
    if isinstance(value, Enum):
        return canonical(value.value)
    if isinstance(value, Decimal):
        return _decimal_text(value)
    if isinstance(value, float):
        raise ValueError("floats are not canonicalizable; use Decimal")
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("refusing to canonicalize a naive datetime")
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Mapping):
        out = {canonical(str(k)): canonical(v) for k, v in value.items()}
        return dict(sorted(out.items()))
    if isinstance(value, list | tuple):
        return [canonical(v) for v in value]
    if value is None or isinstance(value, bool | int):
        return value
    raise TypeError(f"cannot canonicalize {type(value).__name__}")


def decision_digest(value: Any) -> str:
    """`sha256:<hex>` over the v2 canonical form, via the shared v1 hashing primitive.

    The canonical form is serialised to compact JSON first so that v1's list-sorting
    hints (keyed on dict keys such as `slots`) can never reorder a v2 list.
    """
    text = json.dumps(
        canonical(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
    return digest(text)
