"""Pure v2 contracts: units, quantities, enums, facts and the canonical digest.

Framework-free, database-free and IO-free. All arithmetic is Decimal: required
amounts round up and available amounts round down at 0.001, so the
monotonicity properties hold. Floats are rejected rather than coerced.

One JSON-stable rule: values are stored in canonical form. Decimals are plain
decimal text ("1.5", never "1.50" or "1.5E+0"), datetimes are UTC "Z" strings,
text is NFC. Ints stay JSON ints and are NOT interchangeable with Decimals:
`1000` and `Decimal(1000)` ("1000") digest differently, so a builder must use
one representation per field (Decimal for every quantity). A `Fact.payload`
is canonicalised on construction and a `Quantity` serialises to the same text,
so in-memory, dumped and reloaded forms always share one `decision_digest`.
All Decimal work runs in an explicit context and never reads the ambient one.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime
from decimal import (
    ROUND_CEILING,
    ROUND_FLOOR,
    ROUND_HALF_EVEN,
    Context,
    Decimal,
    DivisionByZero,
    InvalidOperation,
    Overflow,
    localcontext,
)
from enum import Enum, StrEnum
from typing import Annotated, Any, NoReturn, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

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
_QUANTITY_TEXT = re.compile(r"-?\d+(\.\d+)?", re.ASCII)
_MAX_EXPONENT = 1000  # canonical text is built by padding zeros, so bound the padding


def _context(prec: int) -> Context:
    """A fresh explicit context: results never depend on the caller's ambient context."""
    return Context(
        prec=prec,
        rounding=ROUND_HALF_EVEN,
        Emin=-999_999,
        Emax=999_999,
        traps=[InvalidOperation, DivisionByZero, Overflow],
    )


def _require_finite(*values: Decimal) -> None:
    for value in values:
        if not value.is_finite():
            raise ValueError("decimal inputs must be finite")


def _quantize(d: Decimal, rounding: str) -> Decimal:
    _require_finite(d)
    with localcontext(_context(200)):
        try:
            return d.quantize(_STEP, rounding=rounding)
        except InvalidOperation as exc:
            raise ValueError("decimal too large to quantize") from exc


class UnitMismatch(ValueError):
    """Arithmetic between quantities of different units."""


def quantize_required(d: Decimal) -> Decimal:
    """Round a required amount up (CEILING) to 0.001."""
    return _quantize(d, ROUND_CEILING)


def quantize_available(d: Decimal) -> Decimal:
    """Round an available amount down (FLOOR) to 0.001."""
    return _quantize(d, ROUND_FLOOR)


def kg_to_m(kg: Decimal, gsm: Decimal, width_m: Decimal) -> Decimal:
    """metres = kg x 1000 / (gsm x width_m), to 28 significant digits.

    Not quantized: the caller picks the direction with quantize_required/available.
    """
    _require_finite(kg, gsm, width_m)
    if gsm <= 0 or width_m <= 0:
        raise ValueError("gsm and width_m must be positive")
    with localcontext(_context(28)):
        return kg * 1000 / (gsm * width_m)


class Quantity(FrozenModel):
    """A Decimal amount (exactly 3 dp) with a unit. JSON form: canonical text, e.g. "5"."""

    value: Decimal
    unit: Unit

    @field_validator("value", mode="before")
    @classmethod
    def _exact_decimal(cls, raw: Any) -> Decimal:
        if isinstance(raw, bool) or not isinstance(raw, str | int | Decimal):
            raise ValueError("quantity value must be a str, int or Decimal, never a float")
        if isinstance(raw, str):
            if not _QUANTITY_TEXT.fullmatch(raw):
                raise ValueError(f"quantity text must look like -?digits[.digits]: {raw!r}")
            raw = Decimal(raw)
        value = Decimal(raw)
        _require_finite(value)
        whole, _, fraction = _decimal_text(value).partition(".")
        if len(fraction) > 3:
            raise ValueError(
                "more than 3 decimal places; round with quantize_required or quantize_available"
            )
        return Decimal(f"{whole}.{fraction.ljust(3, '0')}")

    @field_serializer("value", when_used="json")
    def _canonical_text(self, value: Decimal) -> str:
        return _decimal_text(value)

    def _same_unit(self, other: Quantity) -> None:
        if self.unit != other.unit:
            raise UnitMismatch(f"cannot combine {self.unit.value} with {other.unit.value}")

    def __add__(self, other: Quantity) -> Quantity:
        self._same_unit(other)
        with localcontext(_context(200)):
            return Quantity(value=self.value + other.value, unit=self.unit)

    def __sub__(self, other: Quantity) -> Quantity:
        self._same_unit(other)
        with localcontext(_context(200)):
            return Quantity(value=self.value - other.value, unit=self.unit)


