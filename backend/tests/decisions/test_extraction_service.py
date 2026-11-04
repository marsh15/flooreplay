"""Database-backed tests for note extraction: transactions, budget, retries, facts, isolation.

The service commits its own short transactions, so these tests commit too. Each test uses uuid
workspaces and a uuid user; the user's spend rows are deleted afterwards (spend is not
append-only), while extraction rows are append-only and stay under their uuid workspace.
Providers are mock doubles only; nothing here reaches a network. Pilot counts are asserted,
never model accuracy.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.exc import DBAPIError

from flooreplay import spending
from flooreplay.db import SessionLocal
from flooreplay.decisions.extraction.provider import MockProvider, ProviderResult, RaisingProvider
from flooreplay.decisions.extraction.schema import SCHEMA_VERSION as SCHEMA_HEAD_FOR_KEY
from flooreplay.decisions.extraction.schema import note_digest
from flooreplay.decisions.extraction_service import (
    ATTEMPT_LIMIT,
    MAX_OUTPUT_TOKENS,
    ExtractionResult,
    extract_note,
)
from flooreplay.decisions.models import FactRow, NoteExtraction, ProviderCall
from flooreplay.errors import ServiceError
from flooreplay.paid_models import SpendEntry
from flooreplay.schema_head import SCHEMA_HEAD

MODEL = "claude-haiku-5-5"
OTHER_MODEL = "gpt-4.1-mini-2025-04-14"
PROMPT = "note-extract-v2"
KNOWN_LOTS = frozenset({"L-221"})
NOTE = "Store: L-221 NAVY SJ180, shade fail on 1200 m. Keep that part on hold."
CORPUS = Path(__file__).resolve().parents[2] / "evaluation" / "note-benchmark-v1" / "notes.jsonl"


def uid() -> str:
    return uuid.uuid4().hex


@pytest.fixture
def workspace() -> str:
    return "ws-" + uid()


@pytest.fixture
def user() -> Iterator[str]:
    user_id = "user-" + uid()
    yield user_id
    with SessionLocal() as db:
        db.execute(delete(SpendEntry).where(SpendEntry.user_id == user_id))
        db.commit()


def valid_payload() -> dict[str, Any]:
    return {
        "lot_id": {"value": "L-221", "evidence": "L-221"},
        "issue": {"value": "shade_fail", "evidence": "shade fail"},
        "qty": {"value": "1200", "evidence": "1200 m"},
        "unit": {"value": "m", "evidence": "1200 m"},
        "colour": {"value": "NAVY", "evidence": "NAVY"},
        "fabric_quality": None,
        "language": "en",
    }


def provider_result(raw: dict[str, Any], *, input_tokens: int = 100, output_tokens: int = 50) -> ProviderResult:
    return ProviderResult(raw=raw, input_tokens=input_tokens, output_tokens=output_tokens, model=MODEL)


class Interrupted(BaseException):
    """Stands in for KeyboardInterrupt or a process exit in the middle of a provider call."""


class CountingProvider:
    """A MockProvider that counts calls and records the max_tokens it was given."""

    def __init__(self, table: dict[str, dict[str, Any]] | None = None, *, model: str = MODEL) -> None:
        self.name = "counting"
        self.model = model
        self.calls = 0
        self.max_tokens_seen: list[int | None] = []
        self._inner = MockProvider(table or {}, name="counting", model=model)

    def extract(
        self, note: str, *, prompt_version: str, schema: dict[str, Any], max_tokens: int | None = None
    ) -> ProviderResult:
        self.calls += 1
        self.max_tokens_seen.append(max_tokens)
        return self._inner.extract(note, prompt_version=prompt_version, schema=schema)


class ScriptedProvider:
    """Each call pops the next item: a ProviderResult is returned, an exception is raised."""

    def __init__(self, script: list[Any], *, name: str = "scripted") -> None:
        self.name = name
        self.model = MODEL
        self.script = list(script)
        self.calls = 0
        self.max_tokens_seen: list[int | None] = []

    def extract(
        self, note: str, *, prompt_version: str, schema: dict[str, Any], max_tokens: int | None = None
    ) -> ProviderResult:
        self.calls += 1
        self.max_tokens_seen.append(max_tokens)
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def run(workspace: str, user: str, provider: Any, note: str = NOTE, *, note_id: str = "NOTE-1", model: str = MODEL, prompt: str = PROMPT) -> ExtractionResult:
    return extract_note(workspace, user, note_id, note, provider, model, prompt, KNOWN_LOTS)


def keyed_rows(workspace: str) -> list[NoteExtraction]:
    with SessionLocal() as db:
        return list(db.scalars(select(NoteExtraction).where(NoteExtraction.workspace_id == workspace)).all())


def spend_rows(user: str) -> list[SpendEntry]:
    with SessionLocal() as db:
        return list(db.scalars(select(SpendEntry).where(SpendEntry.user_id == user)).all())


def facts(workspace: str) -> list[FactRow]:
    with SessionLocal() as db:
        return list(db.scalars(select(FactRow).where(FactRow.workspace_id == workspace)).all())


def _rejected(statement: str, params: dict[str, Any]) -> str:
    with SessionLocal() as db:
        with pytest.raises(DBAPIError) as caught, db.begin_nested():
            db.execute(text(statement), params)
        return str(caught.value)


# ---------------------------------------------------------------------------
# Idempotency and replay
# ---------------------------------------------------------------------------


def test_second_run_for_the_same_key_makes_no_provider_call_and_no_spend(workspace: str, user: str) -> None:
    provider = CountingProvider({})
    first = run(workspace, user, provider)
    spend_after_first = len(spend_rows(user))

    second = run(workspace, user, provider)

    assert first.provider_called is True and first.replayed is False
    assert second.provider_called is False and second.replayed is True
    assert second.extraction_id == first.extraction_id
    assert provider.calls == 1
    assert len(spend_rows(user)) == spend_after_first == 1


def test_completed_row_is_replayed_even_with_a_raising_provider(workspace: str, user: str) -> None:
    run(workspace, user, CountingProvider({}))

    replay = run(workspace, user, RaisingProvider())

    assert replay.status == "COMPLETED"
    assert replay.replayed is True
    assert replay.provider_called is False


def test_a_new_model_or_prompt_is_a_new_key(workspace: str, user: str) -> None:
    first = run(workspace, user, CountingProvider({}))
    other = run(workspace, user, CountingProvider({}, model=OTHER_MODEL), model=OTHER_MODEL)

    assert other.extraction_id != first.extraction_id
    assert other.provider_called is True


# ---------------------------------------------------------------------------
# Input validation (before any reservation or call)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"prompt": "p" * 33},
        {"note": NOTE + "\x00"},
    ],
)
def test_invalid_input_is_422_with_no_call_and_no_spend(workspace: str, user: str, kwargs: dict[str, Any]) -> None:
    provider = CountingProvider({})

    with pytest.raises(ServiceError) as caught:
        run(workspace, user, provider, **kwargs)

    assert caught.value.code == "INVALID_EXTRACTION"
    assert caught.value.http_status == 422
    assert provider.calls == 0
    assert spend_rows(user) == []


def test_user_id_of_201_characters_is_422_before_any_reservation(workspace: str) -> None:
    provider = CountingProvider({})
    long_user = "u" * 201

    with pytest.raises(ServiceError) as caught:
        run(workspace, long_user, provider)

    assert caught.value.code == "INVALID_EXTRACTION"
    assert provider.calls == 0
    assert spend_rows(long_user) == []


def test_unpriced_model_is_refused_before_any_reservation(workspace: str, user: str) -> None:
    provider = CountingProvider({}, model="unpriced-model-x")

    with pytest.raises(ServiceError) as caught:
        run(workspace, user, provider, model="unpriced-model-x")

    assert caught.value.code == "UNKNOWN_MODEL"
    assert provider.calls == 0
    assert spend_rows(user) == []


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------


def test_refused_budget_makes_no_call_and_stores_nothing(
    workspace: str, user: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*args: Any, **kwargs: Any) -> None:
        raise ServiceError("ALLOWANCE_EXHAUSTED", "Insufficient reserved spending allowance", 402)

    monkeypatch.setattr(spending, "reserve", refuse)
    provider = CountingProvider({})

    with pytest.raises(ServiceError) as caught:
        run(workspace, user, provider)

    assert caught.value.code == "BUDGET_REFUSED"
    assert provider.calls == 0
    assert keyed_rows(workspace) == []
    assert spend_rows(user) == []


def test_reservation_is_committed_before_the_call_and_visible_from_another_session(
    workspace: str, user: str
) -> None:
    seen_during_call: list[int] = []

    class Probe(CountingProvider):
        def extract(self, note: str, **kwargs: Any) -> ProviderResult:
            seen_during_call.append(len([r for r in spend_rows(user) if r.status == "RESERVED"]))
            return super().extract(note, **kwargs)

    run(workspace, user, Probe({}))

    assert seen_during_call == [1]


def test_interrupted_call_is_recorded_as_an_attempt_and_the_interrupt_propagates(
    workspace: str, user: str
) -> None:
    with pytest.raises(Interrupted):
        run(workspace, user, ScriptedProvider([Interrupted()]))

    (entry,) = spend_rows(user)
    maximum_usd = entry.reserved_inr / entry.price_table["inr_per_usd"]
    assert entry.status == "UNCERTAIN"
    assert entry.charged_usd == pytest.approx(maximum_usd)
    (row,) = keyed_rows(workspace)
    assert row.status == "FAILED" and row.failure_kind == "PROVIDER_ERROR"
    assert row.error_class == "Interrupted"


# ---------------------------------------------------------------------------
# Output cap and settlement clamp
# ---------------------------------------------------------------------------


def test_provider_is_given_the_output_cap(workspace: str, user: str) -> None:
    provider = CountingProvider({})

    run(workspace, user, provider)

    assert provider.max_tokens_seen == [MAX_OUTPUT_TOKENS]


def test_output_far_above_the_cap_is_clamped_to_the_reservation(workspace: str, user: str) -> None:
    provider = ScriptedProvider([provider_result(valid_payload(), output_tokens=10_000_000)])

    result = run(workspace, user, provider)

    assert result.status == "COMPLETED"
    (entry,) = spend_rows(user)
    maximum_usd = entry.reserved_inr / entry.price_table["inr_per_usd"]
    assert entry.status == "SETTLED"
    assert entry.charged_usd == pytest.approx(maximum_usd)
    assert entry.details["over_reservation"] is True
    assert entry.details["unclamped_usd"] > entry.details["reserved_usd"]


# ---------------------------------------------------------------------------
# Facts and review
# ---------------------------------------------------------------------------


def test_passed_fields_become_one_fact_with_provenance(workspace: str, user: str) -> None:
    result = run(workspace, user, CountingProvider({note_digest(NOTE): valid_payload()}))

    assert result.status == "COMPLETED"
    assert result.review_fields == ()
    assert len(result.fact_ids) == 1
    (fact,) = facts(workspace)
    assert fact.kind == "fabric_qc"
    assert fact.source == "notes"
    assert fact.entity_key == "lot:L-221"
    assert fact.payload["origin"] == "notes"
    assert fact.payload["review_state"] == "checks_passed"
    assert fact.payload["extraction_id"] == result.extraction_id
    assert fact.payload["issue"] == "shade_fail"


def test_failed_field_stays_out_of_facts_and_goes_to_review(workspace: str, user: str) -> None:
    payload = valid_payload()
    payload["qty"] = {"value": "1300", "evidence": "1200 m"}  # claims 1300, the note says 1200

    result = run(workspace, user, ScriptedProvider([provider_result(payload)]))

    assert result.fact_ids == ()
    assert [r.field for r in result.review_fields] == ["qty"]
    assert result.review_fields[0].status == "failed"
    assert facts(workspace) == []


def test_one_note_adds_quantity_once_even_across_models(workspace: str, user: str) -> None:
    first = run(workspace, user, ScriptedProvider([provider_result(valid_payload())]))
    second = run(
        workspace,
        user,
        ScriptedProvider([provider_result(valid_payload())], name="other"),
        model=OTHER_MODEL,
    )

    assert len(first.fact_ids) == 1
    assert second.fact_ids == ()
    assert len(facts(workspace)) == 1


# ---------------------------------------------------------------------------
# Payload hygiene: NUL characters
# ---------------------------------------------------------------------------


def test_nul_in_provider_output_is_stripped_before_storage(workspace: str, user: str) -> None:
    payload = valid_payload()
    payload["colour"] = {"value": "NAVY\x00", "evidence": "NAVY"}

    result = run(workspace, user, ScriptedProvider([provider_result(payload)]))

    assert result.status == "COMPLETED"
    (row,) = keyed_rows(workspace)
    assert "\\u0000" not in json.dumps(row.raw_output)
    assert row.raw_output["colour"]["value"] == "NAVY"
    (entry,) = spend_rows(user)
    assert entry.details["nul_removed"] == 1


# ---------------------------------------------------------------------------
# Persist failure keeps the spend and records the attempt
# ---------------------------------------------------------------------------


def test_store_failure_keeps_spend_and_records_a_minimal_failed_row(workspace: str, user: str) -> None:
    # Token counts beyond the stored Integer range make the persist step fail after the call.
    provider = ScriptedProvider([provider_result(valid_payload(), input_tokens=2**40)])

    result = run(workspace, user, provider)

    assert result.status == "FAILED"
    assert result.failure_kind == "STORE_FAILED"
    assert result.provider_called is True
    (row,) = keyed_rows(workspace)
    assert row.raw_output is None and row.signal is None and row.input_tokens is None
    (call,) = [c for c in _calls(workspace)]
    assert call.outcome == "PERSIST_FAILED"
    (entry,) = spend_rows(user)
    assert entry.status == "SETTLED"
    assert entry.charged_usd > 0


def test_store_failure_is_final_and_not_re_billed(workspace: str, user: str) -> None:
    run(workspace, user, ScriptedProvider([provider_result(valid_payload(), input_tokens=2**40)]))
    provider = CountingProvider({})

    again = run(workspace, user, provider)

    assert again.replayed is True
    assert again.failure_kind == "STORE_FAILED"
    assert provider.calls == 0
    assert len(spend_rows(user)) == 1


def _calls(workspace: str) -> list[ProviderCall]:
    with SessionLocal() as db:
        return list(db.scalars(select(ProviderCall).where(ProviderCall.workspace_id == workspace)).all())


# ---------------------------------------------------------------------------
# Provider failures and retries
# ---------------------------------------------------------------------------


def test_provider_error_is_recorded_settled_and_not_raised(workspace: str, user: str) -> None:
    secret = "sk-live-SECRET-123"
    provider = ScriptedProvider([RuntimeError(f"upstream said: {secret} in request body")], name="failing")

    result = run(workspace, user, provider)

    assert result.status == "FAILED"
    assert result.failure_kind == "PROVIDER_ERROR"
    assert result.error_class == "RuntimeError"
    (call,) = _calls(workspace)
    assert call.outcome == "ERROR" and call.error_class == "RuntimeError"
    (entry,) = spend_rows(user)
    assert entry.status == "UNCERTAIN"
    assert entry.charged_usd > 0
    stored = json.dumps([r.error_class for r in keyed_rows(workspace)] + [call.error_class])
    assert secret not in stored


def test_schema_invalid_output_is_failed_with_its_own_call_outcome(workspace: str, user: str) -> None:
    result = run(workspace, user, ScriptedProvider([provider_result({"unexpected": True})]))

    assert result.status == "FAILED"
    assert result.failure_kind == "INVALID_OUTPUT"
    (call,) = _calls(workspace)
    assert call.outcome == "INVALID_OUTPUT"


def test_transient_failure_then_success_completes_with_one_fact(workspace: str, user: str) -> None:
    provider = ScriptedProvider(
        [RuntimeError("timeout"), provider_result(valid_payload())]
    )

    first = run(workspace, user, provider)
    second = run(workspace, user, provider)

    assert first.status == "FAILED" and first.failure_kind == "PROVIDER_ERROR"
    assert second.status == "COMPLETED"
    assert second.provider_called is True
    assert second.attempts == 2
    assert provider.calls == 2
    assert len(second.fact_ids) == 1
    assert len(facts(workspace)) == 1
    assert len(spend_rows(user)) == 2


def test_invalid_output_is_not_retried_and_not_re_billed(workspace: str, user: str) -> None:
    provider = ScriptedProvider([provider_result({"unexpected": True}), provider_result(valid_payload())])
    run(workspace, user, provider)
    spend_after_first = len(spend_rows(user))

    again = run(workspace, user, provider)

    assert again.replayed is True
    assert again.provider_called is False
    assert again.failure_kind == "INVALID_OUTPUT"
    assert provider.calls == 1
    assert len(spend_rows(user)) == spend_after_first == 1


def test_fourth_attempt_is_refused_with_no_call_and_no_spend(workspace: str, user: str) -> None:
    assert ATTEMPT_LIMIT == 3
    provider = ScriptedProvider([RuntimeError("timeout")] * ATTEMPT_LIMIT + [provider_result(valid_payload())])
    for _ in range(ATTEMPT_LIMIT):
        assert run(workspace, user, provider).status == "FAILED"
    spend_before = len(spend_rows(user))

    with pytest.raises(ServiceError) as caught:
        run(workspace, user, provider)

    assert caught.value.code == "EXTRACTION_RETRIES_EXHAUSTED"
    assert caught.value.http_status == 409
    assert provider.calls == ATTEMPT_LIMIT
    assert len(spend_rows(user)) == spend_before == ATTEMPT_LIMIT


# ---------------------------------------------------------------------------
# Database guarantees and isolation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE note_extractions SET language = 'ta' WHERE workspace_id = :ws",
        "DELETE FROM note_extractions WHERE workspace_id = :ws",
        "UPDATE provider_calls SET outcome = 'OK' WHERE workspace_id = :ws",
        "DELETE FROM provider_calls WHERE workspace_id = :ws",
    ],
)
def test_update_and_delete_are_rejected_by_the_database(workspace: str, user: str, statement: str) -> None:
    run(workspace, user, CountingProvider({}))

    assert "append-only" in _rejected(statement, {"ws": workspace})


@pytest.mark.parametrize("table", ["note_extractions", "provider_calls"])
def test_truncate_is_rejected_by_the_database(workspace: str, user: str, table: str) -> None:
    run(workspace, user, CountingProvider({}))

    assert "append-only" in _rejected(f"TRUNCATE {table} CASCADE", {})


def test_completed_key_is_unique_in_the_database(workspace: str, user: str) -> None:
    run(workspace, user, CountingProvider({}))
    (row,) = keyed_rows(workspace)

    message = _rejected(
        "INSERT INTO note_extractions (workspace_id, id, note_id, note_digest, model, prompt_version,"
        " schema_version, status, signal, checks, field_status, cost_usd, created_by, created_at)"
        " VALUES (:ws, :id, 'dup', :digest, :model, :pv, :sv, 'COMPLETED',"
        " '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, 0, 'x', now())",
        {
            "ws": workspace,
            "id": uid(),
            "digest": row.note_digest,
            "model": row.model,
            "pv": row.prompt_version,
            "sv": row.schema_version,
        },
    )

    assert "uq_note_extractions_completed_key" in message


def test_extraction_is_isolated_by_workspace(user: str) -> None:
    ws_a, ws_b = "ws-" + uid(), "ws-" + uid()
    a = run(ws_a, user, CountingProvider({}))
    provider_b = CountingProvider({})
    b = run(ws_b, user, provider_b)

    assert b.extraction_id != a.extraction_id
    assert b.provider_called is True
    assert provider_b.calls == 1
    assert [row.id for row in keyed_rows(ws_a)] == [a.extraction_id]


def test_extraction_migration_is_in_the_chain_to_the_schema_head() -> None:
    # Pinning the head literal here broke when a later migration landed; the invariant is ancestry.
    from alembic.script import ScriptDirectory

    script = ScriptDirectory(str(Path(__file__).resolve().parents[2] / "alembic"))
    chain = {rev.revision for rev in script.iterate_revisions(SCHEMA_HEAD, "base")}
    assert "20261023_decisions_extraction" in chain


# ---------------------------------------------------------------------------
# Pilot: the first 30 notes of the draft corpus, mock provider only
# ---------------------------------------------------------------------------


def test_pilot_over_first_thirty_notes_counts_calls_and_replays(workspace: str, user: str) -> None:
    notes = [json.loads(line) for line in CORPUS.read_text(encoding="utf-8").splitlines()][:30]
    assert len(notes) == 30
    provider = CountingProvider({})

    first = [run(workspace, user, provider, note=n["text"], note_id=n["note_id"]) for n in notes]
    second = [run(workspace, user, provider, note=n["text"], note_id=n["note_id"]) for n in notes]

    assert provider.calls == 30
    assert all(r.status == "COMPLETED" and r.provider_called for r in first)
    assert all(r.replayed and not r.provider_called for r in second)
    assert len(keyed_rows(workspace)) == 30
    assert len(_calls(workspace)) == 30
    assert len(spend_rows(user)) == 30


# ---------------------------------------------------------------------------
# Concurrency: one key is serialised, different keys run in parallel
# ---------------------------------------------------------------------------

NOTE_B = NOTE + " Second note for the parallel-keys test."


class SlowProvider:
    """Counts calls under a lock, optionally waits on a shared barrier, then sleeps to overlap."""

    def __init__(
        self,
        *,
        delay: float = 0.5,
        barrier: threading.Barrier | None = None,
        fail: bool = False,
    ) -> None:
        self.name = "slow"
        self.model = MODEL
        self.delay = delay
        self.barrier = barrier
        self.fail = fail
        self.calls = 0
        self._lock = threading.Lock()

    def extract(
        self, note: str, *, prompt_version: str, schema: dict[str, Any], max_tokens: int | None = None
    ) -> ProviderResult:
        with self._lock:
            self.calls += 1
        if self.barrier is not None:
            self.barrier.wait(timeout=20)
        time.sleep(self.delay)
        if self.fail:
            raise RuntimeError("timeout")
        return provider_result(valid_payload())


def _race(workspace: str, user: str, jobs: list[tuple[Any, str]]) -> list[Any]:
    """Start one thread per (provider, note) at the same moment; return results or exceptions."""
    gate = threading.Barrier(len(jobs), timeout=20)
    out: list[Any] = [None] * len(jobs)

    def worker(index: int, provider: Any, note: str) -> None:
        gate.wait()
        try:
            out[index] = run(workspace, user, provider, note, note_id=f"RACE-{index}")
        except BaseException as exc:
            out[index] = exc

    threads = [threading.Thread(target=worker, args=(i, p, n)) for i, (p, n) in enumerate(jobs)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(60)
    assert not any(thread.is_alive() for thread in threads)
    return out


def test_same_key_race_makes_one_provider_call_and_one_spend(workspace: str, user: str) -> None:
    provider = SlowProvider(delay=0.5)

    first, second = _race(workspace, user, [(provider, NOTE), (provider, NOTE)])

    assert provider.calls == 1
    assert isinstance(first, ExtractionResult) and isinstance(second, ExtractionResult)
    assert first.status == second.status == "COMPLETED"
    assert first.extraction_id == second.extraction_id
    assert sorted([first.provider_called, second.provider_called]) == [False, True]
    assert sorted([first.replayed, second.replayed]) == [False, True]
    spends = spend_rows(user)
    assert len(spends) == 1
    assert spends[0].status == "SETTLED"
    assert len(keyed_rows(workspace)) == 1


def test_different_keys_overlap_and_both_call_the_provider(workspace: str, user: str) -> None:
    rendezvous = threading.Barrier(2, timeout=20)
    provider_a = SlowProvider(delay=0.1, barrier=rendezvous)
    provider_b = SlowProvider(delay=0.1, barrier=rendezvous)

    a, b = _race(workspace, user, [(provider_a, NOTE), (provider_b, NOTE_B)])

    # The barrier only passes if both providers are inside a call at the same moment.
    assert provider_a.calls == 1 and provider_b.calls == 1
    assert isinstance(a, ExtractionResult) and a.status == "COMPLETED" and a.provider_called
    assert isinstance(b, ExtractionResult) and b.status == "COMPLETED" and b.provider_called
    assert len(spend_rows(user)) == 2


def test_attempt_limit_holds_under_concurrent_failures(workspace: str, user: str) -> None:
    prior = ScriptedProvider([RuntimeError("t1"), RuntimeError("t2")])
    run(workspace, user, prior)
    run(workspace, user, prior)
    assert prior.calls == 2

    racer = SlowProvider(delay=0.3, fail=True)
    first, second = _race(workspace, user, [(racer, NOTE), (racer, NOTE)])

    outcomes = [first, second]
    exhausted = [o for o in outcomes if isinstance(o, ServiceError)]
    failed = [o for o in outcomes if isinstance(o, ExtractionResult)]
    assert len(exhausted) == 1 and exhausted[0].code == "EXTRACTION_RETRIES_EXHAUSTED"
    assert len(failed) == 1 and failed[0].failure_kind == "PROVIDER_ERROR"
    assert racer.calls == 1
    assert prior.calls + racer.calls == ATTEMPT_LIMIT

    with pytest.raises(ServiceError) as fourth:
        run(workspace, user, CountingProvider({}))
    assert fourth.value.code == "EXTRACTION_RETRIES_EXHAUSTED"
    assert len(spend_rows(user)) == ATTEMPT_LIMIT


# ---------------------------------------------------------------------------
# Failures after the provider returned
# ---------------------------------------------------------------------------


def test_settle_failure_after_the_call_is_recorded_and_raised(
    workspace: str, user: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_settle = spending.settle
    calls = {"n": 0}

    def flaky_settle(*args: Any, **kwargs: Any) -> Any:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("settle hiccup")
        return real_settle(*args, **kwargs)

    monkeypatch.setattr(spending, "settle", flaky_settle)
    provider = ScriptedProvider([provider_result(valid_payload())])

    with pytest.raises(ServiceError) as caught:
        run(workspace, user, provider)

    assert caught.value.code == "EXTRACTION_STORE_FAILED"
    assert provider.calls == 1
    (entry,) = spend_rows(user)
    maximum_usd = entry.reserved_inr / entry.price_table["inr_per_usd"]
    assert entry.status == "UNCERTAIN"
    assert entry.charged_usd == pytest.approx(maximum_usd)
    (row,) = keyed_rows(workspace)
    assert row.status == "FAILED" and row.failure_kind == "STORE_FAILED"
    (call,) = _calls(workspace)
    assert call.outcome == "PERSIST_FAILED"

    again = run(workspace, user, CountingProvider({}))
    assert again.replayed is True and again.failure_kind == "STORE_FAILED"
    assert again.provider_called is False


@pytest.mark.parametrize(
    "tokens",
    [{"input_tokens": -5}, {"output_tokens": -1}],
)
def test_negative_token_counts_are_charged_at_the_maximum_and_not_retried(
    workspace: str, user: str, tokens: dict[str, int]
) -> None:
    provider = ScriptedProvider([provider_result(valid_payload(), **tokens)])

    with pytest.raises(ServiceError) as caught:
        run(workspace, user, provider)

    assert caught.value.code == "INVALID_PROVIDER_USAGE"
    (entry,) = spend_rows(user)
    maximum_usd = entry.reserved_inr / entry.price_table["inr_per_usd"]
    assert entry.status == "UNCERTAIN"
    assert entry.charged_usd == pytest.approx(maximum_usd)
    assert entry.charged_usd > 0
    (row,) = keyed_rows(workspace)
    assert row.status == "FAILED" and row.failure_kind == "INVALID_OUTPUT"

    again = run(workspace, user, CountingProvider({}))
    assert again.replayed is True and again.provider_called is False


# ---------------------------------------------------------------------------
# Input length before any reservation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_workspace", ["w" * 65, "   "])
def test_workspace_id_is_validated_before_any_reservation(user: str, bad_workspace: str) -> None:
    provider = CountingProvider({})

    with pytest.raises(ServiceError) as caught:
        run(bad_workspace, user, provider)

    assert caught.value.code == "INVALID_EXTRACTION"
    assert caught.value.http_status == 422
    assert provider.calls == 0
    assert spend_rows(user) == []



def test_interrupted_calls_count_toward_the_attempt_limit(workspace: str, user: str) -> None:
    provider = ScriptedProvider([Interrupted(), Interrupted(), Interrupted(), provider_result(valid_payload())])
    for _ in range(ATTEMPT_LIMIT):
        with pytest.raises(Interrupted):
            run(workspace, user, provider)
    spend_before = len(spend_rows(user))

    with pytest.raises(ServiceError) as caught:
        run(workspace, user, provider)

    assert caught.value.code == "EXTRACTION_RETRIES_EXHAUSTED"
    assert provider.calls == ATTEMPT_LIMIT
    assert len(spend_rows(user)) == spend_before == ATTEMPT_LIMIT
    failed = [r for r in keyed_rows(workspace) if r.status == "FAILED"]
    assert len(failed) == ATTEMPT_LIMIT


def test_failure_to_record_a_provider_exception_is_guarded(
    workspace: str, user: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_settle = spending.settle
    calls = {"n": 0}

    def flaky_settle(*args: Any, **kwargs: Any) -> Any:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("settle hiccup on the provider-error path")
        return real_settle(*args, **kwargs)

    monkeypatch.setattr(spending, "settle", flaky_settle)

    with pytest.raises(ServiceError) as caught:
        run(workspace, user, ScriptedProvider([RuntimeError("timeout")]))

    assert caught.value.code == "EXTRACTION_RECORD_FAILED"
    (entry,) = spend_rows(user)
    maximum_usd = entry.reserved_inr / entry.price_table["inr_per_usd"]
    assert entry.status == "UNCERTAIN"
    assert entry.charged_usd == pytest.approx(maximum_usd)
    (row,) = keyed_rows(workspace)
    assert row.status == "FAILED" and row.failure_kind == "PROVIDER_ERROR"
    (call,) = _calls(workspace)
    assert call.outcome == "ERROR"


def test_sixteen_same_key_callers_make_one_call_and_never_see_a_raw_timeout(
    workspace: str, user: str
) -> None:
    provider = SlowProvider(delay=0.5)

    outcomes = _race(workspace, user, [(provider, NOTE)] * 16)

    assert provider.calls == 1
    for outcome in outcomes:
        if isinstance(outcome, ExtractionResult):
            assert outcome.status == "COMPLETED"
        else:
            assert isinstance(outcome, ServiceError), outcome
            assert outcome.code == "EXTRACTION_BUSY"
    assert any(isinstance(o, ExtractionResult) for o in outcomes)
    spends = spend_rows(user)
    assert len(spends) == 1 and spends[0].status == "SETTLED"


def test_busy_slots_refuse_with_429_and_no_call_or_spend(
    workspace: str, user: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from flooreplay.decisions import extraction_service

    monkeypatch.setattr(extraction_service, "KEY_SLOT_WAIT_SECONDS", 0.05)
    held = 0
    while extraction_service._KEY_SLOTS.acquire(blocking=False):
        held += 1
    try:
        provider = CountingProvider({})
        with pytest.raises(ServiceError) as caught:
            run(workspace, user, provider)
        assert caught.value.code == "EXTRACTION_BUSY"
        assert caught.value.http_status == 429
        assert provider.calls == 0
        assert spend_rows(user) == []
    finally:
        for _ in range(held):
            extraction_service._KEY_SLOTS.release()


def test_key_lock_lives_in_its_own_namespace_apart_from_the_spending_lock(workspace: str, user: str) -> None:
    from flooreplay.db import engine
    from flooreplay.decisions.extraction_service import EXTRACTION_LOCK_CLASSID, _key_lock

    digest = note_digest(NOTE)
    with _key_lock(workspace, digest, MODEL, PROMPT), engine.connect() as other:
        spending_free = other.execute(text("SELECT pg_try_advisory_lock(947362)")).scalar_one()
        if spending_free:
            other.execute(text("SELECT pg_advisory_unlock(947362)"))
        other.commit()
        key_free = other.execute(
            text("SELECT pg_try_advisory_lock(CAST(:classid AS integer), hashtext(:key))"),
            {
                "classid": EXTRACTION_LOCK_CLASSID,
                "key": "|".join((workspace, digest, MODEL, PROMPT, SCHEMA_HEAD_FOR_KEY)),
            },
        ).scalar_one()
        other.commit()
    assert spending_free is True
    assert key_free is False
