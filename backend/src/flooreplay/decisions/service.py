"""Effectful fact store: appends facts and loads them back as pure `Fact` objects.

All decisions about validity, visibility and digests stay in the pure modules
(`facts`, `snapshot`). This layer only adds what needs a database: per-entity locks,
the full correction graph at write time, and the database clock.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from datetime import UTC, datetime, timedelta

import psycopg.errors
from pydantic import ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.exc import DataError, DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from flooreplay.decisions import facts as fact_rules
from flooreplay.decisions import snapshot as snapshots
from flooreplay.decisions.compare import compare_cases
from flooreplay.decisions.expectations import Expectation, evaluate_expectation
from flooreplay.decisions.gate import CoverageDecl
from flooreplay.decisions.models import (
    CaseExpectation,
    DecisionCase,
    DecisionEvaluation,
    DecisionRecord,
    DecisionSourceArtifact,
    FactRow,
    PolicyAdoption,
    RegressionRun,
    StoredPolicy,
)
from flooreplay.decisions.policy import (
    DEFAULT_POLICY_V1,
    ENGINE_VERSION,
    PolicyDocument,
    policy_digest,
)
from flooreplay.decisions.replay import ReplayResult, replay
from flooreplay.decisions.types import (
    Classification,
    Fact,
    FactKind,
    FrozenModel,
    Recommendation,
    SourceProfile,
    Verdict,
    decision_digest,
)
from flooreplay.errors import ServiceError
from flooreplay.workspaces import allowed_workspaces

# A caller building a Fact for an untrusted append stamps it with its own "now". We accept
# that as a courtesy but never store it: the database clock wins.
CLIENT_CLOCK_TOLERANCE = timedelta(seconds=60)

SETTLE_HORIZON = timedelta(seconds=120)
"""How long a fresh `known_at` stays provisional.

`known_at` is stamped under the entity lock, but a transaction can still commit well after
it was stamped, so a fact may become visible with a `known_at` in the past. A snapshot whose
cutoff is later than `db_now - SETTLE_HORIZON` is therefore provisional: late commits may
still land before it. Anything that stores an evaluation must require `is_settled` first.
"""

LOCK_NAMESPACE = "decision-facts:"


def db_now(session: Session) -> datetime:
    """The database's wall clock (not the transaction start), so stamps follow lock order."""
    return session.execute(select(func.clock_timestamp())).scalar_one()


def is_settled(session: Session, cutoff: datetime) -> bool:
    """True when `cutoff` is old enough that no in-flight append can still land before it."""
    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
        raise ServiceError("CUTOFF_INVALID", "cutoff must carry a UTC offset", 422)
    return cutoff <= db_now(session) - SETTLE_HORIZON


def latest_settled_instant(session: Session) -> datetime:
    """The newest cutoff that is already settled: the database clock minus the settle horizon."""
    return db_now(session) - SETTLE_HORIZON


def _row_to_fact(row: FactRow) -> Fact:
    return Fact(
        id=row.id,
        kind=FactKind(row.kind),
        entity_key=row.entity_key,
        payload=row.payload,
        valid_from=row.valid_from,
        valid_to=row.valid_to,
        known_at=row.known_at,
        supersedes_id=row.supersedes_id,
        source=SourceProfile(row.source),
        artifact_id=row.artifact_id,
    )


def _take_locks(session: Session, workspace_id: str, facts: Sequence[Fact]) -> None:
    """Lock every touched entity, in ascending hash order, so batches cannot deadlock."""
    keys = {f"{LOCK_NAMESPACE}{workspace_id}:{f.kind.value}:{f.entity_key}" for f in facts}
    hashes: list[int] = sorted({session.scalar(select(func.hashtext(key))) or 0 for key in keys})
    for value in hashes:
        session.execute(select(func.pg_advisory_xact_lock(value)))


def _lock_suite(session: Session, workspace_id: str) -> None:
    """Serialise suite changes, regression runs and adoptions within one workspace."""
    key = f"decision-suite:{workspace_id}"
    session.execute(select(func.pg_advisory_xact_lock(func.hashtext(key))))


def _check_nul(fact: Fact) -> None:
    for value in (fact.id, fact.entity_key, fact.supersedes_id, fact.artifact_id):
        if value is not None and "\x00" in value:
            raise ServiceError("FACT_INVALID", "NUL characters are not allowed in text", 422)


