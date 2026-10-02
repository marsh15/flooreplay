"""Application service: load pinned artifacts, execute, persist.

Short transactions only: create the attempt, commit, execute the engine
with no transaction open, then atomically persist the result, evaluation,
and completion state. Idempotency is enforced by a database unique key,
not an in-memory dictionary.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .domain import evaluation
from .domain.engine import EngineError, run_replay
from .domain.hashing import digest
from .domain.types import (
    Catalog,
    ConstraintCode,
    CoverageTarget,
    DomainOutcome,
    GateFreshnessSettings,
    IssueCode,
    ReplayRequestContext,
    Snapshot,
    UnavailabilityEvent,
)
from .importing import ImportPreview, build_snapshot
from .models import (
    CatalogRevision,
    ComparisonReport,
    ExecutionConfiguration,
    ExpectationRevision,
    ImportAudit,
    ReplayAttempt,
    ReviewCheck,
    ScenarioRevision,
    SourceSnapshot,
    SuiteRevision,
)


class ServiceError(Exception):
    def __init__(
        self, code: str, message: str, http_status: int = 400, retry_after: int | None = None
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.retry_after = retry_after


def _load_context(session: Session, scenario: ScenarioRevision) -> ReplayRequestContext:
    catalog_row = session.get(CatalogRevision, scenario.catalog_revision_id)
    if catalog_row is None:
        raise ServiceError("PINNED_ARTIFACT_MISSING", "Pinned catalog revision is missing", 500)
    snapshots: list[Snapshot] = []
    for snap_id in scenario.pinned_snapshot_ids:
        row = session.get(SourceSnapshot, snap_id)
        if row is None:
            raise ServiceError("PINNED_ARTIFACT_MISSING", f"Pinned snapshot {snap_id} is missing", 500)
        snapshots.append(Snapshot.model_validate(row.payload))
    return ReplayRequestContext(
        catalog=Catalog.model_validate(catalog_row.payload),
        snapshots=tuple(snapshots),
        event=UnavailabilityEvent.model_validate(scenario.event),
        decision_at=scenario.decision_at,
        target=CoverageTarget.model_validate(scenario.target),
    )


def _manifest_digest(
    scenario: ScenarioRevision,
    configuration: ExecutionConfiguration,
    catalog_row: CatalogRevision,
    snapshots: list[SourceSnapshot],
    expectation: ExpectationRevision | None,
) -> str:
    return digest(
        {
            "scenario": {"id": scenario.scenario_id, "revision": scenario.revision},
            "catalog": {"id": catalog_row.id, "digest": catalog_row.content_digest},
            "snapshots": [{"id": s.id, "digest": s.content_digest} for s in snapshots],
            "configuration": {
                "id": configuration.id,
                "policy_kind": configuration.policy_kind,
                "settings": configuration.settings,
            },
            "expectation": expectation.assertions if expectation is not None else None,
            "build_id": settings.build_id,
        }
    )


def _expectation_from(assertions: dict[str, Any]) -> evaluation.Expectation:
    expected = assertions.get("expected_outcome")
    return evaluation.Expectation(
        expected_outcome=DomainOutcome(str(expected)) if expected else None,
        required_issue_codes=tuple(
            IssueCode(c) for c in assertions.get("required_issue_codes", [])
        ),
        required_failed_constraints=tuple(
            ConstraintCode(c) for c in assertions.get("required_failed_constraints", [])
        ),
        required_passed_constraints=tuple(
            ConstraintCode(c) for c in assertions.get("required_passed_constraints", [])
        ),
        forbidden_operators=tuple(assertions.get("forbidden_operators", [])),
        allowed_operators=tuple(assertions.get("allowed_operators", [])),
        required_operator=assertions.get("required_operator"),
        policy_execution_permitted=assertions.get("policy_execution_permitted"),
    )


def _workspace_request_key(workspace_id: str, key: str, operation: str) -> str:
    if workspace_id == "public-demo":
        from .workspaces import allowed_workspaces
        if allowed_workspaces.get() is None:
            return key
    return operation + "-" + digest({"workspace": workspace_id, "key": key, "operation": operation})


def execute_replay(
    session: Session,
    scenario_id: str,
    scenario_revision: int,
    configuration_id: str,
    idempotency_key: str,
) -> ReplayAttempt:
    scenario = session.get(ScenarioRevision, (scenario_id, scenario_revision))
    if scenario is None:
        raise ServiceError("SCENARIO_UNKNOWN", "Unknown scenario revision", 404)
    configuration = session.get(ExecutionConfiguration, configuration_id)
    if configuration is None:
        raise ServiceError("CONFIGURATION_UNKNOWN", "Unknown execution configuration", 404)

    idempotency_key = _workspace_request_key(scenario.workspace_id, idempotency_key, "replay")
    request_payload = {
        "scenario_id": scenario_id,
        "scenario_revision": scenario_revision,
        "configuration_id": configuration_id,
    }
    existing = session.execute(
        select(ReplayAttempt).where(ReplayAttempt.idempotency_key == idempotency_key)
    ).scalar_one_or_none()
    if existing is not None:
        if existing.request_payload != request_payload:
            raise ServiceError(
                "IDEMPOTENCY_CONFLICT",
                "This idempotency key was used with a different request.",
                409,
            )
        return existing

    attempt = ReplayAttempt(
        workspace_id=scenario.workspace_id, idempotency_key=idempotency_key,
        scenario_id=scenario_id,
        scenario_revision=scenario_revision,
        configuration_id=configuration_id,
        lifecycle="RUNNING",
        request_payload=request_payload,
    )
    session.add(attempt)
    session.commit()  # the attempt exists before execution; restarts can mark it INTERRUPTED
    started = time.monotonic()

    try:
        ctx = _load_context(session, scenario)
        catalog_row = session.get(CatalogRevision, scenario.catalog_revision_id)
        assert catalog_row is not None
        snapshot_rows = [
            session.get(SourceSnapshot, snap_id) for snap_id in scenario.pinned_snapshot_ids
        ]
        assert all(isinstance(r, SourceSnapshot) for r in snapshot_rows)
        expectation = session.execute(
            select(ExpectationRevision).where(
                ExpectationRevision.scenario_id == scenario_id,
                ExpectationRevision.revision == scenario_revision,
                ExpectationRevision.configuration_id == configuration_id,
            )
        ).scalar_one_or_none()

        gate_settings = GateFreshnessSettings.model_validate(configuration.settings)
        run = run_replay(ctx, gate_settings, configuration.policy_kind)
        result_payload = run.outcome.model_dump(mode="json")

        verdict = None
        failures: list[str] = []
        if expectation is not None:
            v = evaluation.evaluate(run.outcome, _expectation_from(expectation.assertions))
            verdict = v.verdict.value
            failures = list(v.failures)

        attempt.result = result_payload
        attempt.domain_outcome = run.outcome.outcome.value
        attempt.expectation_verdict = verdict
        attempt.expectation_failures = failures
        attempt.context_digest = run.outcome.context_digest
        attempt.manifest_digest = _manifest_digest(
            scenario, configuration, catalog_row, snapshot_rows, expectation  # type: ignore[arg-type]
        )
        attempt.lifecycle = "COMPLETED"
        attempt.completed_at = datetime.now(UTC)
        attempt.elapsed_ms = round((time.monotonic() - started) * 1000)
        session.commit()
    except EngineError as exc:
        attempt.lifecycle = "ERRORED"
        attempt.result = {"execution_error": {"code": exc.code, "message": str(exc)}}
        attempt.completed_at = datetime.now(UTC)
        attempt.elapsed_ms = round((time.monotonic() - started) * 1000)
        session.commit()
        raise ServiceError(exc.code, str(exc), 500) from exc
    return attempt


def latest_attempt_summaries(session: Session) -> list[dict[str, Any]]:
    """Latest attempt per scenario revision and configuration, for the library."""
    attempts = session.execute(
        select(ReplayAttempt)
        .where(ReplayAttempt.lifecycle == "COMPLETED")
        .order_by(ReplayAttempt.created_at)
    ).scalars().all()
    latest: dict[tuple[str, int, str], ReplayAttempt] = {}
    for attempt in attempts:
        latest[(attempt.scenario_id, attempt.scenario_revision, attempt.configuration_id)] = attempt
    return [
        {
            "scenario_id": a.scenario_id,
            "scenario_revision": a.scenario_revision,
            "configuration_id": a.configuration_id,
            "domain_outcome": a.domain_outcome,
            "expectation_verdict": a.expectation_verdict,
            "created_at": a.created_at.isoformat(),
        }
        for a in latest.values()
    ]


def recover_interrupted(session: Session) -> int:
    """Mark replay attempts stuck in RUNNING as INTERRUPTED.

    execute_replay commits the attempt as RUNNING before execution starts, so
    a process that dies mid-execution leaves such rows behind. Recovery runs
    at application startup: the machinery never finished, and INTERRUPTED is
    the honest lifecycle for that. completed_at stays empty — it never
    completed. Idempotent by definition; returns how many rows it marked.
    """
    stuck = (
        session.execute(
            select(ReplayAttempt).where(ReplayAttempt.lifecycle == "RUNNING")
        )
        .scalars()
        .all()
    )
    for attempt in stuck:
        attempt.lifecycle = "INTERRUPTED"
    if stuck:
        session.commit()
    return len(stuck)


def latest_saved_attempt(
    session: Session, scenario_id: str, revision: int, configuration_id: str
) -> ReplayAttempt:
    """The most recent COMPLETED attempt for an exact selection, for the
    saved-report fallback. A saved report is always labeled as saved; it is
    never presented as a fresh execution."""
    attempt = session.execute(
        select(ReplayAttempt)
        .where(
            ReplayAttempt.scenario_id == scenario_id,
            ReplayAttempt.scenario_revision == revision,
            ReplayAttempt.configuration_id == configuration_id,
            ReplayAttempt.lifecycle == "COMPLETED",
        )
        .order_by(ReplayAttempt.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if attempt is None:
        raise ServiceError(
            "NO_SAVED_REPORT",
            "No completed replay is saved for this selection yet.",
            404,
        )
    return attempt


def publish_import(session: Session, preview: ImportPreview, raw_text: str) -> dict[str, Any]:
    """Atomically persist the snapshot and its audit record.

    Idempotent by preview digest: republishing the exact preview returns the
    existing snapshot without creating anything.
    """
    snapshot = build_snapshot(preview)  # raises on blocking issues: all-or-nothing
    from .workspaces import write_workspace
    workspace_id = write_workspace.get() or "public-demo"
    audit_id = _workspace_request_key(workspace_id, preview.preview_digest, "import")
    if workspace_id != "public-demo":
        snapshot = snapshot.model_copy(update={"id": "snapshot-" + digest({"workspace": workspace_id, "digest": preview.preview_digest})[-55:]})

    existing_audit = session.get(ImportAudit, audit_id)
    if existing_audit is not None:
        existing_snapshot = session.get(SourceSnapshot, existing_audit.snapshot_id)
        if existing_snapshot is None:
            raise ServiceError(
                "IMPORT_INCONSISTENT",
                "Audit record references a missing snapshot.",
                500,
            )
        return {
            "snapshot_id": existing_snapshot.id,
            "already_published": True,
            "content_digest": existing_snapshot.content_digest,
        }

    existing_snapshot = session.get(SourceSnapshot, snapshot.id)
    if existing_snapshot is not None and existing_snapshot.content_digest == snapshot.content_digest:
        session.add(
            ImportAudit(
                workspace_id=workspace_id, preview_digest=audit_id,
                profile_id=preview.profile_id,
                snapshot_id=snapshot.id,
                raw_digest=preview.raw_digest,
                raw_bytes=raw_text.encode("utf-8"),
                row_count=len(preview.rows),
                blocking_issue_count=preview.blocking_count,
                warning_issue_count=preview.warning_count,
                declared_evidence_at=snapshot.declared_evidence_at,
                coverage_complete=preview.coverage_complete,
                scope=preview.scope,
            )
        )
        session.commit()
        return {
            "snapshot_id": snapshot.id,
            "already_published": True,
            "content_digest": snapshot.content_digest,
        }

    payload = snapshot.model_dump(mode="json")
    session.add(
        SourceSnapshot(
            workspace_id=workspace_id, id=snapshot.id,
            kind=snapshot.kind.value,
            source_system=snapshot.source_system,
            scope=snapshot.scope,
            declared_evidence_at=snapshot.declared_evidence_at,
            coverage_complete=snapshot.coverage_complete,
            content_digest=snapshot.content_digest,
            payload=payload,
        )
    )
    session.flush()  # the audit's foreign key needs the snapshot row first
    session.add(
        ImportAudit(
            workspace_id=workspace_id, preview_digest=audit_id,
            profile_id=preview.profile_id,
            snapshot_id=snapshot.id,
            raw_digest=preview.raw_digest,
            raw_bytes=raw_text.encode("utf-8"),
            row_count=len(preview.rows),
            blocking_issue_count=preview.blocking_count,
            warning_issue_count=preview.warning_count,
            declared_evidence_at=snapshot.declared_evidence_at,
            coverage_complete=preview.coverage_complete,
            scope=preview.scope,
        )
    )
    session.commit()
    return {
        "snapshot_id": snapshot.id,
        "already_published": False,
        "content_digest": snapshot.content_digest,
    }


def fork_scenario(
    session: Session, scenario_id: str, revision: int, replacement_snapshot_id: str
) -> ScenarioRevision:
    """Create a new scenario revision that swaps one pinned snapshot.

    The original revision is untouched: corrections create revisions, they
    never rewrite history. Expectations carry over so the fork is
    immediately evaluable against the same behavioral demands.
    """
    source = session.get(ScenarioRevision, (scenario_id, revision))
    if source is None:
        raise ServiceError("SCENARIO_UNKNOWN", "Unknown scenario revision", 404)
    replacement = session.get(SourceSnapshot, replacement_snapshot_id)
    if replacement is None:
        raise ServiceError("SNAPSHOT_UNKNOWN", "Unknown snapshot", 404)

    same_kind_ids = [
        sid for sid in source.pinned_snapshot_ids
        if (row := session.get(SourceSnapshot, sid)) is not None and row.kind == replacement.kind
    ]
    if not same_kind_ids:
        raise ServiceError(
            "FORK_KIND_MISMATCH",
            f"Scenario {scenario_id}@{revision} pins no {replacement.kind.lower()} snapshot to "
            f"replace with {replacement_snapshot_id}.",
            422,
        )

    new_pinned = [
        replacement_snapshot_id if sid == same_kind_ids[0] else sid
        for sid in source.pinned_snapshot_ids
    ]

    from .workspaces import write_workspace
    workspace_id = write_workspace.get() or source.workspace_id
    fork_id = scenario_id
    if workspace_id != "public-demo" and source.workspace_id != workspace_id:
        fork_id = "scenario-" + digest({"workspace": workspace_id, "origin": scenario_id})[-55:]
    latest = (
        session.execute(
            select(ScenarioRevision.revision).where(ScenarioRevision.scenario_id == fork_id)
        )
        .scalars()
        .all()
    )
    new_revision = max(latest or [revision]) + 1

    tags = list(source.tags)
    if fork_id != scenario_id:
        tags.append(f"origin:{scenario_id}@{revision}")
    if "imported-evidence" not in tags:
        tags.append("imported-evidence")
    fork = ScenarioRevision(
        workspace_id=workspace_id, scenario_id=fork_id,
        revision=new_revision,
        title=source.title,
        tags=tags,
        defect_statement=source.defect_statement
        + f" Forked at revision {new_revision} with imported {replacement.kind.lower()} "
        f"snapshot {replacement_snapshot_id}.",
        event=dict(source.event),
        decision_at=source.decision_at,
        target=dict(source.target),
        catalog_revision_id=source.catalog_revision_id,
        pinned_snapshot_ids=new_pinned,
    )
    session.add(fork)

    expectations = session.execute(
        select(ExpectationRevision).where(
            ExpectationRevision.scenario_id == scenario_id,
            ExpectationRevision.revision == revision,
        )
    ).scalars().all()
    for exp in expectations:
        session.add(
            ExpectationRevision(
                workspace_id=workspace_id, scenario_id=fork_id,
                revision=new_revision,
                configuration_id=exp.configuration_id,
                assertions=dict(exp.assertions),
            )
        )
    session.commit()
    return fork


CLASSIFICATIONS = ("UNCHANGED_PASS", "FIXED", "REGRESSION", "UNCHANGED_FAIL", "NOT_COMPARABLE")


def _classify(baseline_verdict: str, candidate_verdict: str) -> str:
    if baseline_verdict == "PASS" and candidate_verdict == "PASS":
        return "UNCHANGED_PASS"
    if baseline_verdict == "FAIL" and candidate_verdict == "PASS":
        return "FIXED"
    if baseline_verdict == "PASS" and candidate_verdict == "FAIL":
        return "REGRESSION"
    return "UNCHANGED_FAIL"


def _run_one(
    session: Session,
    scenario: ScenarioRevision,
    configuration: ExecutionConfiguration,
) -> dict[str, Any]:
    ctx = _load_context(session, scenario)
    gate_settings = GateFreshnessSettings.model_validate(configuration.settings)
    run = run_replay(ctx, gate_settings, configuration.policy_kind)
    expectation = session.execute(
        select(ExpectationRevision).where(
            ExpectationRevision.scenario_id == scenario.scenario_id,
            ExpectationRevision.revision == scenario.revision,
            ExpectationRevision.configuration_id == configuration.id,
        )
    ).scalar_one_or_none()
    verdict = "NOT_EVALUATED"
    failures: list[str] = []
    if expectation is not None:
        v = evaluation.evaluate(run.outcome, _expectation_from(expectation.assertions))
        verdict = v.verdict.value
        failures = list(v.failures)
    return {
        "outcome": run.outcome.outcome.value,
        "verdict": verdict,
        "operator": run.outcome.proposal.operator_id if run.outcome.proposal else None,
        "issue_codes": sorted({i.code.value for i in run.outcome.gate_issues}),
        "failures": failures,
    }


def run_comparison(
    session: Session,
    suite_id: str,
    baseline_config_id: str,
    candidate_config_id: str,
    idempotency_key: str,
) -> ComparisonReport:
    if baseline_config_id == candidate_config_id:
        raise ServiceError(
            "COMPARISON_CONFIGS_IDENTICAL",
            "Baseline and candidate configurations must differ.",
            422,
        )
    suite = session.get(SuiteRevision, suite_id)
    if suite is None:
        raise ServiceError("SUITE_UNKNOWN", "Unknown suite revision", 404)
    baseline_cfg = session.get(ExecutionConfiguration, baseline_config_id)
    candidate_cfg = session.get(ExecutionConfiguration, candidate_config_id)
    if baseline_cfg is None or candidate_cfg is None:
        raise ServiceError("CONFIGURATION_UNKNOWN", "Unknown execution configuration", 404)

    idempotency_key = _workspace_request_key(suite.workspace_id, idempotency_key, "comparison")
    request_payload = {
        "suite_id": suite_id,
        "baseline_config_id": baseline_config_id,
        "candidate_config_id": candidate_config_id,
    }
    existing = session.execute(
        select(ComparisonReport).where(ComparisonReport.idempotency_key == idempotency_key)
    ).scalar_one_or_none()
    if existing is not None:
        same_request = (
            existing.suite_id == suite_id
            and existing.baseline_config_id == baseline_config_id
            and existing.candidate_config_id == candidate_config_id
        )
        if not same_request:
            raise ServiceError(
                "IDEMPOTENCY_CONFLICT",
                "This idempotency key was used with a different comparison request.",
                409,
            )
        return existing
    _ = request_payload  # documented request identity, mirrored by the columns above

    deadline = time.monotonic() + settings.suite_budget_seconds
    items: list[dict[str, Any]] = []
    totals = {"fixed": 0, "regression": 0, "unchanged_pass": 0, "unchanged_fail": 0}
    interrupted = False

    for suite_item in suite.items:
        if time.monotonic() > deadline:
            interrupted = True
            break
        scenario = session.get(ScenarioRevision, (suite_item["scenario_id"], suite_item["revision"]))
        if scenario is None:
            raise ServiceError(
                "SUITE_MEMBER_MISSING",
                f"Suite member {suite_item['scenario_id']} is missing from the database.",
                500,
            )
        base = _run_one(session, scenario, baseline_cfg)
        cand = _run_one(session, scenario, candidate_cfg)
        classification = _classify(base["verdict"], cand["verdict"])
        behavior_changed = (
            base["verdict"] == "PASS"
            and cand["verdict"] == "PASS"
            and base["outcome"] != cand["outcome"]
        ) or (
            base["verdict"] == "PASS"
            and cand["verdict"] == "PASS"
            and base["operator"] != cand["operator"]
        )
        totals_key = classification.lower()
        if totals_key in totals:
            totals[totals_key] += 1
        items.append(
            {
                "scenario_id": scenario.scenario_id,
                "title": suite_item.get("title", scenario.title),
                "category": suite_item.get("category", ""),
                "defect_statement": suite_item.get("defect_statement", scenario.defect_statement),
                "baseline": base,
                "candidate": cand,
                "classification": classification,
                "behavior_changed": behavior_changed,
            }
        )

    manifest_digest = digest(
        {
            "suite": {"id": suite.id, "revision": suite.revision, "digest": suite.content_digest},
            "baseline": {"id": baseline_cfg.id, "settings": baseline_cfg.settings},
            "candidate": {"id": candidate_cfg.id, "settings": candidate_cfg.settings},
            "build_id": settings.build_id,
        }
    )
    report = ComparisonReport(
        workspace_id=suite.workspace_id, idempotency_key=idempotency_key,
        suite_id=suite.id,
        suite_revision=suite.revision,
        baseline_config_id=baseline_config_id,
        candidate_config_id=candidate_config_id,
        status="INTERRUPTED" if interrupted else "COMPLETED",
        items=items,
        totals={**totals, "completed": len(items), "total": len(suite.items)},
        manifest_digest=manifest_digest,
    )
    session.add(report)
    session.commit()
    return report


# ---------------------------------------------------------------------------
# Later-context review
# ---------------------------------------------------------------------------

_REVIEW_OUTCOMES = ("STILL_SUPPORTED", "STALE_RECOMMENDATION", "BLOCKED_CONTEXT")


def _changed_paths(left: object, right: object, prefix: str = "") -> list[str]:
    """Paths at which two canonical payloads differ, for human inspection."""
    from .domain.hashing import canonical_json

    try:
        left_json = canonical_json(left)
        right_json = canonical_json(right)
    except ValueError:
        return [prefix or "<unserializable>"]
    if left_json == right_json:
        return []
    if isinstance(left, dict) and isinstance(right, dict):
        paths: list[str] = []
        for key in sorted(set(left) | set(right)):
            child = f"{prefix}.{key}" if prefix else str(key)
            if key not in left or key not in right or left[key] != right[key]:
                paths.extend(_changed_paths(left.get(key), right.get(key), child))
        return paths
    if isinstance(left, list) and isinstance(right, list):
        paths = []
        for index in range(max(len(left), len(right))):
            child = f"{prefix}[{index}]"
            l_item = left[index] if index < len(left) else None
            r_item = right[index] if index < len(right) else None
            if l_item != r_item:
                paths.extend(_changed_paths(l_item, r_item, child))
        if len(left) != len(right):
            paths.append(f"{prefix}[length]")
        return paths
    return [prefix or "<value>"]


def _path_reason_codes(paths: list[str]) -> list[str]:
    codes = set()
    for path in paths:
        head = path.split(".")[0].split("[")[0]
        if head == "snapshots":
            codes.add("EVIDENCE_CHANGED")
        elif head == "event":
            codes.add("EVENT_CHANGED")
        elif head == "decision_at":
            codes.add("DECISION_TIME_CHANGED")
        elif head == "target":
            codes.add("TARGET_CHANGED")
        elif head == "catalog":
            codes.add("CATALOG_CHANGED")
    return sorted(codes)


def review_check(
    session: Session,
    original_replay_id: str,
    target_scenario_id: str,
    target_revision: int,
) -> dict[str, Any]:
    """Check an earlier proposal against an explicit later scenario.

    Never alters the original replay. The original result stands; this
    records whether the later context still supports it."""
    original = session.get(ReplayAttempt, original_replay_id)
    if original is None or original.lifecycle != "COMPLETED" or not original.result:
        raise ServiceError("REPLAY_UNKNOWN", "Original replay not found or not completed", 404)
    original_result = original.result
    proposal_payload = original_result.get("proposal") if isinstance(original_result, dict) else None
    if not proposal_payload:
        raise ServiceError(
            "REVIEW_INCOMPATIBLE",
            "Only a replay that produced a proposal can be reviewed against later context.",
            422,
        )
    original_scenario = session.get(ScenarioRevision, (original.scenario_id, original.scenario_revision))
    target_scenario = session.get(ScenarioRevision, (target_scenario_id, target_revision))
    if original_scenario is None or target_scenario is None:
        raise ServiceError("SCENARIO_UNKNOWN", "Unknown scenario revision", 404)
    if (
        original_scenario.target.get("slot_id") != target_scenario.target.get("slot_id")
        or original_scenario.target.get("line_id") != target_scenario.target.get("line_id")
    ):
        raise ServiceError(
            "REVIEW_INCOMPATIBLE",
            "The target scenario describes a different episode or slot.",
            422,
        )

    configuration = session.get(ExecutionConfiguration, original.configuration_id)
    if configuration is None:
        raise ServiceError("CONFIGURATION_UNKNOWN", "Original configuration is missing", 500)

    target_ctx = _load_context(session, target_scenario)
    gate_settings = GateFreshnessSettings.model_validate(configuration.settings)
    run = run_replay(target_ctx, gate_settings, configuration.policy_kind)

    gate_issues = [i.model_dump(mode="json") for i in run.outcome.gate_issues]

    if run.outcome.outcome in (DomainOutcome.NEEDS_CONTEXT, DomainOutcome.CONFLICTING_CONTEXT):
        outcome = "BLOCKED_CONTEXT"
    else:
        original_ctx = _load_context(session, original_scenario)
        from .domain.engine import context_digest_for

        original_digest = original.context_digest or context_digest_for(original_ctx)
        if run.outcome.context_digest != original_digest:
            outcome = "STALE_RECOMMENDATION"
        else:
            # Same decision context: revalidate the original proposal.
            from .domain import validator as validator_module
            from .domain.types import Proposal

            proposal = Proposal.model_validate(proposal_payload)
            constraints = validator_module.validate_proposal(
                proposal, target_ctx, gate_settings, run.outcome.context_digest
            )
            outcome = (
                "STILL_SUPPORTED"
                if all(c.verdict.value == "PASS" for c in constraints)
                else "STALE_RECOMMENDATION"
            )

    if outcome == "STALE_RECOMMENDATION":
        original_ctx = _load_context(session, original_scenario)
        paths = _changed_paths(
            original_ctx.model_dump(mode="json"), target_ctx.model_dump(mode="json")
        )
        reason_codes = _path_reason_codes(paths)
        if run.outcome.outcome is DomainOutcome.NO_FEASIBLE_CANDIDATE:
            reason_codes = sorted(set(reason_codes) | {"TARGET_CONTEXT_EXCLUDED"})
    else:
        paths, reason_codes = [], []

    check = ReviewCheck(
        original_replay_id=original_replay_id,
        target_scenario_id=target_scenario_id,
        target_scenario_revision=target_revision,
        outcome=outcome,
        changed_paths=paths,
        reason_codes=reason_codes,
        issues=gate_issues,
        target_context_digest=run.outcome.context_digest,
    )
    session.add(check)
    session.commit()
    return {
        "id": check.id,
        "original_replay_id": original_replay_id,
        "target_scenario_id": target_scenario_id,
        "target_scenario_revision": target_revision,
        "outcome": outcome,
        "changed_paths": paths,
        "reason_codes": reason_codes,
        "issues": gate_issues,
        "target_context_digest": check.target_context_digest,
        "created_at": check.created_at.isoformat(),
        "original_untouched": True,
    }


# ---------------------------------------------------------------------------
# Note confirmation
# ---------------------------------------------------------------------------


def confirm_event_and_fork(
    session: Session,
    scenario_id: str,
    revision: int,
    *,
    subject_operator_id: str,
    summary: str,
    observed_at: Any,
    source_kind: str,
    source_ref: str,
    parser_call_id: str | None = None,
    corrections: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Confirm a structured event and fork the scenario onto it.

    The model never authors an event: this endpoint runs only on confirmed
    human input, whether the draft came from the parser or manual entry.
    """
    source = session.get(ScenarioRevision, (scenario_id, revision))
    if source is None:
        raise ServiceError("SCENARIO_UNKNOWN", "Unknown scenario revision", 404)
    operator = next(
        (op for op in _load_context(session, source).catalog.operators if op.id == subject_operator_id),
        None,
    )
    if operator is None or not operator.active:
        raise ServiceError("OPERATOR_UNKNOWN", "Unknown or inactive operator", 422)
    if source_kind not in ("note", "manual"):
        raise ServiceError("VALIDATION", "source_kind must be note or manual", 422)

    event = {
        "kind": "OPERATOR_UNAVAILABLE",
        "subject_operator_id": subject_operator_id,
        "observed_at": observed_at,
        "summary": summary,
        "source_ref": source_ref,
    }

    from .workspaces import write_workspace
    workspace_id = write_workspace.get() or source.workspace_id
    fork_id = scenario_id
    if workspace_id != "public-demo" and source.workspace_id != workspace_id:
        fork_id = "scenario-" + digest({"workspace": workspace_id, "origin": scenario_id})[-55:]
    latest = (
        session.execute(
            select(ScenarioRevision.revision).where(ScenarioRevision.scenario_id == fork_id)
        )
        .scalars()
        .all()
    )
    new_revision = max(latest or [revision]) + 1
    tags = list(source.tags)
    if fork_id != scenario_id:
        tags.append(f"origin:{scenario_id}@{revision}")
    if source_kind == "note" and "confirmed-note" not in tags:
        tags.append("confirmed-note")
    elif source_kind == "manual" and "manual-entry" not in tags:
        tags.append("manual-entry")

    fork = ScenarioRevision(
        workspace_id=workspace_id, scenario_id=fork_id,
        revision=new_revision,
        title=source.title,
        tags=tags,
        defect_statement=source.defect_statement
        + f" Revision {new_revision} carries a confirmed "
        f"({'floor note' if source_kind == 'note' else 'manual entry'}) unavailability event for "
        f"{subject_operator_id}.",
        event=event,
        decision_at=source.decision_at,
        target=dict(source.target),
        catalog_revision_id=source.catalog_revision_id,
        pinned_snapshot_ids=list(source.pinned_snapshot_ids),
    )
    session.add(fork)
    expectations = session.execute(
        select(ExpectationRevision).where(
            ExpectationRevision.scenario_id == scenario_id,
            ExpectationRevision.revision == revision,
        )
    ).scalars().all()
    for exp in expectations:
        session.add(
            ExpectationRevision(
                workspace_id=workspace_id, scenario_id=fork_id,
                revision=new_revision,
                configuration_id=exp.configuration_id,
                assertions=dict(exp.assertions),
            )
        )
    session.commit()
    return {
        "scenario_id": fork.scenario_id,
        "revision": fork.revision,
        "event": event,
        "corrections": corrections or {},
        "parser_call_id": parser_call_id,
        "pinned_snapshot_ids": fork.pinned_snapshot_ids,
    }


