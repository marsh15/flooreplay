"""Note extraction orchestration (FloorReplay 2.0, task T19).

Three short transactions around one provider call, mirroring v1 `ai_runs.run_ai`:

1. Reserve (own transaction, committed before the call): idempotency and retry checks, then
   `spending.reserve` under `spending.lock`. A refused reservation raises `BUDGET_REFUSED`.
2. Call (no transaction and no lock held): `provider.extract(..., max_tokens=...)`. A provider
   exception is recorded as a FAILED attempt. A BaseException (interrupt, exit) propagates and
   writes nothing, so the committed reservation stays and is charged as uncertain once it expires.
3. Settle and persist (own transaction): settle is clamped to the reservation, then the result
   is written inside a savepoint. If that write fails, the savepoint is rolled back, the spend
   stays, and a minimal FAILED row (error class only) is stored.

Rules:
- A COMPLETED row for the key is returned with no provider call and no spend.
- A FAILED row is an attempt. Only a provider exception may be retried, up to ATTEMPT_LIMIT
  attempts in total. INVALID_OUTPUT and STORE_FAILED are final and are never re-billed.
- Only the required fields that passed the checks become one `fabric_qc` fact. Its id derives
  from the note digest, so a retry or another model never adds the quantity twice.

Concurrency. Callers for one key are serialised by a session-level advisory lock on a
dedicated connection, `pg_try_advisory_lock(EXTRACTION_LOCK_CLASSID, hashtext(key))`. That is
the two-int form, a namespace separate from the single-bigint `spending` lock. A process-wide
semaphore caps how many extractions may wait for or hold a key lock, at half the pool, so
waiters cannot exhaust the pool. A caller that cannot get a slot within KEY_SLOT_WAIT_SECONDS,
or a key lock within KEY_LOCK_WAIT_SECONDS, gets `EXTRACTION_BUSY` (429) with no call and no
spend. Different keys proceed in parallel up to the slot cap.

Attempts. Every provider call that started is recorded, including interrupts: a BaseException
from the provider is recorded as a PROVIDER_ERROR attempt and then re-raised unchanged.

Known limits (documented, not fixed): the v1 execution-capacity cap loosens once a reservation
passes its 65 s expiry while its call is still running (the money ceiling still holds); the
settled charge is clamped to the reservation, with the real figure kept in the details.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Collection, Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, NoReturn

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from flooreplay import spending
from flooreplay.db import engine, session_scope
from flooreplay.decisions import service
from flooreplay.decisions.extraction.checks import ChecksOutcome, FieldStatus, run_checks
from flooreplay.decisions.extraction.provider import GenerationProvider, ProviderResult
from flooreplay.decisions.extraction.schema import (
    REQUIRED_FIELDS,
    SCHEMA_VERSION,
    NoteSignal,
    SignalValidationError,
    normalize_note,
    note_digest,
    note_signal_json_schema,
    validate_signal_payload,
)
from flooreplay.decisions.models import FactRow, NoteExtraction, ProviderCall
from flooreplay.decisions.types import Fact, FactKind, SourceProfile
from flooreplay.errors import ServiceError
from flooreplay.spending import UnknownModelPriceError, model_price

STATUS_COMPLETED = "COMPLETED"
STATUS_FAILED = "FAILED"
# Reserved for the status column. A refusal raises instead of storing, so the key stays free.
STATUS_BUDGET_REFUSED = "BUDGET_REFUSED"

FAILURE_PROVIDER = "PROVIDER_ERROR"
FAILURE_INVALID = "INVALID_OUTPUT"
FAILURE_STORE = "STORE_FAILED"

SPEND_PURPOSE = "evaluation"
SPEND_OPERATION = "note_extraction"
# Reservation sizing: UTF-8 bytes bound the input tokens from above; the output cap is also the
# provider's max_tokens, so a call cannot emit more billable output than the reservation covers.
PROMPT_OVERHEAD_TOKENS = 2_000
MAX_OUTPUT_TOKENS = 1_500
ATTEMPT_LIMIT = 3
QC_ORIGIN = "notes"
QC_REVIEW_STATE = "checks_passed"

MAX_WORKSPACE_ID = 64  # NoteExtraction.workspace_id
MAX_PROMPT_VERSION = 32  # NoteExtraction.prompt_version
MAX_USER_ID = 64  # SpendEntry.user_id
MAX_NOTE_ID = 200
INT4_MAX = 2**31 - 1  # token counts are stored as Integer


@dataclass(frozen=True)
class ReviewField:
    """A field the checks did not pass: it stays out of facts and goes to the review queue."""

    field: str
    status: str  # "failed" (claimed and rejected) or "missing" (required and absent)
    codes: tuple[str, ...]


@dataclass(frozen=True)
class ExtractionResult:
    extraction_id: str
    status: str
    model: str
    prompt_version: str
    replayed: bool  # True when a stored row answered; no provider call was made
    provider_called: bool
    language: str | None
    fact_ids: tuple[str, ...]
    review_fields: tuple[ReviewField, ...]
    error_class: str | None
    failure_kind: str | None
    attempts: int


def _invalid(message: str) -> ServiceError:
    return ServiceError("INVALID_EXTRACTION", message, 422)


def _validate_inputs(
    workspace_id: str, user_id: str, note_id: str, note_text: str, prompt_version: str
) -> None:
    if not workspace_id.strip() or len(workspace_id) > MAX_WORKSPACE_ID or "\x00" in workspace_id:
        raise _invalid(f"workspace_id must be 1-{MAX_WORKSPACE_ID} characters without NUL")
    if not user_id.strip() or len(user_id) > MAX_USER_ID or "\x00" in user_id:
        raise _invalid(f"user_id must be 1-{MAX_USER_ID} characters without NUL")
    if not note_id.strip() or len(note_id) > MAX_NOTE_ID or "\x00" in note_id:
        raise _invalid(f"note_id must be 1-{MAX_NOTE_ID} characters without NUL")
    if not prompt_version.strip() or len(prompt_version) > MAX_PROMPT_VERSION or "\x00" in prompt_version:
        raise _invalid(f"prompt_version must be 1-{MAX_PROMPT_VERSION} characters without NUL")
    if "\x00" in note_text:
        raise _invalid("note text must not contain NUL")


def _usage_ok(value: object) -> bool:
    """Token counts must be real non-negative integers (bool is an int in Python, so refuse it)."""
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


EXTRACTION_LOCK_CLASSID = 1_746_023  # int4; the two-int advisory namespace used only here
KEY_LOCK_WAIT_SECONDS = 25.0
KEY_SLOT_WAIT_SECONDS = 2.0


def _key_slot_count() -> int:
    """Half the pool (size + overflow), floor 1, so at least half stays free for other work."""
    pool = engine.pool
    size_fn = getattr(pool, "size", None)
    size = int(size_fn()) if callable(size_fn) else 0
    overflow = int(getattr(pool, "_max_overflow", 0) or 0)
    return max(1, (size + overflow) // 2)


_KEY_SLOTS = threading.BoundedSemaphore(_key_slot_count())


@contextmanager
def _key_lock(workspace_id: str, digest: str, model: str, prompt_version: str) -> Iterator[None]:
    """Hold the key's advisory lock on a dedicated connection for the whole span.

    Polls `pg_try_advisory_lock` with short pauses up to KEY_LOCK_WAIT_SECONDS, then raises
    EXTRACTION_BUSY. Released in `finally`; if the release fails, the connection is invalidated,
    which drops the lock with it, so a pooled connection never keeps it.
    """
    key = "|".join((workspace_id, digest, model, prompt_version, SCHEMA_VERSION))
    params = {"classid": EXTRACTION_LOCK_CLASSID, "key": key}
    connection = engine.connect()
    try:
        deadline = time.monotonic() + KEY_LOCK_WAIT_SECONDS
        pause = 0.02
        while True:
            acquired: bool = connection.execute(
                text("SELECT pg_try_advisory_lock(CAST(:classid AS integer), hashtext(:key))"), params
            ).scalar_one()
            connection.commit()
            if acquired:
                break
            if time.monotonic() >= deadline:
                raise ServiceError(
                    "EXTRACTION_BUSY", "Another extraction for this note is still running; try again", 429
                )
            time.sleep(pause)
            pause = min(pause * 2, 0.25)
    except BaseException:
        connection.invalidate()
        connection.close()
        raise
    try:
        yield
    finally:
        try:
            connection.execute(
                text("SELECT pg_advisory_unlock(CAST(:classid AS integer), hashtext(:key))"), params
            )
            connection.commit()
        except BaseException:
            connection.invalidate()
            raise
        finally:
            connection.close()


def _strip_nul(value: Any) -> tuple[Any, int]:
    """Drop U+0000 from every string, dict key and nested value. Returns (clean, count removed)."""
    if isinstance(value, str):
        return value.replace("\x00", ""), value.count("\x00")
    if isinstance(value, dict):
        out: dict[Any, Any] = {}
        removed = 0
        for key, item in value.items():
            clean_key, nk = _strip_nul(key)
            clean_item, ni = _strip_nul(item)
            out[clean_key] = clean_item
            removed += nk + ni
        return out, removed
    if isinstance(value, list):
        items = [_strip_nul(item) for item in value]
        return [clean for clean, _ in items], sum(n for _, n in items)
    return value, 0


def _review_fields(checks: dict[str, Any]) -> tuple[ReviewField, ...]:
    out: list[ReviewField] = []
    for name in checks.get("failed_fields", []):
        results = [r for r in checks["results"] if r["field"] == name and r["code"] != "ok"]
        status = "failed" if any(r["status"] == "claimed_and_failed" for r in results) else "missing"
        out.append(
            ReviewField(field=name, status=status, codes=tuple(sorted({r["code"] for r in results})))
        )
    return tuple(out)


def _result(
    row: NoteExtraction,
    attempts: int,
    *,
    replayed: bool,
    provider_called: bool,
    fact_ids: tuple[str, ...] = (),
) -> ExtractionResult:
    return ExtractionResult(
        extraction_id=row.id,
        status=row.status,
        model=row.model,
        prompt_version=row.prompt_version,
        replayed=replayed,
        provider_called=provider_called,
        language=row.language,
        fact_ids=fact_ids,
        review_fields=_review_fields(row.checks) if row.checks is not None else (),
        error_class=row.error_class,
        failure_kind=row.failure_kind,
        attempts=attempts,
    )


def _key_filter(workspace_id: str, digest: str, model: str, prompt_version: str) -> list[Any]:
    return [
        NoteExtraction.workspace_id == workspace_id,
        NoteExtraction.note_digest == digest,
        NoteExtraction.model == model,
        NoteExtraction.prompt_version == prompt_version,
        NoteExtraction.schema_version == SCHEMA_VERSION,
    ]


def _store(
    session: Session,
    *,
    workspace_id: str,
    user_id: str,
    note_id: str,
    digest: str,
    model: str,
    prompt_version: str,
    status: str,
    failure_kind: str | None,
    spend_entry_id: str,
    cost_usd: float,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    raw: dict[str, Any] | None = None,
    signal: dict[str, Any] | None = None,
    checks: dict[str, Any] | None = None,
    language: str | None = None,
    error_class: str | None = None,
) -> NoteExtraction:
    field_status = (
        {f["field"]: f["status"] for f in checks["fields"]} if checks is not None else None
    )
    row = NoteExtraction(
        workspace_id=workspace_id,
        note_id=note_id,
        note_digest=digest,
        model=model,
        prompt_version=prompt_version,
        schema_version=SCHEMA_VERSION,
        status=status,
        failure_kind=failure_kind,
        language=language,
        raw_output=raw,
        signal=signal,
        checks=checks,
        field_status=field_status,
        error_class=error_class,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
        spend_entry_id=spend_entry_id,
        created_by=user_id,
    )
    session.add(row)
    session.flush()
    return row


def _record_call(
    session: Session,
    row: NoteExtraction,
    provider: GenerationProvider,
    *,
    outcome: str,
    error_class: str | None,
    input_tokens: int | None,
    output_tokens: int | None,
    cost_usd: float,
    spend_entry_id: str,
) -> None:
    session.add(
        ProviderCall(
            workspace_id=row.workspace_id,
            extraction_id=row.id,
            note_digest=row.note_digest,
            provider_name=provider.name,
            model=row.model,
            prompt_version=row.prompt_version,
            schema_version=row.schema_version,
            outcome=outcome,
            error_class=error_class,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            spend_entry_id=spend_entry_id,
        )
    )
    session.flush()


def _qc_fact(
    session: Session, workspace_id: str, checks: ChecksOutcome, extraction_id: str, digest: str
) -> Fact | None:
    """One fabric_qc fact from the four required fields, all of which must have passed."""
    by_field = {f.field: f for f in checks.fields}
    if any(by_field[name].status is not FieldStatus.PASSED for name in REQUIRED_FIELDS):
        return None
    lot, issue, qty, unit = (by_field[name].value for name in REQUIRED_FIELDS)
    if lot is None or issue is None or qty is None or unit is None:  # pragma: no cover
        return None
    fact_id = f"note-qc:{digest.removeprefix('sha256:')[:24]}"
    # Same note text, same fact: a retry or a second model must not add the quantity again.
    if session.get(FactRow, (workspace_id, fact_id)) is not None:
        return None
    now = service.db_now(session)
    return Fact(
        id=fact_id,
        kind=FactKind.FABRIC_QC,
        entity_key=f"lot:{lot}",
        payload={
            "qty": {"value": Decimal(qty), "unit": unit},
            "issue": issue,
            "review_state": QC_REVIEW_STATE,
            "origin": QC_ORIGIN,
            "extraction_id": extraction_id,
        },
        valid_from=now,
        valid_to=None,
        known_at=now,
        supersedes_id=None,
        source=SourceProfile.NOTES,
        artifact_id=None,
    )


def _persist_checked(
    session: Session,
    *,
    workspace_id: str,
    user_id: str,
    note_id: str,
    digest: str,
    model: str,
    prompt_version: str,
    provider: GenerationProvider,
    entry_id: str,
    charged_usd: float,
    input_tokens: int,
    output_tokens: int,
    raw: dict[str, Any],
    nfc: str,
    known_lots: Collection[str],
) -> tuple[NoteExtraction, tuple[str, ...]]:
    """Validate, check and store one provider payload. Raises if the store fails."""
    try:
        signal: NoteSignal = validate_signal_payload(raw)
    except SignalValidationError:
        row = _store(
            session, workspace_id=workspace_id, user_id=user_id, note_id=note_id, digest=digest,
            model=model, prompt_version=prompt_version, status=STATUS_FAILED,
            failure_kind=FAILURE_INVALID, spend_entry_id=entry_id, cost_usd=charged_usd,
            input_tokens=input_tokens, output_tokens=output_tokens, raw=raw,
            error_class="SignalValidationError",
        )
        _record_call(
            session, row, provider, outcome="INVALID_OUTPUT", error_class="SignalValidationError",
            input_tokens=input_tokens, output_tokens=output_tokens, cost_usd=charged_usd,
            spend_entry_id=entry_id,
        )
        return row, ()

    checks = run_checks(nfc, signal, known_lots)
    row = _store(
        session, workspace_id=workspace_id, user_id=user_id, note_id=note_id, digest=digest,
        model=model, prompt_version=prompt_version, status=STATUS_COMPLETED, failure_kind=None,
        spend_entry_id=entry_id, cost_usd=charged_usd, input_tokens=input_tokens,
        output_tokens=output_tokens, raw=raw, signal=signal.model_dump(mode="json"),
        checks=checks.canonical_payload(), language=signal.language,
    )
    _record_call(
        session, row, provider, outcome="OK", error_class=None, input_tokens=input_tokens,
        output_tokens=output_tokens, cost_usd=charged_usd, spend_entry_id=entry_id,
    )
    fact_ids: tuple[str, ...] = ()
    qc = _qc_fact(session, workspace_id, checks, row.id, digest)
    if qc is not None:
        service.append_fact(session, qc, workspace_id=workspace_id)
        fact_ids = (qc.id,)
    return row, fact_ids


def _write_failure(
    *,
    workspace_id: str,
    user_id: str,
    note_id: str,
    digest: str,
    model: str,
    prompt_version: str,
    provider: GenerationProvider,
    entry_id: str,
    maximum_usd: float,
    failure_kind: str,
    call_outcome: str,
    error_class: str,
    attempts: int,
) -> ExtractionResult:
    """One fresh transaction: settle uncertain at the maximum, store the FAILED row, record the call."""
    with session_scope() as session:
        spending.settle(
            session, entry_id, maximum_usd,
            {"error_class": error_class, "failure_kind": failure_kind}, uncertain=True,
        )
        row = _store(
            session, workspace_id=workspace_id, user_id=user_id, note_id=note_id, digest=digest,
            model=model, prompt_version=prompt_version, status=STATUS_FAILED,
            failure_kind=failure_kind, spend_entry_id=entry_id, cost_usd=maximum_usd,
            error_class=error_class,
        )
        _record_call(
            session, row, provider, outcome=call_outcome, error_class=error_class,
            input_tokens=None, output_tokens=None, cost_usd=maximum_usd, spend_entry_id=entry_id,
        )
        return _result(row, attempts, replayed=False, provider_called=True)


def _record_after_provider_failure(
    *,
    workspace_id: str,
    user_id: str,
    note_id: str,
    digest: str,
    model: str,
    prompt_version: str,
    provider: GenerationProvider,
    entry_id: str,
    maximum_usd: float,
    failure_kind: str,
    call_outcome: str,
    error_class: str,
    attempts: int,
    code: str,
    message: str,
    http_status: int,
    cause: BaseException,
) -> NoReturn:
    """Guarded fallback: a last-resort write in a fresh transaction, then always a ServiceError.

    If that write fails too, the error is EXTRACTION_RECORD_FAILED and the spend is held as
    uncertain at the maximum (or stays RESERVED until its expiry if even the settle cannot run).
    """
    try:
        _write_failure(
            workspace_id=workspace_id, user_id=user_id, note_id=note_id, digest=digest, model=model,
            prompt_version=prompt_version, provider=provider, entry_id=entry_id,
            maximum_usd=maximum_usd, failure_kind=failure_kind, call_outcome=call_outcome,
            error_class=error_class, attempts=attempts,
        )
    except Exception as exc:
        raise ServiceError(
            "EXTRACTION_RECORD_FAILED",
            "The provider call finished but its outcome could not be recorded; the spend is held as uncertain",
            500,
        ) from exc
    raise ServiceError(code, message, http_status) from cause


def _settle_and_persist(
    *,
    workspace_id: str,
    user_id: str,
    note_id: str,
    digest: str,
    model: str,
    prompt_version: str,
    provider: GenerationProvider,
    entry_id: str,
    attempts: int,
    result: ProviderResult,
    nfc: str,
    known_lots: Collection[str],
    unclamped: float,
    maximum_usd: float,
) -> ExtractionResult:
    charged = min(max(unclamped, 0.0), maximum_usd)
    clean_raw, nul_removed = _strip_nul(result.raw)
    details = {
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "provider": provider.name,
        "unclamped_usd": unclamped,
        "reserved_usd": maximum_usd,
        "over_reservation": unclamped > maximum_usd,
        "nul_removed": nul_removed,
    }
    with session_scope() as session:
        spending.settle(session, entry_id, charged, details)
        try:
            with session.begin_nested():
                if not (0 <= result.input_tokens <= INT4_MAX and 0 <= result.output_tokens <= INT4_MAX):
                    raise ValueError("provider reported token counts outside the stored range")
                row, fact_ids = _persist_checked(
                    session, workspace_id=workspace_id, user_id=user_id, note_id=note_id,
                    digest=digest, model=model, prompt_version=prompt_version, provider=provider,
                    entry_id=entry_id, charged_usd=charged, input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens, raw=clean_raw, nfc=nfc, known_lots=known_lots,
                )
        except Exception as exc:
            # The savepoint rolled back; the settled spend stays. Record the failure minimally.
            error_class = type(exc).__name__
            row = _store(
                session, workspace_id=workspace_id, user_id=user_id, note_id=note_id, digest=digest,
                model=model, prompt_version=prompt_version, status=STATUS_FAILED,
                failure_kind=FAILURE_STORE, spend_entry_id=entry_id, cost_usd=charged,
                error_class=error_class,
            )
            _record_call(
                session, row, provider, outcome="PERSIST_FAILED", error_class=error_class,
                input_tokens=None, output_tokens=None, cost_usd=charged, spend_entry_id=entry_id,
            )
            return _result(row, attempts, replayed=False, provider_called=True)
        return _result(row, attempts, replayed=False, provider_called=True, fact_ids=fact_ids)


def extract_note(
    workspace_id: str,
    user_id: str,
    note_id: str,
    note_text: str,
    provider: GenerationProvider,
    model: str,
    prompt_version: str,
    known_lots: Collection[str],
) -> ExtractionResult:
    """Extract one note once per (note digest, model, prompt version, schema version).

    Admission: a process-wide slot (KEY_SLOT_WAIT_SECONDS), then the per-key advisory lock
    (KEY_LOCK_WAIT_SECONDS). Both raise EXTRACTION_BUSY (429) with no call and no spend. The
    replay and attempt checks run after the lock, so a waiting caller replays the winner's
    result. Owns its transactions; the caller's session is never used.

    Raises `ServiceError` for invalid input (422), an unpriced model, a refused budget
    (`BUDGET_REFUSED`), an exhausted retry budget (`EXTRACTION_RETRIES_EXHAUSTED`, 409),
    EXTRACTION_BUSY (429), and failures after the provider was called. Ordinary provider
    exceptions come back as FAILED results; an interrupt is recorded and re-raised unchanged.
    """
    _validate_inputs(workspace_id, user_id, note_id, note_text, prompt_version)
    try:
        model_price(model)
    except UnknownModelPriceError as exc:
        raise ServiceError("UNKNOWN_MODEL", str(exc), 422) from exc
    digest = note_digest(note_text)
    nfc = normalize_note(note_text)
    maximum_usd = spending.cost(
        len(nfc.encode("utf-8")) + PROMPT_OVERHEAD_TOKENS, MAX_OUTPUT_TOKENS, model=model
    )
    if not _KEY_SLOTS.acquire(timeout=KEY_SLOT_WAIT_SECONDS):
        raise ServiceError(
            "EXTRACTION_BUSY", "Too many extractions are running; try again shortly", 429
        )
    try:
        with _key_lock(workspace_id, digest, model, prompt_version):
            return _extract_locked(
                workspace_id=workspace_id, user_id=user_id, note_id=note_id, digest=digest, nfc=nfc,
                provider=provider, model=model, prompt_version=prompt_version,
                known_lots=known_lots, maximum_usd=maximum_usd,
            )
    finally:
        _KEY_SLOTS.release()


def _extract_locked(
    *,
    workspace_id: str,
    user_id: str,
    note_id: str,
    digest: str,
    nfc: str,
    provider: GenerationProvider,
    model: str,
    prompt_version: str,
    known_lots: Collection[str],
    maximum_usd: float,
) -> ExtractionResult:
    # 1. Reserve: checks and reservation in one committed transaction, before the call.
    with session_scope() as session:
        spending.lock(session)
        key = _key_filter(workspace_id, digest, model, prompt_version)
        done = session.scalar(select(NoteExtraction).where(*key, NoteExtraction.status == STATUS_COMPLETED))
        if done is not None:
            return _result(done, 0, replayed=True, provider_called=False)
        failures = list(
            session.scalars(
                select(NoteExtraction)
                .where(*key, NoteExtraction.status == STATUS_FAILED)
                .order_by(NoteExtraction.created_at, NoteExtraction.id)
            ).all()
        )
        if failures:
            last = failures[-1]
            if last.failure_kind != FAILURE_PROVIDER:
                return _result(last, len(failures), replayed=True, provider_called=False)
            if len(failures) >= ATTEMPT_LIMIT:
                raise ServiceError(
                    "EXTRACTION_RETRIES_EXHAUSTED",
                    f"Extraction failed {len(failures)} times; no further provider call",
                    409,
                )
        try:
            entry = spending.reserve(session, user_id, SPEND_PURPOSE, SPEND_OPERATION, maximum_usd)
        except ServiceError as exc:
            raise ServiceError(
                "BUDGET_REFUSED",
                "Extraction budget refused; no provider call was made",
                exc.http_status,
                exc.retry_after,
            ) from exc
        entry_id = entry.id
        attempts = len(failures) + 1

    common: dict[str, Any] = {
        "workspace_id": workspace_id,
        "user_id": user_id,
        "note_id": note_id,
        "digest": digest,
        "model": model,
        "prompt_version": prompt_version,
        "provider": provider,
        "entry_id": entry_id,
        "maximum_usd": maximum_usd,
        "attempts": attempts,
    }

    # 2. Call: no transaction and no lock held beyond the key lock.
    try:
        result = provider.extract(
            nfc, prompt_version=prompt_version, schema=note_signal_json_schema(), max_tokens=MAX_OUTPUT_TOKENS
        )
    except Exception as exc:
        error_class = type(exc).__name__
        try:
            return _write_failure(
                **common, failure_kind=FAILURE_PROVIDER, call_outcome="ERROR", error_class=error_class,
            )
        except Exception as record_exc:
            _record_after_provider_failure(
                **common, failure_kind=FAILURE_PROVIDER, call_outcome="ERROR", error_class=error_class,
                code="EXTRACTION_RECORD_FAILED",
                message="The provider call failed and its outcome could not be recorded; the spend is held as uncertain",
                http_status=500, cause=record_exc,
            )
    except BaseException as exc:
        # Interrupted or cancelled: the attempt still counts, then the original propagates unchanged.
        with suppress(Exception):
            _write_failure(
                **common, failure_kind=FAILURE_PROVIDER, call_outcome="ERROR",
                error_class=type(exc).__name__,
            )
        raise

    # 3. Usage validation before any charge is computed. Unknown usage is charged at the maximum.
    if not (_usage_ok(result.input_tokens) and _usage_ok(result.output_tokens)):
        _record_after_provider_failure(
            **common, failure_kind=FAILURE_INVALID, call_outcome="INVALID_OUTPUT",
            error_class="InvalidProviderUsage", code="INVALID_PROVIDER_USAGE",
            message="Provider reported unusable token counts; the spend is charged at the reservation maximum",
            http_status=502, cause=ValueError("negative or non-integer token count"),
        )

    # 4. Settle and persist in one transaction. Any failure here is recorded and raised.
    try:
        return _settle_and_persist(
            workspace_id=workspace_id, user_id=user_id, note_id=note_id, digest=digest, model=model,
            prompt_version=prompt_version, provider=provider, entry_id=entry_id, attempts=attempts,
            result=result, nfc=nfc, known_lots=known_lots,
            unclamped=spending.cost(result.input_tokens, result.output_tokens, model=model),
            maximum_usd=maximum_usd,
        )
    except ServiceError:
        raise
    except Exception as exc:
        _record_after_provider_failure(
            **common, failure_kind=FAILURE_STORE, call_outcome="PERSIST_FAILED",
            error_class=type(exc).__name__, code="EXTRACTION_STORE_FAILED",
            message="The provider call finished but the result could not be stored; the spend is charged at the reservation maximum",
            http_status=500, cause=exc,
        )