def _require_read_committed(session: Session) -> None:
    # The entity lock plus a fresh read of the entity's facts is only sound when each
    # statement sees everything committed before it. Stronger isolation would hide rows.
    level: str | None = session.scalar(text("SHOW transaction_isolation"))
    if level != "read committed":
        raise ServiceError(
            "ISOLATION_UNSUPPORTED", f"append_facts needs READ COMMITTED, got {level}", 500
        )


def _stamp(fact: Fact, now: datetime, trusted_known_at: datetime | None) -> datetime:
    if trusted_known_at is not None:
        return trusted_known_at
    if abs(fact.known_at - now) > CLIENT_CLOCK_TOLERANCE:
        raise ServiceError(
            "KNOWN_AT_CLIENT_SUPPLIED",
            "known_at is set by the server; only seed and CLI may author it",
            422,
        )
    return now


def translate_db_error(exc: DBAPIError) -> ServiceError | None:
    """The ServiceError for a database failure the caller can act on, else None."""
    if isinstance(exc.orig, psycopg.errors.DeadlockDetected | psycopg.errors.SerializationFailure):
        return ServiceError(
            "RETRY", "Concurrent write conflict; retry the request", 409, retry_after=1
        )
    if isinstance(exc, DataError):
        return ServiceError("FACT_INVALID", "fact contains a value the database cannot store", 422)
    return None


def append_fact(
    session: Session,
    fact: Fact,
    *,
    workspace_id: str,
    trusted_known_at: datetime | None = None,
) -> FactRow:
    """Append one fact; see `append_facts`."""
    return append_facts(
        session, [fact], workspace_id=workspace_id, trusted_known_at=trusted_known_at
    )[0]


def append_facts(
    session: Session,
    facts: Sequence[Fact],
    *,
    workspace_id: str,
    trusted_known_at: datetime | None = None,
) -> list[FactRow]:
    """Validate and append facts as one all-or-nothing batch; never modifies an existing row.

    Every touched entity is locked first, in a global order, then one `known_at` is stamped
    from the database clock for the whole batch. Corrections must therefore go in a later call
    than the fact they replace (they need a strictly later `known_at`).

    Only seed and CLI code may pass `trusted_known_at` to author `known_at` (the frozen cases
    need that). It is refused whenever a workspace scope is active, i.e. on any HTTP path.
    Either way `valid_from <= known_at` (no backdating), a referenced artifact must be in the
    same workspace, and the full correction graph of each entity (existing facts plus the new
    one) must still validate.
    """
    if not facts:
        return []
    if trusted_known_at is not None:
        if allowed_workspaces.get() is not None:
            raise ServiceError(
                "TRUSTED_TIME_FORBIDDEN", "known_at cannot be authored in a workspace scope", 403
            )
        if trusted_known_at.tzinfo is None or trusted_known_at.utcoffset() is None:
            raise ServiceError("KNOWN_AT_INVALID", "trusted_known_at must carry a UTC offset", 422)
    for fact in facts:
        _check_nul(fact)
    try:
        _require_read_committed(session)
        _take_locks(session, workspace_id, facts)
        now = db_now(session)  # after the locks: stamps follow lock order, not arrival order
        with session.begin_nested():  # all or nothing, without poisoning the caller's session
            return [
                _append_one(session, fact, workspace_id, _stamp(fact, now, trusted_known_at))
                for fact in facts
            ]
    except DBAPIError as exc:
        translated = translate_db_error(exc)
        if translated is None:
            raise
        raise translated from exc


