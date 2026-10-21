"""Pure policy documents: an immutable, digested parameter set plus the closed predicate registry.

A policy holds numbers and names only. Constraint logic lives in code, versioned by
`ENGINE_VERSION`; a conflict rule names one of the registry's predicates and is rejected at
construction when the name is unknown for the document's engine version. Set-like lists are
stored sorted, so the same policy always has the same canonical form and `policy_digest`.
No clock, database or randomness is used here.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Any, Final, Literal

from pydantic import field_validator, model_validator

from flooreplay.decisions.facts import (
    Number,
    PositiveNumber,
    parse_payload,
)
from flooreplay.decisions.types import (
    ConstraintId,
    Fact,
    FactKind,
    FrozenModel,
    ReviewState,
    canonical,
    decision_digest,
)

ENGINE_VERSION: Final = "decision-v1"


class Weekday(StrEnum):
    MON = "MON"
    TUE = "TUE"
    WED = "WED"
    THU = "THU"
    FRI = "FRI"
    SAT = "SAT"
    SUN = "SUN"


_WEEKDAY_ORDER = {day: index for index, day in enumerate(Weekday)}


# ---------------------------------------------------------------------------
# Predicate registry (closed; versioned by ENGINE_VERSION)
# ---------------------------------------------------------------------------

Predicate = Callable[[Fact, Fact], bool]

# A QC claim in one of these states still counts against the lot's stock. `corrected` and
# `rejected` are human outcomes that replace or withdraw the claim.
_CLAIMING_STATES = frozenset({ReviewState.CHECKS_PASSED, ReviewState.CONFIRMED, ReviewState.NEEDS_REVIEW})


def qc_claims_against_lot(lot: Fact, qc: Fact) -> bool:
    """A live QC claim for a positive quantity on a lot the ERP still reports.

    The gate has already joined the pair on entity_key and valid-time overlap; this checks
    kinds, key and content only.
    """
    if lot.kind is not FactKind.FABRIC_LOT or qc.kind is not FactKind.FABRIC_QC:
        return False
    if lot.entity_key != qc.entity_key:
        return False
    parsed: Any = parse_payload(qc)
    return bool(parsed.review_state in _CLAIMING_STATES and parsed.qty.value > 0)


def inbound_eta_disagrees(left: Fact, right: Fact) -> bool:
    """Two inbound facts for one delivery name different ETAs."""
    if left.kind is not FactKind.FABRIC_INBOUND or right.kind is not FactKind.FABRIC_INBOUND:
        return False
    if left.entity_key != right.entity_key:
        return False
    a: Any = parse_payload(left)
    b: Any = parse_payload(right)
    return bool(a.eta != b.eta)


PREDICATES_BY_ENGINE: Final[Mapping[str, Mapping[str, Predicate]]] = {
    ENGINE_VERSION: {
        "qc_claims_against_lot": qc_claims_against_lot,
        "inbound_eta_disagrees": inbound_eta_disagrees,
    }
}

PREDICATES: Final[dict[str, Predicate]] = dict(PREDICATES_BY_ENGINE[ENGINE_VERSION])


# ---------------------------------------------------------------------------
# Document
# ---------------------------------------------------------------------------


def _reject_duplicates(values: tuple[Any, ...], what: str) -> None:
    if len(set(values)) != len(values):
        raise ValueError(f"duplicate entries in {what}")


class FreshnessHours(FrozenModel):
    erp_fabric_stock: int
    sheet_trims_status: int
    shift_capacity: int
    supplier_updates: int
    notes: int
    order_requests: int

    @field_validator("*")
    @classmethod
    def _non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("freshness hours must be >= 0")
        return v


class FabricParams(FrozenModel):
    wastage_pct: Number
    inbound_buffer_days: int
    safety_floor_pct: Number

    @field_validator("inbound_buffer_days")
    @classmethod
    def _days(cls, v: int) -> int:
        if v < 0:
            raise ValueError("must be >= 0")
        return v


class TrimParams(FrozenModel):
    wastage_pct: Number
    buffer_days: int

    @field_validator("buffer_days")
    @classmethod
    def _days(cls, v: int) -> int:
        if v < 0:
            raise ValueError("must be >= 0")
        return v


class CapacityParams(FrozenModel):
    eligible_lines: tuple[str, ...]
    default_efficiency_pct: PositiveNumber
    cut_to_ship_days: int
    finishing_days: int
    ot_cap_hours_per_line_day: int
    # Working days for CAPACITY are every date that is neither a non-working weekday nor a
    # holiday. Owner-approved additions to the PLAN (see docs/v2/changelog.md, 2026-10-21).
    non_working_weekdays: tuple[Weekday, ...] = (Weekday.SUN,)
    holidays: tuple[date, ...] = ()

    @field_validator("cut_to_ship_days", "finishing_days", "ot_cap_hours_per_line_day")
    @classmethod
    def _non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("must be >= 0")
        return v

    @field_validator("eligible_lines")
    @classmethod
    def _lines(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        if any(not line for line in v):
            raise ValueError("line ids must be non-empty")
        _reject_duplicates(v, "eligible_lines")
        return tuple(sorted(v))

    @field_validator("non_working_weekdays")
    @classmethod
    def _weekdays(cls, v: tuple[Weekday, ...]) -> tuple[Weekday, ...]:
        _reject_duplicates(v, "non_working_weekdays")
        return tuple(sorted(v, key=_WEEKDAY_ORDER.__getitem__))

    @field_validator("holidays")
    @classmethod
    def _holidays(cls, v: tuple[date, ...]) -> tuple[date, ...]:
        _reject_duplicates(v, "holidays")
        return tuple(sorted(v))


class ApprovalParams(FrozenModel):
    max_value_inr: Number
    max_qty_pcs: int

    @field_validator("max_qty_pcs")
    @classmethod
    def _qty(cls, v: int) -> int:
        if v < 0:
            raise ValueError("must be >= 0")
        return v


class ConflictRule(FrozenModel):
    id: str
    left_kind: FactKind
    right_kind: FactKind
    join: Literal["entity_key"]
    valid_time: Literal["overlap"]
    predicate: str

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not v:
            raise ValueError("rule id must be non-empty")
        return v


class PolicyDocument(FrozenModel):
    """The whole policy. Its `policy_digest` identifies it; it is never edited in place."""

    label: str
    engine_version: str
    freshness_hours: FreshnessHours
    fabric: FabricParams
    trims: TrimParams
    capacity: CapacityParams
    approval: ApprovalParams
    conflict_rules: tuple[ConflictRule, ...]
    enabled_constraints: tuple[ConstraintId, ...]

    @field_validator("conflict_rules")
    @classmethod
    def _rules(cls, v: tuple[ConflictRule, ...]) -> tuple[ConflictRule, ...]:
        _reject_duplicates(tuple(r.id for r in v), "conflict_rules ids")
        return tuple(sorted(v, key=lambda r: r.id))

    @field_validator("enabled_constraints")
    @classmethod
    def _constraints(cls, v: tuple[ConstraintId, ...]) -> tuple[ConstraintId, ...]:
        _reject_duplicates(v, "enabled_constraints")
        return tuple(sorted(v, key=lambda c: c.value))

    @model_validator(mode="after")
    def _predicates_exist(self) -> PolicyDocument:
        registry = PREDICATES_BY_ENGINE.get(self.engine_version)
        if registry is None:
            raise ValueError(f"unknown engine_version {self.engine_version!r}")
        for rule in self.conflict_rules:
            if rule.predicate not in registry:
                raise ValueError(
                    f"rule {rule.id!r}: unknown predicate {rule.predicate!r} "
                    f"for engine {self.engine_version}"
                )
        return self

    def predicate_for(self, rule: ConflictRule) -> Predicate:
        return PREDICATES_BY_ENGINE[self.engine_version][rule.predicate]


def _body(doc: PolicyDocument) -> dict[str, Any]:
    """The canonical dict of a policy, with every set-like list sorted explicitly."""
    body: dict[str, Any] = canonical(doc.model_dump(mode="python"))
    capacity = body["capacity"]
    capacity["eligible_lines"] = sorted(capacity["eligible_lines"])
    capacity["holidays"] = sorted(capacity["holidays"])
    capacity["non_working_weekdays"] = sorted(
        capacity["non_working_weekdays"], key=lambda d: _WEEKDAY_ORDER[Weekday(d)]
    )
    body["enabled_constraints"] = sorted(body["enabled_constraints"])
    body["conflict_rules"] = sorted(body["conflict_rules"], key=lambda r: r["id"])
    return body


def policy_digest(doc: PolicyDocument) -> str:
    """`sha256:<hex>` of the canonical policy document."""
    return decision_digest(_body(doc))


# ---------------------------------------------------------------------------
# Calendar helpers shared by the gate and CAPACITY
# ---------------------------------------------------------------------------


def cut_date(capacity: CapacityParams, ship_date: date) -> date:
    """The cut date: `ship_date - cut_to_ship_days`."""
    return ship_date - timedelta(days=capacity.cut_to_ship_days)


def sewing_days(capacity: CapacityParams, ship_date: date) -> list[date]:
    """Working days in [cut_date + 1, ship_date - finishing_days], inclusive, ascending.

    A working day is neither a non-working weekday nor a holiday.
    """
    first = cut_date(capacity, ship_date) + timedelta(days=1)
    last = ship_date - timedelta(days=capacity.finishing_days)
    off_weekdays = {day.value for day in capacity.non_working_weekdays}
    holidays = set(capacity.holidays)
    days: list[date] = []
    day = first
    while day <= last:
        if day not in holidays and list(Weekday)[day.weekday()].value not in off_weekdays:
            days.append(day)
        day += timedelta(days=1)
    return days


# ---------------------------------------------------------------------------
# Parameter diff
# ---------------------------------------------------------------------------


def _leaves(prefix: str, value: Any, out: dict[str, Any]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            _leaves(f"{prefix}.{key}" if prefix else str(key), item, out)
    else:
        out[prefix] = value  # scalars and whole lists


def _flatten(doc: PolicyDocument) -> dict[str, Any]:
    body = _body(doc)
    rules = {rule["id"]: rule for rule in body.pop("conflict_rules")}
    leaves: dict[str, Any] = {}
    _leaves("", body, leaves)
    return {**leaves, **{f"conflict_rules[{rid}]": rule for rid, rule in rules.items()}}


def parameter_diff(before: PolicyDocument, after: PolicyDocument) -> list[dict[str, Any]]:
    """Changed leaf parameters as `{path, before, after}`, sorted by path.

    Set-like lists (eligible_lines, holidays, non_working_weekdays, enabled_constraints) are
    compared and reported as wholes. Conflict rules are matched by id: a changed rule reports
    each changed field as `conflict_rules[<id>].<field>`; an added or removed rule reports the
    whole rule against None.
    """
    a, b = _flatten(before), _flatten(after)
    entries: list[dict[str, Any]] = []
    for path in sorted(a.keys() | b.keys()):
        old, new = a.get(path), b.get(path)
        if path in a and path in b and old == new:
            continue
        if old is not None and new is not None and path.startswith("conflict_rules["):
            for field_name in sorted(old.keys() | new.keys()):
                if old.get(field_name) != new.get(field_name):
                    entries.append(
                        {
                            "path": f"{path}.{field_name}",
                            "before": old.get(field_name),
                            "after": new.get(field_name),
                        }
                    )
            continue
        entries.append({"path": path, "before": old, "after": new})
    return sorted(entries, key=lambda e: e["path"])


# ---------------------------------------------------------------------------
# Defaults (docs/v2/discovery.md, "Draft constraint list"; unvalidated until the freeze)
# ---------------------------------------------------------------------------

DEFAULT_POLICY_V1: Final = PolicyDocument.model_validate(
    {
        "label": "Tiruppur default v1",
        "engine_version": ENGINE_VERSION,
        "freshness_hours": {
            "erp_fabric_stock": 24,
            "sheet_trims_status": 48,
            "shift_capacity": 24,
            "supplier_updates": 72,
            "notes": 24,
            "order_requests": 168,
        },
        "fabric": {
            "wastage_pct": Decimal("0.05"),
            "inbound_buffer_days": 2,
            "safety_floor_pct": Decimal("0.05"),
        },
        "trims": {"wastage_pct": Decimal("0.03"), "buffer_days": 2},
        "capacity": {
            "eligible_lines": ["L1", "L2", "L3", "L4"],
            "default_efficiency_pct": Decimal("0.55"),
            "cut_to_ship_days": 21,
            "finishing_days": 4,
            "ot_cap_hours_per_line_day": 2,
            "non_working_weekdays": ["SUN"],
            "holidays": [],
        },
        "approval": {"max_value_inr": Decimal("5000000"), "max_qty_pcs": 20000},
        "conflict_rules": [
            {
                "id": "qc_claims_against_lot",
                "left_kind": "fabric_lot",
                "right_kind": "fabric_qc",
                "join": "entity_key",
                "valid_time": "overlap",
                "predicate": "qc_claims_against_lot",
            },
            {
                "id": "inbound_eta_disagrees",
                "left_kind": "fabric_inbound",
                "right_kind": "fabric_inbound",
                "join": "entity_key",
                "valid_time": "overlap",
                "predicate": "inbound_eta_disagrees",
            },
        ],
        "enabled_constraints": [c.value for c in ConstraintId],
    }
)
