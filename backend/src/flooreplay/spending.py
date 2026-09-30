"""Atomic shared allowance and execution slots; uncertain calls stay charged."""
from __future__ import annotations

from datetime import timedelta
from math import isfinite
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import settings
from .paid_models import SpendEntry, SpendingAllocation, now
from .service import ServiceError

PRICE_TABLE = {"version": "openai-2026-09-30", "effective_date": "2026-09-30", "generation_input_usd_per_million": 0.40, "generation_output_usd_per_million": 1.60, "embedding_usd_per_million": 0.02}
ALLOCATIONS = {"development": 100.0, "evaluation": 200.0, "reviewer": 100.0, "buffer": 100.0}


def lock(session: Session) -> None:
    session.execute(select(func.pg_advisory_xact_lock(947362)))


def usage_view(session: Session) -> dict[str, Any]:
    allocations = {row.purpose: row.ceiling_inr for row in session.scalars(select(SpendingAllocation))} or ALLOCATIONS
    entries = session.scalars(select(SpendEntry).order_by(SpendEntry.created_at.desc())).all()
    used = {purpose: sum(e.charged_inr if e.status == "SETTLED" else e.reserved_inr for e in entries if e.purpose == purpose) for purpose in ALLOCATIONS}
    return {"total_ceiling_inr": 500, "allocations_inr": allocations, "committed_inr": sum(used.values()), "available_inr": max(0, 500 - sum(used.values())), "purpose_available_inr": {p: max(0, cap - used[p]) for p, cap in allocations.items()}, "active_operations": sum(e.status == "RESERVED" and e.expires_at > now() for e in entries), "price_table": PRICE_TABLE, "entries": [{"id": e.id, "purpose": e.purpose, "operation": e.operation, "status": e.status, "reserved_inr": e.reserved_inr, "charged_inr": e.charged_inr, "charged_usd": e.charged_usd, "details": e.details} for e in entries[:100]]}


def reserve(session: Session, user_id: str, purpose: str, operation: str, maximum_usd: float) -> SpendEntry:
    if purpose not in ALLOCATIONS or not isfinite(maximum_usd) or maximum_usd < 0:
        raise ServiceError("INVALID_ALLOWANCE", "Unknown spending purpose", 422)
    lock(session)
    # Expiration releases capacity only. It never assumes an interrupted provider call was free.
    for entry in session.scalars(select(SpendEntry).where(SpendEntry.status == "RESERVED", SpendEntry.expires_at <= now())):
        entry.status = "UNCERTAIN"
    session.flush()
    usage = usage_view(session)
    amount = maximum_usd * settings.openai_inr_per_usd
    if usage["active_operations"] >= 2:
        raise ServiceError("EXECUTION_CAPACITY_FULL", "Two provider operations are already active", 429)
    if amount > usage["available_inr"] or amount > usage["purpose_available_inr"][purpose]:
        raise ServiceError("ALLOWANCE_EXHAUSTED", "Insufficient reserved spending allowance", 402)
    entry = SpendEntry(user_id=user_id, purpose=purpose, operation=operation, reserved_inr=amount, price_table={**PRICE_TABLE, "inr_per_usd": settings.openai_inr_per_usd}, expires_at=now() + timedelta(seconds=65))
    session.add(entry)
    session.flush()
    return entry


def settle(session: Session, entry_id: str, usd: float, details: dict[str, Any], *, uncertain: bool = False) -> None:
    lock(session)
    entry = session.get(SpendEntry, entry_id)
    if entry is None:
        raise RuntimeError("Reservation missing")
    entry.status = "UNCERTAIN" if uncertain else "SETTLED"
    entry.charged_usd = usd
    entry.charged_inr = usd * entry.price_table["inr_per_usd"]
    entry.details = details


def cost(input_tokens: int, output_tokens: int = 0, *, embedding: bool = False) -> float:
    return (input_tokens * (0.02 if embedding else 0.40) + output_tokens * 1.60) / 1_000_000


def move_allowance(session: Session, source: str, destination: str, amount_inr: float) -> dict[str, Any]:
    if source not in ALLOCATIONS or destination not in ALLOCATIONS or source == destination or not 0 < amount_inr <= 500:
        raise ServiceError("INVALID_ALLOWANCE", "Invalid allocation transfer", 422)
    lock(session)
    for purpose, ceiling in ALLOCATIONS.items():
        if session.get(SpendingAllocation, purpose) is None:
            session.add(SpendingAllocation(purpose=purpose, ceiling_inr=ceiling))
    session.flush()
    usage = usage_view(session)
    if amount_inr > usage["purpose_available_inr"][source]:
        raise ServiceError("ALLOWANCE_COMMITTED", "Source allowance already reserved or spent", 409)
    origin = session.get(SpendingAllocation, source)
    target = session.get(SpendingAllocation, destination)
    assert origin is not None and target is not None
    origin.ceiling_inr -= amount_inr
    target.ceiling_inr += amount_inr
    session.flush()
    return usage_view(session)