def _append_one(session: Session, fact: Fact, workspace_id: str, known_at: datetime) -> FactRow:
    fact = fact.model_copy(update={"known_at": known_at})
    if fact.valid_from > known_at:
        raise ServiceError(
            "BACKDATED",
            f"valid_from {fact.valid_from.isoformat()} is after known_at {known_at.isoformat()}",
            422,
        )
    try:  # after stamping, so the pure rules judge the known_at that will be stored
        fact = fact_rules.validate_fact(fact)
    except fact_rules.FactValidationError as exc:
        raise ServiceError("FACT_INVALID", str(exc), 422) from exc

    if session.scalar(
        select(FactRow.id).where(FactRow.workspace_id == workspace_id, FactRow.id == fact.id)
    ):
        raise ServiceError("FACT_ID_TAKEN", f"fact {fact.id} already exists", 409)
    if fact.artifact_id is not None and not session.scalar(
        select(DecisionSourceArtifact.id).where(
            DecisionSourceArtifact.workspace_id == workspace_id,
            DecisionSourceArtifact.id == fact.artifact_id,
        )
    ):
        raise ServiceError(
            "ARTIFACT_UNKNOWN", f"artifact {fact.artifact_id} not found in this workspace", 422
        )

    entity_rows = session.scalars(
        select(FactRow).where(
            FactRow.workspace_id == workspace_id,
            FactRow.kind == fact.kind.value,
            FactRow.entity_key == fact.entity_key,
        )
    ).all()
    graph = [_row_to_fact(row) for row in entity_rows]
    if fact.supersedes_id is not None and all(f.id != fact.supersedes_id for f in graph):
        # Pull the target in even if it is another kind or entity, so the pure check can
        # name the real problem (kind or entity mismatch) instead of "unknown target".
        target = session.scalar(
            select(FactRow).where(
                FactRow.workspace_id == workspace_id, FactRow.id == fact.supersedes_id
            )
        )
        if target is not None:
            graph.append(_row_to_fact(target))
    try:
        fact_rules.validate_corrections([*graph, fact])
    except fact_rules.CorrectionError as exc:
        raise ServiceError("CORRECTION_INVALID", f"{exc.code.value}: {exc}", 422) from exc

    dumped = fact.model_dump(mode="json")
    row = FactRow(
        id=fact.id,
        workspace_id=workspace_id,
        kind=fact.kind.value,
        entity_key=fact.entity_key,
        payload=dumped["payload"],
        valid_from=fact.valid_from,
        valid_to=fact.valid_to,
        known_at=known_at,
        supersedes_id=fact.supersedes_id,
        source=fact.source.value,
        artifact_id=fact.artifact_id,
        semantic_digest=fact_rules.semantic_digest(fact),
    )
    try:
        with session.begin_nested():
            session.add(row)
            session.flush()
    except IntegrityError as exc:
        raise ServiceError("FACT_REJECTED", "fact violates a stored-data constraint", 409) from exc
    return row


def load_facts(
    session: Session,
    workspace_id: str,
    *,
    kinds: Collection[FactKind] | None = None,
    entity_keys: Collection[str] | None = None,
    known_by: datetime | None = None,
) -> list[Fact]:
    """The workspace's facts as pure `Fact`s, ordered by (known_at, id)."""
    query = select(FactRow).where(FactRow.workspace_id == workspace_id)
    if kinds is not None:
        query = query.where(FactRow.kind.in_([k.value for k in kinds]))
    if entity_keys is not None:
        query = query.where(FactRow.entity_key.in_(list(entity_keys)))
    if known_by is not None:
        query = query.where(FactRow.known_at <= known_by)
    rows = session.scalars(query.order_by(FactRow.known_at, FactRow.id)).all()
    return [_row_to_fact(row) for row in rows]


def snapshot_at(session: Session, workspace_id: str, cutoff: datetime) -> snapshots.Snapshot:
    """The as-known snapshot at `cutoff`. Facts known after it are never even loaded.

    Anything a visible fact supersedes was known strictly earlier, so `known_by=cutoff`
    already contains every row the pure `snapshot_at` needs. Use `is_settled` before treating
    the result as final: a cutoff inside `SETTLE_HORIZON` of now is provisional.
    """
    return snapshots.snapshot_at(load_facts(session, workspace_id, known_by=cutoff), cutoff)


def load_coverage(session: Session, workspace_id: str, cutoff: datetime) -> dict[str, CoverageDecl]:
    """What each stock export known by `cutoff` declares it covers, keyed by artifact id.

    The gate needs this to tell a known zero from an unknown stock level. An artifact that
    was learned after the cutoff is never used, so a replay cannot see the future. A stored
    declaration that does not parse is left out: the gate then treats the quality as
    uncovered, which is the safe direction.
    """
    rows = session.scalars(
        select(DecisionSourceArtifact).where(
            DecisionSourceArtifact.workspace_id == workspace_id,
            DecisionSourceArtifact.known_at <= cutoff,
        )
    ).all()
    covered: dict[str, CoverageDecl] = {}
    for row in rows:
        if not row.coverage:
            continue
        try:
            covered[row.id] = CoverageDecl.model_validate(row.coverage)
        except ValidationError:
            continue
    return covered


# ---------------------------------------------------------------------------
# Decision evaluations and human decision records
# ---------------------------------------------------------------------------


class Reconstruction(FrozenModel):
    """Outcome of replaying a stored evaluation. A mismatch is data, never an exception."""

    evaluation_id: str
    stored_decision_digest: str
    recomputed_decision_digest: str
    snapshot_matches: bool
    policy_matches: bool
    matches: bool
    result: ReplayResult


