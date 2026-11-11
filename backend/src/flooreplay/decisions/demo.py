"""The synthetic "Tiruppur Knits" demo: five order stories and the frozen regression cases.

Everything here is invented. The data builders are pure (no database, no clock) so the same
facts always come out; `seed_demo` writes them into the public demo workspace and is safe to
run again. The stories, all on 2026-10-22 (times IST):

* POLO-221  09:00 ERP shows 4,000 m of NAVY in lot L-221. 10:30 a dyeing-house note says
            1,200 m failed shade. The gate is CONFLICTING at 11:00. 12:30 QA reviews it and
            records 2,800 m usable; the gate is READY and the order ACCEPT at 13:00.
* POLO-222  Sewing capacity is short but covered by capped overtime: ACCEPT_WITH_CONDITIONS.
* POLO-223  Fabric is short. Split shipment is not built, so the engine asks for review.
* POLO-224  The trims sheet is three days old: STALE, so the engine asks for review.
* POLO-225  Everything passes but the order value is above the approval limit.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from flooreplay.decisions import service
from flooreplay.decisions.expectations import Expectation
from flooreplay.decisions.gate import CoverageDecl
from flooreplay.decisions.models import (
    DecisionCase,
    DecisionEvaluation,
    DecisionSourceArtifact,
    FactRow,
    RegressionRun,
)
from flooreplay.decisions.policy import DEFAULT_POLICY_V1, PolicyDocument, policy_digest
from flooreplay.decisions.types import Fact, FactKind, Recommendation, SourceProfile

WORKSPACE = "public-demo"
FACTORY = "Tiruppur Knits (synthetic)"
QUALITY = "SJ180"
LINES = ("L1", "L2", "L3", "L4")
ERP_ARTIFACT = "demo-erp-2026-10-22"

DAY = date(2026, 10, 22)
IST = timedelta(hours=5, minutes=30)


def ist(hour: int, minute: int = 0, day: date = DAY) -> datetime:
    """An IST wall-clock time on `day`, as a UTC instant."""
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=UTC) - IST


EXPORT_AS_OF = ist(8, 30)
EXPORT_KNOWN = ist(9, 0)
STALE_TRIMS_AS_OF = ist(8, 30, DAY - timedelta(days=3))


def _fact(
    fact_id: str,
    kind: FactKind,
    entity_key: str,
    payload: Mapping[str, Any],
    source: SourceProfile,
    *,
    valid_from: datetime = EXPORT_AS_OF,
    known_at: datetime = EXPORT_KNOWN,
    artifact_id: str | None = None,
) -> Fact:
    return Fact(
        id=fact_id,
        kind=kind,
        entity_key=entity_key,
        payload=dict(payload),
        valid_from=valid_from,
        valid_to=None,
        known_at=known_at,
        supersedes_id=None,
        source=source,
        artifact_id=artifact_id,
    )


def _qty(value: str, unit: str) -> dict[str, str]:
    return {"value": value, "unit": unit}


@dataclass(frozen=True)
class OrderSpec:
    order_id: str
    buyer: str
    colours: tuple[tuple[str, int], ...]
    ship_date: date
    value_inr: str
    sam_minutes: str
    lots: tuple[tuple[str, str, str], ...]  # (lot_id, colour, metres)
    metres_per_piece: str = "0.62"
    trims_as_of: datetime = EXPORT_AS_OF


ORDERS: tuple[OrderSpec, ...] = (
    OrderSpec(
        "POLO-221",
        "Synthetic Buyer A",
        (("NAVY", 3000), ("WHITE", 2000)),
        date(2026, 11, 20),
        "2500000",
        "12.5",
        (("L-221", "NAVY", "4000"), ("L-222", "WHITE", "3000")),
    ),
    OrderSpec(
        "POLO-222",
        "Synthetic Buyer B",
        (("BLACK", 5000),),
        date(2026, 11, 14),
        "3100000",
        "19.0",
        (("L-223", "BLACK", "5000"),),
    ),
    OrderSpec(
        "POLO-223",
        "Synthetic Buyer C",
        (("RED", 4000),),
        date(2026, 11, 20),
        "2100000",
        "12.5",
        (("L-224", "RED", "2000"),),
    ),
    OrderSpec(
        "POLO-224",
        "Synthetic Buyer D",
        (("GREEN", 2500),),
        date(2026, 11, 20),
        "1400000",
        "12.5",
        (("L-225", "GREEN", "2500"),),
        trims_as_of=STALE_TRIMS_AS_OF,
    ),
    OrderSpec(
        "POLO-225",
        "Synthetic Buyer E",
        (("MAROON", 3000),),
        date(2026, 11, 20),
        "6200000",
        "12.5",
        (("L-226", "MAROON", "3000"),),
    ),
)


def working_days(first: date, last: date) -> list[date]:
    """Every day from `first` to `last` except Sundays (the default policy's day off)."""
    days = (last - first).days + 1
    return [first + timedelta(days=n) for n in range(days) if (first + timedelta(days=n)).weekday() != 6]


def order_facts(spec: OrderSpec, *, capacity_minutes: str = "3000") -> list[Fact]:
    """Order request, BOM, ERP lots, trims and line capacity for one order, known at 09:00."""
    key = spec.order_id
    facts = [
        _fact(
            f"{key}-order",
            FactKind.ORDER_REQUEST,
            f"order:{key}",
            {
                "buyer": spec.buyer,
                "style_id": key,
                "colours": [{"colour": c, "qty_pcs": q} for c, q in spec.colours],
                "ship_date": spec.ship_date,
                "order_value_inr": spec.value_inr,
                "partial_shipment_allowed": True,
            },
            SourceProfile.ORDER_REQUESTS,
        ),
        _fact(
            f"{key}-bom",
            FactKind.BOM,
            f"bom:{key}",
            {
                "fabric_quality": QUALITY,
                "consumption_per_pc": _qty(spec.metres_per_piece, "m"),
                "trims": [{"trim_id": "LABEL", "qty_per_pc": "1"}, {"trim_id": "BUTTON", "qty_per_pc": "2"}],
                "sam_minutes": spec.sam_minutes,
            },
            SourceProfile.ORDER_REQUESTS,
        ),
    ]
    for lot_id, colour, metres in spec.lots:
        facts.append(
            _fact(
                f"lot-{lot_id}",
                FactKind.FABRIC_LOT,
                f"lot:{lot_id}",
                {"fabric_quality": QUALITY, "colour": colour, "qty": _qty(metres, "m")},
                SourceProfile.ERP_FABRIC_STOCK,
                artifact_id=ERP_ARTIFACT,
            )
        )
    for trim_id in ("LABEL", "BUTTON"):
        facts.append(
            _fact(
                f"{key}-trim-{trim_id}",
                FactKind.TRIM_STATUS,
                f"trim:{key}:{trim_id}",
                {"on_hand": _qty("100000", "pcs"), "supplier": "Synthetic trims supplier"},
                SourceProfile.SHEET_TRIMS_STATUS,
                valid_from=spec.trims_as_of,
                known_at=max(spec.trims_as_of + timedelta(minutes=30), spec.trims_as_of),
            )
        )
    return facts


def capacity_facts(minutes: str = "3000") -> list[Fact]:
    """The shift sheet: every line, every working day the demo orders can need."""
    facts = []
    for line in LINES:
        for day in working_days(date(2026, 10, 23), date(2026, 12, 15)):
            facts.append(
                _fact(
                    f"cap-{line}-{day.isoformat()}",
                    FactKind.LINE_CAPACITY,
                    f"line:{line}:{day.isoformat()}",
                    {"available_minutes": _qty(minutes, "minutes")},
                    SourceProfile.SHIFT_CAPACITY,
                )
            )
    return facts


def dyeing_note_facts() -> list[Fact]:
    """The 10:30 note (shade failure on 1,200 m of L-221) and the 12:30 QA resolution."""
    note = _fact(
        "note-L-221-shade",
        FactKind.FABRIC_QC,
        "lot:L-221",
        {
            "issue": "shade_fail",
            "qty": _qty("1200", "m"),
            "review_state": "checks_passed",
            "origin": "notes",
        },
        SourceProfile.NOTES,
        valid_from=ist(10, 30),
        known_at=ist(10, 30),
    )
    resolution = _fact(
        "resolution-L-221",
        FactKind.RESOLUTION,
        "lot:L-221",
        {
            "rule_id": "qc_claims_against_lot",
            "left_fact_id": "lot-L-221",
            "right_fact_id": "note-L-221-shade",
            "resolved_payload": {"usable_qty": _qty("2800", "m")},
            "reviewer": "QA lead (synthetic)",
        },
        SourceProfile.REVIEW_QUEUE,
        valid_from=ist(12, 30),
        known_at=ist(12, 30),
    )
    return [note, resolution]


def erp_coverage() -> dict[str, CoverageDecl]:
    return {
        ERP_ARTIFACT: CoverageDecl(
            profile=SourceProfile.ERP_FABRIC_STOCK, as_of=EXPORT_AS_OF, qualities=frozenset({QUALITY})
        )
    }


def demo_facts() -> list[Fact]:
    facts = capacity_facts()
    for spec in ORDERS:
        facts.extend(order_facts(spec))
    facts.extend(dyeing_note_facts())
    return facts


# ---------------------------------------------------------------------------
# The candidate policy and the frozen regression cases
# ---------------------------------------------------------------------------


def candidate_policy() -> PolicyDocument:
    """Tiruppur v2 (candidate): a thinner safety floor and a lower overtime cap."""
    data = DEFAULT_POLICY_V1.model_dump(mode="json")
    data["label"] = "Tiruppur candidate v2"
    data["fabric"]["safety_floor_pct"] = "0.02"
    data["capacity"]["ot_cap_hours_per_line_day"] = 1
    return PolicyDocument.model_validate(data)


@dataclass(frozen=True)
class CaseSpec:
    case_id: str
    name: str
    order_id: str
    cutoff: datetime
    facts: tuple[Fact, ...]
    expectation: Expectation


def _known_by(facts: list[Fact], cutoff: datetime) -> tuple[Fact, ...]:
    return tuple(f for f in facts if f.known_at <= cutoff)


def _variant(order_id: str, **changes: Any) -> OrderSpec:
    base = next(spec for spec in ORDERS if spec.order_id == "POLO-223")
    values = {**base.__dict__, "order_id": order_id, **changes}
    return OrderSpec(**values)


def case_specs() -> tuple[CaseSpec, ...]:
    """Nine hand-labelled past decisions. The label is what a merchandiser would say in hindsight."""
    shared = capacity_facts()
    spec = {s.order_id: s for s in ORDERS}

    def own(order_id: str, cutoff: datetime) -> tuple[Fact, ...]:
        return _known_by([*shared, *order_facts(spec[order_id])] + (dyeing_note_facts() if order_id == "POLO-221" else []), cutoff)

    thin = _variant("CASE-THIN-MARGIN", lots=(("L-901", "RED", "2700"),))
    short = _variant("CASE-NO-CAPACITY", colours=(("RED", 3000),), lots=(("L-902", "RED", "9000"),), sam_minutes="40.0")
    incomplete = [f for f in order_facts(spec["POLO-221"]) if f.kind is not FactKind.BOM]
    gold = Recommendation
    return (
        CaseSpec(
            "case-01-conflicting-stock", "Dyeing note contradicts the ERP stock", "POLO-221", ist(11),
            own("POLO-221", ist(11)),
            Expectation(
                correct=gold.NEEDS_REVIEW,
                rationale="ERP said 4,000 m while the dyeing house reported 1,200 m failed; nobody should accept before QA looked.",
                required_findings=("conflict_rule",),
            ),
        ),
        CaseSpec(
            "case-02-qa-resolved", "QA resolves the stock conflict", "POLO-221", ist(13),
            own("POLO-221", ist(13)),
            Expectation(correct=gold.ACCEPT, rationale="QA confirmed 2,800 m usable, which covers both colours with margin."),
        ),
        CaseSpec(
            "case-03-overtime-covers", "Capacity is short but overtime covers it", "POLO-222", ist(13),
            own("POLO-222", ist(13)),
            Expectation(
                correct=gold.ACCEPT_WITH_CONDITIONS,
                rationale="The lines ran two overtime hours a day for two weeks and shipped on time.",
            ),
        ),
        CaseSpec(
            "case-04-fabric-shortfall", "Fabric short; the buyer took a split shipment", "POLO-223", ist(13),
            own("POLO-223", ist(13)),
            Expectation(
                correct=gold.ACCEPT_WITH_CONDITIONS,
                rationale="The buyer accepted a split shipment. The engine cannot propose one yet, so it asks for review: a known gap.",
            ),
        ),
        CaseSpec(
            "case-05-stale-trims", "Trims sheet is three days old", "POLO-224", ist(13),
            own("POLO-224", ist(13)),
            Expectation(
                correct=gold.NEEDS_REVIEW,
                rationale="Trims stock could have moved in three days; someone must refresh the sheet first.",
                required_findings=("stale_evidence",),
            ),
        ),
        CaseSpec(
            "case-06-over-approval", "Order value above the approval limit", "POLO-225", ist(13),
            own("POLO-225", ist(13)),
            Expectation(correct=gold.NEEDS_REVIEW, rationale="Everything passed, but orders this large need a director's sign-off."),
        ),
        CaseSpec(
            "case-07-thin-safety-margin", "Safety margin only just short", thin.order_id, ist(13),
            _known_by([*shared, *order_facts(thin)], ist(13)),
            Expectation(
                correct=gold.ACCEPT,
                rationale="The order was accepted and shipped; a 3 percent margin was enough in practice.",
            ),
        ),
        CaseSpec(
            "case-08-bom-missing", "Order arrived without a bill of materials", "POLO-221", ist(9, 5),
            _known_by([*shared, *incomplete], ist(9, 5)),
            Expectation(
                correct=gold.NEEDS_REVIEW,
                rationale="Fabric need cannot be worked out without the BOM.",
                required_findings=("bom_missing",),
            ),
        ),
        CaseSpec(
            "case-09-no-capacity", "Too much work even with overtime", short.order_id, ist(13),
            _known_by([*shared, *order_facts(short)], ist(13)),
            Expectation(correct=gold.DECLINE, rationale="The sewing minutes were never there; declining was right."),
        ),
    )


# ---------------------------------------------------------------------------
# Writing it all into the public demo workspace (idempotent)
# ---------------------------------------------------------------------------

_ERP_BYTES = b"lot_id,fabric_quality,colour,qty_m\nL-221,SJ180,NAVY,4000\n"
# Where each story is first shown: POLO-221 at the conflicted and then the resolved cutoff.
_STORED_EVALUATIONS = (
    ("POLO-221", ist(11)),
    ("POLO-221", ist(13)),
    ("POLO-222", ist(13)),
    ("POLO-223", ist(13)),
    ("POLO-224", ist(13)),
    ("POLO-225", ist(13)),
)


def seed_demo(session: Session, workspace_id: str = WORKSPACE) -> dict[str, int]:
    """Create whatever the workspace is missing of the demo. A second run creates nothing."""
    counts = {"facts": 0, "artifacts": 0, "policies": 0, "cases": 0, "evaluations": 0, "runs": 0}
    if session.get(DecisionSourceArtifact, (workspace_id, ERP_ARTIFACT)) is None:
        session.add(
            DecisionSourceArtifact(
                workspace_id=workspace_id,
                id=ERP_ARTIFACT,
                profile=SourceProfile.ERP_FABRIC_STOCK.value,
                filename="erp-fabric-stock-2026-10-22.csv",
                raw_bytes=_ERP_BYTES,
                raw_digest="synthetic-demo",
                as_of=EXPORT_AS_OF,
                known_at=EXPORT_KNOWN,
                coverage=erp_coverage()[ERP_ARTIFACT].model_dump(mode="json"),
                idempotency_key=ERP_ARTIFACT,
                preview_digest="synthetic-demo",
            )
        )
        session.flush()
        counts["artifacts"] += 1

    present = set(session.scalars(select(FactRow.id).where(FactRow.workspace_id == workspace_id)))
    missing = [fact for fact in demo_facts() if fact.id not in present]
    for known_at in sorted({fact.known_at for fact in missing}):
        batch = [fact for fact in missing if fact.known_at == known_at]
        service.append_facts(session, batch, workspace_id=workspace_id, trusted_known_at=known_at)
        counts["facts"] += len(batch)

    candidate = candidate_policy()
    for policy in (DEFAULT_POLICY_V1, candidate):
        before = len(service.list_stored_policies(session, workspace_id))
        service.store_policy(session, workspace_id, policy)
        counts["policies"] += len(service.list_stored_policies(session, workspace_id)) - before

    coverage = erp_coverage()
    for case in case_specs():
        if session.get(DecisionCase, (workspace_id, case.case_id)) is not None:
            continue
        service.create_case(
            session, workspace_id, case.case_id, case.name, case.cutoff, case.order_id,
            case.facts, coverage, synthetic=True,
        )
        service.add_expectation(session, workspace_id, case.case_id, case.expectation)
        counts["cases"] += 1

    for order_id, cutoff in _STORED_EVALUATIONS:
        known = session.scalar(
            select(DecisionEvaluation.id).where(
                DecisionEvaluation.workspace_id == workspace_id,
                DecisionEvaluation.order_id == order_id,
                DecisionEvaluation.cutoff == cutoff,
                DecisionEvaluation.policy_digest == policy_digest(DEFAULT_POLICY_V1),
            )
        )
        if known is None and service.is_settled(session, cutoff):
            service.evaluate_order(session, workspace_id, order_id, cutoff, DEFAULT_POLICY_V1)
            counts["evaluations"] += 1

    if session.scalar(
        select(RegressionRun.id).where(
            RegressionRun.workspace_id == workspace_id,
            RegressionRun.candidate_policy_digest == policy_digest(candidate),
        )
    ) is None:
        service.run_regression(session, workspace_id, DEFAULT_POLICY_V1, candidate)
        counts["runs"] += 1
    return counts


# ---------------------------------------------------------------------------
# Verification: the labels, the engine and the declared comparison must agree
# ---------------------------------------------------------------------------

EXPECTED_CLASSIFICATIONS: dict[str, str] = {
    "case-01-conflicting-stock": "UNCHANGED_PASS",
    "case-02-qa-resolved": "UNCHANGED_PASS",
    "case-03-overtime-covers": "REGRESSION",
    "case-04-fabric-shortfall": "UNCHANGED_FAIL",
    "case-05-stale-trims": "UNCHANGED_PASS",
    "case-06-over-approval": "UNCHANGED_PASS",
    "case-07-thin-safety-margin": "FIXED",
    "case-08-bom-missing": "UNCHANGED_PASS",
    "case-09-no-capacity": "UNCHANGED_PASS",
}
"""What the default policy against the candidate must do to each case. Changing a case, a
label or either policy so that this table no longer holds is a deliberate act: edit the table
in the same commit and say why."""


def classify_cases() -> dict[str, str]:
    """Replay every case under both policies and compare the verdicts, with no database."""
    from flooreplay.decisions.compare import compare_cases
    from flooreplay.decisions.expectations import evaluate_expectation
    from flooreplay.decisions.replay import replay
    from flooreplay.decisions.snapshot import snapshot_at

    def verdicts(policy: PolicyDocument) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for case in case_specs():
            result = replay(snapshot_at(case.facts, case.cutoff), case.order_id, policy, erp_coverage())
            codes = tuple(finding.code for finding in result.gate.findings)
            out[case.case_id] = evaluate_expectation(case.expectation, result.recommendation.outcome, codes).verdict
        return out

    compared = compare_cases(
        verdicts(DEFAULT_POLICY_V1),
        verdicts(candidate_policy()),
        baseline_suite_digest="demo",
        candidate_suite_digest="demo",
    )
    return {item.case_id: item.classification.value for item in compared}


def verify_cases() -> dict[str, Any]:
    """Problems with the demo cases, or an empty list. Used by `decision-cases-verify`."""
    problems: list[str] = []
    cases = case_specs()
    ids = [case.case_id for case in cases]
    if len(set(ids)) != len(ids):
        problems.append("duplicate case ids")
    if set(ids) != set(EXPECTED_CLASSIFICATIONS):
        problems.append("the declared classifications do not list exactly the cases")
    for case in cases:
        if any(fact.known_at > case.cutoff for fact in case.facts):
            problems.append(f"{case.case_id}: a fact was learned after the cutoff")
        if not case.expectation.rationale.strip():
            problems.append(f"{case.case_id}: the label has no written rationale")
    if not problems:
        actual = classify_cases()
        for case_id, declared in EXPECTED_CLASSIFICATIONS.items():
            if actual.get(case_id) != declared:
                problems.append(f"{case_id}: declared {declared}, replay gives {actual.get(case_id)}")
    return {
        "status": "PASSED" if not problems else "FAILED",
        "cases": len(cases),
        "synthetic": True,
        "problems": problems,
    }