# ---------------------------------------------------------------------------
# Facts
# ---------------------------------------------------------------------------


class FrozenDict(dict[str, Any]):
    """A dict that cannot change after construction and hashes by content."""

    def _readonly(self, *args: Any, **kwargs: Any) -> NoReturn:
        raise TypeError("FrozenDict is immutable")

    __setitem__ = __delitem__ = __ior__ = _readonly
    clear = pop = popitem = setdefault = update = _readonly

    def __hash__(self) -> int:  # type: ignore[override]
        return hash(frozenset(self.items()))

    def __reduce__(self) -> tuple[Any, ...]:
        return (FrozenDict, (dict(self),))


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return FrozenDict({k: _freeze(v) for k, v in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_freeze(v) for v in value)
    return value


class Fact(FrozenModel):
    """An immutable, hashable, bitemporal record.

    `payload` is canonicalised on construction (Decimals become text, floats are
    rejected, datetimes become UTC "Z" strings, text becomes NFC) and then deep-frozen:
    mappings become `FrozenDict`, lists become tuples (they dump back as JSON lists).
    """

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

    @field_validator("payload", mode="before")
    @classmethod
    def _canonical_payload(cls, raw: Any) -> Any:
        if not isinstance(raw, Mapping):
            return raw  # pydantic reports the type error
        try:
            return canonical(raw)
        except TypeError as exc:
            raise ValueError(str(exc)) from exc

    @field_validator("payload", mode="after")
    @classmethod
    def _freeze_payload(cls, value: dict[str, Any]) -> dict[str, Any]:
        frozen: dict[str, Any] = _freeze(value)
        return frozen

    @model_validator(mode="after")
    def _valid_interval(self) -> Self:
        if self.valid_to is not None and self.valid_to <= self.valid_from:
            raise ValueError("valid_to must be after valid_from")
        return self


# ---------------------------------------------------------------------------
# Canonical form and digest
# ---------------------------------------------------------------------------


def _decimal_text(d: Decimal) -> str:
    """Plain decimal text without exponent or trailing zeros; "-0" is "0". Context-free."""
    if not d.is_finite():
        raise ValueError("non-finite decimals are not canonicalizable")
    sign, digit_tuple, exponent = d.as_tuple()
    assert isinstance(exponent, int)  # finite
    digits = list(digit_tuple)
    while len(digits) > 1 and digits[-1] == 0:
        digits.pop()
        exponent += 1
    if digits == [0]:
        return "0"
    if abs(exponent) > _MAX_EXPONENT:
        raise ValueError("decimal exponent out of range")
    text = "".join(map(str, digits))
    if exponent >= 0:
        body = text + "0" * exponent
    else:
        places = -exponent
        text = text.rjust(places + 1, "0")
        body = f"{text[:-places]}.{text[-places:]}"
    return "-" + body if sign else body


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
        if "\x00" in value:
            raise ValueError("NUL characters are not allowed in text")  # Postgres cannot store them
        return unicodedata.normalize("NFC", value)
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("refusing to canonicalize a naive datetime")
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for k, v in value.items():
            key = canonical(str(k))
            if key in out:
                raise ValueError(f"mapping keys collide after canonicalisation: {key!r}")
            out[key] = canonical(v)
        return dict(sorted(out.items()))
    if isinstance(value, list | tuple):
        return [canonical(v) for v in value]
    if value is None or isinstance(value, bool | int):
        return value
    raise TypeError(f"cannot canonicalize {type(value).__name__}")


def decision_digest(value: Any) -> str:
    """`sha256:<hex>` over the v2 canonical form, via the shared v1 hashing primitive.

    The digest is sha256 over the canonical JSON *string literal* (compact, sorted keys,
    UTF-8) passed through `hashing.digest`, which JSON-encodes that string once more.
    Serialising first means v1's list-sorting hints (keyed on dict keys such as `slots`)
    can never reorder a v2 list.
    """
    text = json.dumps(
        canonical(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
    return digest(text)