def _find_evaluation(
    session: Session, workspace_id: str, result: ReplayResult, order_id: str, cutoff: datetime
) -> DecisionEvaluation | None:
    return session.scalar(
        select(DecisionEvaluation).where(
            DecisionEvaluation.workspace_id == workspace_id,
            DecisionEvaluation.order_id == order_id,
            DecisionEvaluation.cutoff == cutoff,
            DecisionEvaluation.policy_digest == result.policy_digest,
            DecisionEvaluation.engine_version == result.engine_version,
            DecisionEvaluation.snapshot_digest == result.snapshot_digest,
        )
    )


def find_evaluation(
    session: Session, workspace_id: str, result: ReplayResult, order_id: str, cutoff: datetime
) -> DecisionEvaluation | None:
    """The stored evaluation for this exact replay, if one exists."""
    return _find_evaluation(session, workspace_id, result, order_id, cutoff)


def _load_evaluation(session: Session, workspace_id: str, evaluation_id: str) -> DecisionEvaluation:
    row = session.scalar(
        select(DecisionEvaluation).where(
            DecisionEvaluation.workspace_id == workspace_id,
            DecisionEvaluation.id == evaluation_id,
        )
    )
    if row is None:
        raise ServiceError("EVALUATION_NOT_FOUND", "evaluation not found in this workspace", 404)
    return row


def evaluate_order(
    session: Session,
    workspace_id: str,
    order_id: str,
    cutoff: datetime,
    policy: PolicyDocument,
) -> DecisionEvaluation:
    """Replay one order as known at `cutoff` and store the result once per replay key.

    Pure replay only: no model provider is called. An unsettled cutoff is refused, because a
    late commit could still change the snapshot under a stored evaluation.
    """
    if policy.engine_version != ENGINE_VERSION:
        raise ServiceError("ENGINE_UNSUPPORTED", f"engine {policy.engine_version} is not supported", 422)
    if not is_settled(session, cutoff):  # also refuses a naive cutoff
        raise ServiceError("CUTOFF_NOT_SETTLED", "cutoff is too recent to store an evaluation", 422)
    snapshot = snapshot_at(session, workspace_id, cutoff)
    result = replay(snapshot, order_id, policy, load_coverage(session, workspace_id, cutoff))

    existing = _find_evaluation(session, workspace_id, result, order_id, cutoff)
    if existing is not None:
        return existing
    row = DecisionEvaluation(
        workspace_id=workspace_id,
        order_id=order_id,
        cutoff=cutoff,
        policy_digest=result.policy_digest,
        policy=policy.model_dump(mode="json"),
        engine_version=result.engine_version,
        snapshot_digest=result.snapshot_digest,
        decision_digest=result.decision_digest,
        outcome=result.recommendation.outcome.value,
        result=result.model_dump(mode="json"),
        created_at=db_now(session),
    )
    try:
        with session.begin_nested():
            session.add(row)
            session.flush()
    except IntegrityError as exc:
        # A concurrent writer stored the same replay key first; return that row.
        winner = _find_evaluation(session, workspace_id, result, order_id, cutoff)
        if winner is None:
            raise ServiceError("EVALUATION_REJECTED", "evaluation violates a stored-data constraint", 409) from exc
        return winner
    return row


def record_decision(
    session: Session,
    workspace_id: str,
    evaluation_id: str,
    decision: Recommendation,
    reason: str,
    actor: str,
) -> DecisionRecord:
    """Append a human final decision against a stored evaluation.

    Nothing is auto-accepted: a decision that differs from the engine outcome is an override,
    and an override needs a reason (the same text is stored as `override_reason`). An ACCEPT
    over a NEEDS_REVIEW recommendation is such an override.
    """
    evaluation = _load_evaluation(session, workspace_id, evaluation_id)
    recommended = Recommendation(evaluation.outcome)
    try:
        chosen = Recommendation(decision)
    except ValueError as exc:
        raise ServiceError("DECISION_INVALID", f"unknown decision {decision!r}", 422) from exc
    if not actor.strip():
        raise ServiceError("ACTOR_REQUIRED", "a decision needs an actor", 422)
    if len(actor) > 200:
        raise ServiceError("ACTOR_TOO_LONG", "actor must be 200 characters or fewer", 422)
    override = chosen is not recommended
    if not reason.strip():
        code = "OVERRIDE_REASON_REQUIRED" if override else "DECISION_REASON_REQUIRED"
        message = (
            f"deciding {chosen.value} against the engine's {recommended.value} needs a reason"
            if override
            else "a decision needs a reason"
        )
        raise ServiceError(code, message, 422)
    row = DecisionRecord(
        workspace_id=workspace_id,
        evaluation_id=evaluation.id,
        decision=chosen.value,
        recommended_outcome=recommended.value,
        override=override,
        reason=reason,
        override_reason=reason if override else None,
        actor=actor,
        created_at=db_now(session),
    )
    try:
        with session.begin_nested():
            session.add(row)
            session.flush()
    except IntegrityError as exc:
        raise ServiceError("DECISION_REJECTED", "decision violates a stored-data constraint", 409) from exc
    return row


