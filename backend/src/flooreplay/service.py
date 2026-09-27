"""Application service: load pinned artifacts, execute, persist.

Short transactions only: create the attempt, commit, execute the engine
with no transaction open, then atomically persist the result, evaluation,
and completion state. Idempotency is enforced by a database unique key,
not an in-memory dictionary.
"""

from __future__ import annotations

import time
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
    ScenarioRevision,
    SourceSnapshot,
    SuiteRevision,
)


class ServiceError(Exception):
    def __init__(self, code: str, message: str, http_status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


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
        idempotency_key=idempotency_key,
        scenario_id=scenario_id,
        scenario_revision=scenario_revision,
        configuration_id=configuration_id,
        lifecycle="RUNNING",
        request_payload=request_payload,
    )
    session.add(attempt)
    session.commit()  # the attempt exists before execution; restarts can mark it INTERRUPTED

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
        attempt.completed_at = attempt.created_at
        session.commit()
    except EngineError as exc:
        attempt.lifecycle = "ERRORED"
        attempt.result = {"execution_error": {"code": exc.code, "message": str(exc)}}
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


def publish_import(session: Session, preview: ImportPreview, raw_text: str) -> dict[str, Any]:
    """Atomically persist the snapshot and its audit record.

    Idempotent by preview digest: republishing the exact preview returns the
    existing snapshot without creating anything.
    """
    snapshot = build_snapshot(preview)  # raises on blocking issues: all-or-nothing

    existing_audit = session.get(ImportAudit, preview.preview_digest)
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
                preview_digest=preview.preview_digest,
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
            id=snapshot.id,
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
            preview_digest=preview.preview_digest,
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

    latest = (
        session.execute(
            select(ScenarioRevision.revision).where(ScenarioRevision.scenario_id == scenario_id)
        )
        .scalars()
        .all()
    )
    new_revision = max(latest) + 1

    tags = list(source.tags)
    if "imported-evidence" not in tags:
        tags.append("imported-evidence")
    fork = ScenarioRevision(
        scenario_id=scenario_id,
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
                scenario_id=scenario_id,
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
        idempotency_key=idempotency_key,
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