def replay_export(session: Session, replay_id: str) -> dict[str, Any]:
    """A portable JSON report: the result plus every pinned input."""
    attempt = session.get(ReplayAttempt, replay_id)
    if attempt is None:
        raise ServiceError("REPLAY_UNKNOWN", "Unknown replay attempt", 404)
    scenario = session.get(ScenarioRevision, (attempt.scenario_id, attempt.scenario_revision))
    if scenario is None:
        raise ServiceError("SCENARIO_UNKNOWN", "Scenario revision missing", 500)
    snapshots = []
    for snap_id in scenario.pinned_snapshot_ids:
        row = session.get(SourceSnapshot, snap_id)
        if row is not None:
            snapshots.append(
                {
                    "id": row.id,
                    "kind": row.kind,
                    "source_system": row.source_system,
                    "scope": row.scope,
                    "declared_evidence_at": row.declared_evidence_at.isoformat(),
                    "coverage_complete": row.coverage_complete,
                    "content_digest": row.content_digest,
                    "payload": row.payload,
                }
            )
    return {
        "format": "flooreplay/replay-export@1",
        "attempt": {
            "id": attempt.id,
            "lifecycle": attempt.lifecycle,
            "domain_outcome": attempt.domain_outcome,
            "result": attempt.result,
            "expectation_verdict": attempt.expectation_verdict,
            "expectation_failures": attempt.expectation_failures,
            "context_digest": attempt.context_digest,
            "manifest_digest": attempt.manifest_digest,
            "created_at": attempt.created_at.isoformat(),
        },
        "scenario": {
            "scenario_id": scenario.scenario_id,
            "revision": scenario.revision,
            "title": scenario.title,
            "event": scenario.event,
            "target": scenario.target,
            "decision_at": scenario.decision_at.isoformat(),
        },
        "snapshots": snapshots,
    }