def reconstruct(session: Session, workspace_id: str, evaluation_id: str) -> Reconstruction:
    """Reload the snapshot at the stored cutoff, replay with the stored policy, and compare.

    Returns a result for every stored evaluation; a digest mismatch is reported in the
    returned object and never raised.
    """
    evaluation = _load_evaluation(session, workspace_id, evaluation_id)
    policy = PolicyDocument.model_validate(evaluation.policy)
    policy_matches = policy_digest(policy) == evaluation.policy_digest
    snapshot = snapshot_at(session, workspace_id, evaluation.cutoff)
    coverage = load_coverage(session, workspace_id, evaluation.cutoff)
    result = replay(snapshot, evaluation.order_id, policy, coverage)
    snapshot_matches = result.snapshot_digest == evaluation.snapshot_digest
    decision_matches = result.decision_digest == evaluation.decision_digest
    return Reconstruction(
        evaluation_id=evaluation.id,
        stored_decision_digest=evaluation.decision_digest,
        recomputed_decision_digest=result.decision_digest,
        snapshot_matches=snapshot_matches,
        policy_matches=policy_matches,
        matches=policy_matches and snapshot_matches and decision_matches,
        result=result,
    )


# ---------------------------------------------------------------------------
# Regression cases, policy runs and owner adoption (T12)
# ---------------------------------------------------------------------------

ADOPTION_OWNER_ROLE = "owner"
"""The only workspace role that may adopt a policy (`WorkspaceMember.role`)."""


def _require_aware(cutoff: datetime) -> None:
    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
        raise ServiceError("CUTOFF_INVALID", "cutoff must carry a UTC offset", 422)


def create_case(
    session: Session,
    workspace_id: str,
    case_id: str,
    name: str,
    cutoff: datetime,
    order_id: str,
    facts: Sequence[Fact],
    coverage: Mapping[str, CoverageDecl],
    *,
    synthetic: bool,
) -> DecisionCase:
    """Freeze one order's facts and coverage as a regression case. Cases are never edited."""
    _require_aware(cutoff)
    _lock_suite(session, workspace_id)
    if not name.strip():
        raise ServiceError("CASE_NAME_REQUIRED", "a case needs a name", 422)
    if session.scalar(
        select(DecisionCase.id).where(DecisionCase.workspace_id == workspace_id, DecisionCase.id == case_id)
    ):
        raise ServiceError("CASE_EXISTS", f"case {case_id} already exists", 409)
    row = DecisionCase(
        workspace_id=workspace_id,
        id=case_id,
        name=name,
        cutoff=cutoff,
        order_id=order_id,
        facts=[fact.model_dump(mode="json") for fact in facts],
        coverage={key: decl.model_dump(mode="json") for key, decl in coverage.items()},
        synthetic=synthetic,
        created_at=db_now(session),
    )
    try:
        with session.begin_nested():
            session.add(row)
            session.flush()
    except IntegrityError as exc:
        raise ServiceError("CASE_REJECTED", "case violates a stored-data constraint", 409) from exc
    return row


def add_expectation(
    session: Session, workspace_id: str, case_id: str, expectation: Expectation
) -> CaseExpectation:
    """Append the next expectation revision for a case; earlier revisions are kept."""
    _lock_suite(session, workspace_id)
    if session.scalar(
        select(DecisionCase.id).where(DecisionCase.workspace_id == workspace_id, DecisionCase.id == case_id)
    ) is None:
        raise ServiceError("CASE_NOT_FOUND", "case not found in this workspace", 404)
    latest = session.scalar(
        select(func.max(CaseExpectation.revision)).where(
            CaseExpectation.workspace_id == workspace_id, CaseExpectation.case_id == case_id
        )
    )
    row = CaseExpectation(
        workspace_id=workspace_id,
        case_id=case_id,
        revision=(latest or 0) + 1,
        expectation=expectation.model_dump(mode="json"),
        created_at=db_now(session),
    )
    try:
        with session.begin_nested():
            session.add(row)
            session.flush()
    except IntegrityError as exc:
        raise ServiceError("EXPECTATION_RACE", "expectation revision written concurrently; retry", 409, retry_after=1) from exc
    return row


