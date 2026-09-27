"""Idempotent, content-addressed seeding of the synthetic release fixtures.

Running seed twice is a no-op. Artifacts are keyed by stable fixture IDs;
if content under a published ID changes, seeding fails loudly: corrections
must create a new artifact, never rewrite a published one.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from .domain.evaluation import Expectation
from .domain.hashing import digest
from .domain.types import Snapshot
from .fixtures import CATALOG, CONFIGURATIONS, hero_scenarios
from .fixtures_suite import SUITE_ID, suite_cases
from .models import (
    CatalogRevision,
    ExecutionConfiguration,
    ExpectationRevision,
    ScenarioRevision,
    SourceSnapshot,
    SuiteRevision,
)

CATALOG_ID = "CATALOG-2026-09-A"


def _payload_digest(payload: dict[str, Any]) -> str:
    without_digest = {k: v for k, v in payload.items() if k != "content_digest"}
    return digest(without_digest)


def _expectation_assertions(expectation: Expectation) -> dict[str, Any]:
    return {
        "expected_outcome": (
            expectation.expected_outcome.value
            if expectation.expected_outcome is not None
            else None
        ),
        "required_issue_codes": [c.value for c in expectation.required_issue_codes],
        "required_failed_constraints": [
            c.value for c in expectation.required_failed_constraints
        ],
        "required_passed_constraints": [
            c.value for c in expectation.required_passed_constraints
        ],
        "forbidden_operators": list(expectation.forbidden_operators),
        "allowed_operators": list(expectation.allowed_operators),
        "required_operator": expectation.required_operator,
        "policy_execution_permitted": expectation.policy_execution_permitted,
    }


class _ScenarioLike:
    """Uniform view over hero fixtures and suite cases for seeding."""

    def __init__(self, scenario_id: str, revision: int, title: str, tags: tuple[str, ...],
                 defect_statement: str, context: Any, expectations: dict[str, Expectation]) -> None:
        self.scenario_id = scenario_id
        self.revision = revision
        self.title = title
        self.tags = tags
        self.defect_statement = defect_statement
        self.context = context
        self.expectations = expectations


def _all_scenarios() -> list[_ScenarioLike]:
    hero = [
        _ScenarioLike(
            scen.scenario_id, scen.revision, scen.title, scen.tags,
            scen.defect_statement, scen.context, scen.expectations,
        )
        for scen in hero_scenarios()
    ]
    suite = [
        _ScenarioLike(
            case.sid, 1, f"{case.title} ({case.category})",
            (*case.tags, "suite", f"category:{case.category}"),
            case.defect_statement, case.context, case.demands,
        )
        for case in suite_cases()
    ]
    return hero + suite


def seed(session: Session) -> dict[str, int]:
    counts = {"catalogs": 0, "snapshots": 0, "configurations": 0, "scenarios": 0, "expectations": 0, "suite": 0}

    # --- catalog ---------------------------------------------------------
    catalog_payload = CATALOG.model_dump(mode="json")
    catalog_digest = digest(catalog_payload)
    existing = session.get(CatalogRevision, CATALOG_ID)
    if existing is None:
        session.add(
            CatalogRevision(
                id=CATALOG_ID, revision=1, payload=catalog_payload, content_digest=catalog_digest
            )
        )
        counts["catalogs"] += 1
    elif existing.content_digest != catalog_digest:
        raise RuntimeError(
            f"Catalog {CATALOG_ID} changed after publication; publish a new catalog revision."
        )

    # --- snapshots (collected across all scenario revisions) -------------
    snapshots: dict[str, Snapshot] = {}
    for scenario in _all_scenarios():
        for snap in scenario.context.snapshots:
            if snap.id in snapshots and snapshots[snap.id] != snap:
                raise RuntimeError(f"Snapshot id {snap.id} reused with different content")
            snapshots[snap.id] = snap

    for snap_id, snap in sorted(snapshots.items()):
        payload = snap.model_dump(mode="json")
        real_digest = _payload_digest(payload)
        if payload.get("content_digest") != real_digest:
            payload["content_digest"] = real_digest
        existing_snap = session.get(SourceSnapshot, snap_id)
        row = {
            "id": snap_id,
            "kind": snap.kind.value,
            "source_system": snap.source_system,
            "scope": snap.scope,
            "declared_evidence_at": snap.declared_evidence_at,
            "coverage_complete": snap.coverage_complete,
            "content_digest": real_digest,
            "payload": payload,
        }
        if existing_snap is None:
            session.add(SourceSnapshot(**row))
            counts["snapshots"] += 1
        elif existing_snap.content_digest != real_digest:
            raise RuntimeError(
                f"Snapshot {snap_id} changed after publication; publish a new snapshot."
            )

    # --- execution configurations ----------------------------------------
    for cfg in CONFIGURATIONS:
        settings_payload = cfg["settings"].model_dump(mode="json")
        existing_cfg = session.get(ExecutionConfiguration, cfg["id"])
        if existing_cfg is None:
            session.add(
                ExecutionConfiguration(
                    id=cfg["id"],
                    name=cfg["name"],
                    policy_kind=cfg["policy_kind"],
                    settings=settings_payload,
                    known_limitation=cfg["known_limitation"],
                )
            )
            counts["configurations"] += 1
        else:
            # Registered configurations are code, not evidence: refresh labels
            # but settings changes are recorded per attempt at execution time.
            existing_cfg.name = cfg["name"]
            existing_cfg.policy_kind = cfg["policy_kind"]
            existing_cfg.settings = settings_payload
            existing_cfg.known_limitation = cfg["known_limitation"]

    # --- scenario revisions and expectations ------------------------------
    for scenario in _all_scenarios():
        existing_scen = session.get(ScenarioRevision, (scenario.scenario_id, scenario.revision))
        if existing_scen is None:
            session.add(
                ScenarioRevision(
                    scenario_id=scenario.scenario_id,
                    revision=scenario.revision,
                    title=scenario.title,
                    tags=list(scenario.tags),
                    defect_statement=scenario.defect_statement,
                    event=scenario.context.event.model_dump(mode="json"),
                    decision_at=scenario.context.decision_at,
                    target=scenario.context.target.model_dump(mode="json"),
                    catalog_revision_id=CATALOG_ID,
                    pinned_snapshot_ids=[s.id for s in scenario.context.snapshots],
                )
            )
            counts["scenarios"] += 1

        for cfg_id, expectation in scenario.expectations.items():
            assertions = _expectation_assertions(expectation)
            stmt = pg_insert(ExpectationRevision).values(
                scenario_id=scenario.scenario_id,
                revision=scenario.revision,
                configuration_id=cfg_id,
                assertions=assertions,
            )
            existing_exp = session.execute(
                select(ExpectationRevision).where(
                    ExpectationRevision.scenario_id == scenario.scenario_id,
                    ExpectationRevision.revision == scenario.revision,
                    ExpectationRevision.configuration_id == cfg_id,
                )
            ).scalar_one_or_none()
            if existing_exp is None:
                session.execute(stmt)
                counts["expectations"] += 1
            elif existing_exp.assertions != assertions:
                raise RuntimeError(
                    f"Expectation for {scenario.scenario_id}@{scenario.revision}/{cfg_id} "
                    "changed after publication; publish a new expectation revision with "
                    "a written rationale."
                )

    # --- suite revision ----------------------------------------------------
    suite_items = [
        {
            "scenario_id": case.sid,
            "revision": 1,
            "category": case.category,
            "title": case.title,
            "defect_statement": case.defect_statement,
        }
        for case in suite_cases()
    ]
    suite_digest = digest({"suite_id": SUITE_ID, "items": suite_items})
    existing_suite = session.get(SuiteRevision, SUITE_ID)
    if existing_suite is None:
        session.add(
            SuiteRevision(
                id=SUITE_ID,
                revision=1,
                label="Operational evaluation suite v1 (32 cases)",
                items=suite_items,
                content_digest=suite_digest,
            )
        )
        counts["suite"] = 1
    elif existing_suite.content_digest != suite_digest:
        raise RuntimeError(
            f"Suite {SUITE_ID} membership changed after publication; publish a new suite revision."
        )

    session.commit()
    return counts


def run_seed() -> dict[str, int]:
    from .db import session_scope

    with session_scope() as session:
        return seed(session)
