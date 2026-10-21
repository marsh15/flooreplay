"""Atomic shared allowance and execution slots; uncertain calls stay charged."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from math import isfinite
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from .config import settings
from .errors import ServiceError
from .paid_models import SpendEntry, SpendingAllocation, now

PRICE_TABLE = {"version": "openai-2026-09-30", "effective_date": "2026-09-30", "generation_input_usd_per_million": 0.40, "generation_output_usd_per_million": 1.60, "embedding_usd_per_million": 0.02}
# Per-model price table (USD per million tokens), added for the v2 provider Protocol.
# Sources (official pricing pages, read 2026-10-20):
#   Anthropic: https://platform.claude.com/docs/en/about-claude/pricing
#   OpenAI:    https://platform.openai.com/docs/pricing
# PRICE_TABLE above is the persisted v1 ledger snapshot and stays unchanged; this table
# only prices calls that name a model. Bump PRICE_TABLE_VERSION and the effective date
# whenever any row changes.
PRICE_TABLE_VERSION = "models-2026-10-20"
PRICE_TABLE_EFFECTIVE_DATE = "2026-10-20"


@dataclass(frozen=True)
class ModelPrice:
    input_usd_per_million: float
    output_usd_per_million: float
    # Claude Haiku 5.5 is billed at a higher rate card when the prompt exceeds 100K tokens.
    long_prompt_threshold: int | None = None
    long_input_usd_per_million: float | None = None
    long_output_usd_per_million: float | None = None


MODEL_PRICES: dict[str, ModelPrice] = {
    "gpt-4.1-mini-2025-04-14": ModelPrice(0.40, 1.60),
    "text-embedding-3-small": ModelPrice(0.02, 0.0),
    "claude-haiku-5-5": ModelPrice(0.10, 0.50, 100_000, 0.50, 2.50),
    "claude-sonnet-5-5": ModelPrice(2.00, 10.00),
}


class UnknownModelPriceError(ValueError):
    """A model has no row in the price table; pricing it as zero would hide spend."""


def model_price(model: str) -> ModelPrice:
    try:
        return MODEL_PRICES[model]
    except KeyError:
        raise UnknownModelPriceError(f"No price table entry for model {model!r}; add one before using it") from None


ALLOCATIONS = {"development": 100.0, "evaluation": 200.0, "reviewer": 100.0, "buffer": 100.0}


def lock(session: Session) -> None:
    session.execute(select(func.pg_advisory_xact_lock(947362)))


def usage_view(session: Session, *, include_entries: bool = True) -> dict[str, Any]:
    allocations = {row.purpose: row.ceiling_inr for row in session.scalars(select(SpendingAllocation))} or ALLOCATIONS
    committed = case((SpendEntry.status == "SETTLED", SpendEntry.charged_inr), else_=SpendEntry.reserved_inr)
    used = dict.fromkeys(ALLOCATIONS, 0.0)
    for purpose, total in session.execute(select(SpendEntry.purpose, func.sum(committed)).group_by(SpendEntry.purpose)):
        used[purpose] = float(total)
    active = session.execute(select(func.count()).select_from(SpendEntry).where(SpendEntry.status == "RESERVED", SpendEntry.expires_at > now())).scalar_one()
    entries = session.scalars(select(SpendEntry).order_by(SpendEntry.created_at.desc(), SpendEntry.id).limit(100)).all() if include_entries else []
    return {"total_ceiling_inr": 500, "allocations_inr": allocations, "committed_inr": sum(used.values()), "available_inr": max(0, 500 - sum(used.values())), "purpose_available_inr": {p: max(0, cap - used[p]) for p, cap in allocations.items()}, "active_operations": active, "price_table": PRICE_TABLE, "entries": [{"id": e.id, "purpose": e.purpose, "operation": e.operation, "status": e.status, "reserved_inr": e.reserved_inr, "charged_inr": e.charged_inr, "charged_usd": e.charged_usd, "details": e.details} for e in entries]}


def reserve(session: Session, user_id: str, purpose: str, operation: str, maximum_usd: float) -> SpendEntry:
    if purpose not in ALLOCATIONS or not isfinite(maximum_usd) or maximum_usd < 0:
        raise ServiceError("INVALID_ALLOWANCE", "Unknown spending purpose", 422)
    lock(session)
    # Expiration releases capacity only. It never assumes an interrupted provider call was free.
    for entry in session.scalars(select(SpendEntry).where(SpendEntry.status == "RESERVED", SpendEntry.expires_at <= now())):
        entry.status = "UNCERTAIN"
    session.flush()
    usage = usage_view(session, include_entries=False)
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


def cost(input_tokens: int, output_tokens: int = 0, *, embedding: bool = False, model: str | None = None) -> float:
    if model is None:
        return (input_tokens * (0.02 if embedding else 0.40) + output_tokens * 1.60) / 1_000_000
    if embedding:
        raise ValueError("Name the embedding model instead of passing embedding=True with model=")
    price = model_price(model)
    rate_in, rate_out = price.input_usd_per_million, price.output_usd_per_million
    if price.long_prompt_threshold is not None and input_tokens > price.long_prompt_threshold:
        assert price.long_input_usd_per_million is not None and price.long_output_usd_per_million is not None
        rate_in, rate_out = price.long_input_usd_per_million, price.long_output_usd_per_million
    return (input_tokens * rate_in + output_tokens * rate_out) / 1_000_000


def move_allowance(session: Session, source: str, destination: str, amount_inr: float) -> dict[str, Any]:
    if source not in ALLOCATIONS or destination not in ALLOCATIONS or source == destination or not 0 < amount_inr <= 500:
        raise ServiceError("INVALID_ALLOWANCE", "Invalid allocation transfer", 422)
    lock(session)
    for purpose, ceiling in ALLOCATIONS.items():
        if session.get(SpendingAllocation, purpose) is None:
            session.add(SpendingAllocation(purpose=purpose, ceiling_inr=ceiling))
    session.flush()
    usage = usage_view(session, include_entries=False)
    if amount_inr > usage["purpose_available_inr"][source]:
        raise ServiceError("ALLOWANCE_COMMITTED", "Source allowance already reserved or spent", 409)
    origin = session.get(SpendingAllocation, source)
    target = session.get(SpendingAllocation, destination)
    assert origin is not None and target is not None
    origin.ceiling_inr -= amount_inr
    target.ceiling_inr += amount_inr
    session.flush()
    return usage_view(session)