def _latest_expectation(session: Session, workspace_id: str, case_id: str) -> CaseExpectation | None:
    return session.scalar(
        select(CaseExpectation)
        .where(CaseExpectation.workspace_id == workspace_id, CaseExpectation.case_id == case_id)
        .order_by(CaseExpectation.revision.desc())
        .limit(1)
    )


def _suite(session: Session, workspace_id: str) -> list[tuple[DecisionCase, CaseExpectation | None]]:
    cases = session.scalars(
        select(DecisionCase).where(DecisionCase.workspace_id == workspace_id).order_by(DecisionCase.id)
    ).all()
    return [(case, _latest_expectation(session, workspace_id, case.id)) for case in cases]


def _suite_digest(suite: Sequence[tuple[DecisionCase, CaseExpectation | None]]) -> str:
    """Digest of every case, its frozen inputs and its latest expectation revision."""
    return decision_digest(
        {
            "cases": [
                {
                    "id": case.id,
                    "order_id": case.order_id,
                    "cutoff": case.cutoff.astimezone(UTC).isoformat(),
                    "facts": case.facts,
                    "coverage": case.coverage,
                    "expectation_revision": exp.revision if exp else None,
                    "expectation": exp.expectation if exp else None,
                }
                for case, exp in suite
            ]
        }
    )


def _store_policy(session: Session, workspace_id: str, policy: PolicyDocument) -> str:
    """Store a policy under its digest once; an existing digest is reused, never rewritten."""
    digest = policy_digest(policy)
    if session.scalar(
        select(StoredPolicy.id).where(StoredPolicy.workspace_id == workspace_id, StoredPolicy.policy_digest == digest)
    ) is not None:
        return digest
    if not policy.label.strip():
        raise ServiceError("POLICY_LABEL_REQUIRED", "a policy needs a label", 422)
    row = StoredPolicy(
        workspace_id=workspace_id,
        policy_digest=digest,
        label=policy.label,
        engine_version=policy.engine_version,
        policy=policy.model_dump(mode="json"),
        created_at=db_now(session),
    )
    try:
        with session.begin_nested():
            session.add(row)
            session.flush()
    except IntegrityError as exc:
        # A concurrent writer may have stored the same digest first; anything else is refused.
        if session.scalar(
            select(StoredPolicy.id).where(StoredPolicy.workspace_id == workspace_id, StoredPolicy.policy_digest == digest)
        ) is None:
            raise ServiceError("POLICY_REJECTED", "policy violates a stored-data constraint", 409) from exc
    return digest


class CaseRun(FrozenModel):
    """One case replayed under one policy. `verdict` is None when the case could not be judged."""

    verdict: Verdict | None
    outcome: str | None
    failures: tuple[str, ...]
    decision_digest: str | None
    error: str | None


def _run_case(case: DecisionCase, expectation: CaseExpectation | None, policy: PolicyDocument) -> CaseRun:
    if expectation is None:
        return CaseRun(verdict=None, outcome=None, failures=(), decision_digest=None, error="NO_EXPECTATION")
    try:
        snapshot = snapshots.snapshot_at(
            [Fact.model_validate(item) for item in case.facts], case.cutoff
        )
        coverage = {key: CoverageDecl.model_validate(value) for key, value in case.coverage.items()}
        result = replay(snapshot, case.order_id, policy, coverage)
        judged = evaluate_expectation(
            Expectation.model_validate(expectation.expectation),
            result.recommendation.outcome,
            tuple(finding.code for finding in result.gate.findings),
        )
    except Exception as exc:  # any failure to judge a case makes the whole run incomplete
        return CaseRun(
            verdict=None,
            outcome=None,
            failures=(),
            decision_digest=None,
            error=f"{type(exc).__name__}: {exc}",
        )
    return CaseRun(
        verdict=judged.verdict,
        outcome=result.recommendation.outcome.value,
        failures=judged.failures,
        decision_digest=result.decision_digest,
        error=None,
    )


def run_regression(
    session: Session,
    workspace_id: str,
    baseline: PolicyDocument,
    candidate: PolicyDocument,
) -> RegressionRun:
    """Evaluate EVERY case in the workspace suite under both policies and store the comparison.

    A case with no expectation, a replay error or a missing verdict makes the run INCOMPLETE:
    it is still stored (so the attempt is on record) but it can never be adopted.
    """
    _lock_suite(session, workspace_id)
    baseline_digest = _store_policy(session, workspace_id, baseline)
    candidate_digest = _store_policy(session, workspace_id, candidate)
    suite = _suite(session, workspace_id)
    suite_digest = _suite_digest(suite)

    baseline_runs = {case.id: _run_case(case, exp, baseline) for case, exp in suite}
    candidate_runs = {case.id: _run_case(case, exp, candidate) for case, exp in suite}
    comparisons = {
        item.case_id: item.classification
        for item in compare_cases(
            {cid: run.verdict for cid, run in baseline_runs.items()},
            {cid: run.verdict for cid, run in candidate_runs.items()},
            baseline_suite_digest=suite_digest,
            candidate_suite_digest=suite_digest,
        )
    }
    results = [
        {
            "case_id": case.id,
            "classification": comparisons[case.id].value,
            "baseline": baseline_runs[case.id].model_dump(mode="json"),
            "candidate": candidate_runs[case.id].model_dump(mode="json"),
        }
        for case, _ in suite
    ]
    complete = bool(results) and all(
        item["classification"] != Classification.NOT_COMPARABLE.value for item in results
    )
    row = RegressionRun(
        workspace_id=workspace_id,
        baseline_policy_digest=baseline_digest,
        candidate_policy_digest=candidate_digest,
        suite_digest=suite_digest,
        results=results,
        status="COMPLETE" if complete else "INCOMPLETE",
        complete=complete,
        created_at=db_now(session),
    )
    session.add(row)
    session.flush()
    return row


def _written(text: object) -> bool:
    return isinstance(text, str) and bool(text.strip())


def adopt_policy(
    session: Session,
    workspace_id: str,
    regression_run_id: str,
    actor_role: str,
    acknowledgements: Mapping[str, str],
    actor: str,
) -> PolicyAdoption:
    """Adopt the run's candidate policy. Owner only; never mutates any stored policy.

    Refused unless the run is COMPLETE, the suite is unchanged since the run, the candidate
    policy stored under the run's digest still hashes to it, no case is NOT_COMPARABLE, and every
    REGRESSION case has a non-blank written acknowledgement keyed by its case id.
    """
    if actor_role != ADOPTION_OWNER_ROLE:
        raise ServiceError("ADOPTION_FORBIDDEN", "only the workspace owner can adopt a policy", 403)
    if not actor.strip():
        raise ServiceError("ACTOR_REQUIRED", "an adoption needs an actor", 422)
    if len(actor) > 200:
        raise ServiceError("ACTOR_TOO_LONG", "actor must be 200 characters or fewer", 422)
    _lock_suite(session, workspace_id)
    run = session.scalar(
        select(RegressionRun).where(
            RegressionRun.workspace_id == workspace_id, RegressionRun.id == regression_run_id
        )
    )
    if run is None:
        raise ServiceError("RUN_NOT_FOUND", "regression run not found in this workspace", 404)
    if session.scalar(
        select(PolicyAdoption.id).where(
            PolicyAdoption.workspace_id == workspace_id, PolicyAdoption.regression_run_id == run.id
        )
    ):
        raise ServiceError("RUN_ALREADY_ADOPTED", "this regression run was already adopted", 409)
    if not run.complete or run.status != "COMPLETE":
        raise ServiceError("RUN_INCOMPLETE", "an incomplete regression run cannot be adopted", 409)
    if _suite_digest(_suite(session, workspace_id)) != run.suite_digest:
        raise ServiceError("SUITE_CHANGED", "the suite changed after this run; run it again", 409)
    stored = session.scalar(
        select(StoredPolicy).where(
            StoredPolicy.workspace_id == workspace_id,
            StoredPolicy.policy_digest == run.candidate_policy_digest,
        )
    )
    if stored is None or policy_digest(PolicyDocument.model_validate(stored.policy)) != run.candidate_policy_digest:
        raise ServiceError("POLICY_DIGEST_MISMATCH", "the candidate policy does not match the run", 409)

    regression_ids: list[str] = []
    for item in run.results:
        if item["classification"] == Classification.NOT_COMPARABLE.value:
            raise ServiceError(
                "NOT_COMPARABLE_BLOCKS_ADOPTION",
                f"case {item['case_id']} is not comparable; the run cannot be adopted",
                409,
            )
        if item["classification"] == Classification.REGRESSION.value:
            regression_ids.append(item["case_id"])
    unexpected = sorted(set(acknowledgements) - set(regression_ids))
    if unexpected:
        raise ServiceError(
            "ACKNOWLEDGEMENT_UNEXPECTED",
            f"acknowledgements given for cases that did not regress: {', '.join(unexpected)}",
            422,
        )
    missing = [cid for cid in sorted(regression_ids) if not _written(acknowledgements.get(cid))]
    if missing:
        raise ServiceError(
            "ACKNOWLEDGEMENT_REQUIRED",
            f"regressed cases need a written acknowledgement: {', '.join(missing)}",
            409,
        )

    row = PolicyAdoption(
        workspace_id=workspace_id,
        regression_run_id=run.id,
        run_complete=True,
        policy_digest=run.candidate_policy_digest,
        adopted_by=actor,
        acknowledgements={cid: acknowledgements[cid] for cid in regression_ids},
        created_at=db_now(session),
    )
    try:
        with session.begin_nested():
            session.add(row)
            session.flush()
    except IntegrityError as exc:
        raise ServiceError("ADOPTION_REJECTED", "adoption violates a stored-data constraint", 409) from exc
    return row


# ---------------------------------------------------------------------------
# Read and store helpers for the HTTP layer (T13). Read-only except `store_policy`.
# ---------------------------------------------------------------------------

ORDER_KEY_PREFIX = "order:"


def list_order_ids(session: Session, workspace_id: str) -> list[str]:
    """Every order id that has an order_request fact in this workspace, sorted."""
    keys = session.scalars(
        select(FactRow.entity_key)
        .where(
            FactRow.workspace_id == workspace_id,
            FactRow.kind == FactKind.ORDER_REQUEST.value,
        )
        .distinct()
        .order_by(FactRow.entity_key)
    ).all()
    return [key.removeprefix(ORDER_KEY_PREFIX) for key in keys]


def order_facts(snapshot: snapshots.Snapshot, order_id: str) -> list[Fact]:
    """The order's own visible facts in a snapshot (its order_request entity)."""
    return [fact for fact in snapshot.facts if fact.entity_key == ORDER_KEY_PREFIX + order_id]


def load_evaluation(session: Session, workspace_id: str, evaluation_id: str) -> DecisionEvaluation:
    return _load_evaluation(session, workspace_id, evaluation_id)


def load_regression_run(session: Session, workspace_id: str, run_id: str) -> RegressionRun:
    row = session.scalar(
        select(RegressionRun).where(RegressionRun.workspace_id == workspace_id, RegressionRun.id == run_id)
    )
    if row is None:
        raise ServiceError("RUN_NOT_FOUND", "regression run not found in this workspace", 404)
    return row


def list_stored_policies(session: Session, workspace_id: str) -> list[StoredPolicy]:
    return list(
        session.scalars(
            select(StoredPolicy)
            .where(StoredPolicy.workspace_id == workspace_id)
            .order_by(StoredPolicy.created_at, StoredPolicy.policy_digest)
        ).all()
    )


def load_policy(session: Session, workspace_id: str, digest: str) -> PolicyDocument:
    row = session.scalar(
        select(StoredPolicy).where(
            StoredPolicy.workspace_id == workspace_id, StoredPolicy.policy_digest == digest
        )
    )
    if row is None:
        raise ServiceError("POLICY_UNKNOWN", "policy not found in this workspace", 404)
    return PolicyDocument.model_validate(row.policy)


def store_policy(session: Session, workspace_id: str, policy: PolicyDocument) -> str:
    """Store a policy under its digest (idempotent) and return the digest."""
    return _store_policy(session, workspace_id, policy)


def adopted_policy_digest(session: Session, workspace_id: str) -> str:
    """The most recently adopted policy, or the built-in default if none was ever adopted."""
    latest = session.scalar(
        select(PolicyAdoption.policy_digest)
        .where(PolicyAdoption.workspace_id == workspace_id)
        .order_by(PolicyAdoption.created_at.desc(), PolicyAdoption.id.desc())
        .limit(1)
    )
    return latest if latest is not None else policy_digest(DEFAULT_POLICY_V1)


def resolve_policy(session: Session, workspace_id: str, digest: str | None) -> PolicyDocument:
    """The policy a request names; no name means the adopted policy. The default needs no row."""
    wanted = digest if digest is not None else adopted_policy_digest(session, workspace_id)
    if wanted == policy_digest(DEFAULT_POLICY_V1):
        return DEFAULT_POLICY_V1
    return load_policy(session, workspace_id, wanted)
