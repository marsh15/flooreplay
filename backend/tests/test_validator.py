"""Independent validator behavior on fabricated proposals.

These tests keep the constraints exercised even when the improved policy
filters bad candidates before proposing them: here we hand the validator
proposals it would never receive from a sane policy.
"""

from __future__ import annotations

from flooreplay.domain import validator
from flooreplay.domain.engine import context_digest_for
from flooreplay.domain.types import ConstraintCode, Verdict
from flooreplay.fixtures import DEFAULT_FRESHNESS, hero_context, hero_snapshots_v2


def _proposal(**overrides):
    base = {
        "operator_id": "O219",
        "target_slot_id": "L4-SLM-1",
        "machine_id": "SN-4407",
        "operation_id": "OP-SLM",
        "style_id": "ST-411",
        "plan_revision": "PLAN-2026-09-22-B",
        "starts_at": hero_context(hero_snapshots_v2()).target.starts_at,
        "ends_at": hero_context(hero_snapshots_v2()).target.ends_at,
        "context_digest": "sha256:placeholder",
        "ranking_factors": (),
    }
    base.update(overrides)
    from flooreplay.domain.types import Proposal

    return Proposal(**base)


def _validate(proposal, ctx):
    return {
        c.code: c for c in validator.validate_proposal(
            proposal, ctx, DEFAULT_FRESHNESS, context_digest_for(ctx)
        )
    }


def test_valid_proposal_passes_every_constraint():
    ctx = hero_context(hero_snapshots_v2())
    p = _proposal(context_digest=context_digest_for(ctx))
    results = _validate(p, ctx)
    assert all(c.verdict is Verdict.PASS for c in results.values())


def test_unknown_operator_fails_c01_and_dependents_not_evaluated():
    ctx = hero_context(hero_snapshots_v2())
    results = _validate(_proposal(operator_id="O999"), ctx)
    assert results[ConstraintCode.C01].verdict is Verdict.FAIL
    for code in (ConstraintCode.C02, ConstraintCode.C04, ConstraintCode.C05, ConstraintCode.C07, ConstraintCode.C12):
        assert results[code].verdict is Verdict.NOT_EVALUATED


def test_occupied_operator_fails_c07_with_evidence():
    ctx = hero_context(hero_snapshots_v2())
    results = _validate(_proposal(operator_id="O204"), ctx)
    assert results[ConstraintCode.C07].verdict is Verdict.FAIL
    assert results[ConstraintCode.C07].evidence


def test_wrong_context_digest_fails_c11():
    ctx = hero_context(hero_snapshots_v2())
    results = _validate(_proposal(context_digest="sha256:wrong"), ctx)
    assert results[ConstraintCode.C11].verdict is Verdict.FAIL


def test_unavailable_subject_fails_c02_and_c12():
    ctx = hero_context(hero_snapshots_v2())
    results = _validate(_proposal(operator_id="O117"), ctx)
    assert results[ConstraintCode.C02].verdict is Verdict.FAIL
    assert results[ConstraintCode.C12].verdict is Verdict.FAIL


def test_unknown_machine_fails_c06():
    ctx = hero_context(hero_snapshots_v2())
    results = _validate(_proposal(machine_id="SN-0000"), ctx)
    assert results[ConstraintCode.C06].verdict is Verdict.FAIL


def test_incompatible_machine_fails_c06():
    ctx = hero_context(hero_snapshots_v2())
    results = _validate(_proposal(machine_id="BT-3305"), ctx)
    assert results[ConstraintCode.C06].verdict is Verdict.FAIL


def test_wrong_plan_revision_fails_c09():
    ctx = hero_context(hero_snapshots_v2())
    results = _validate(_proposal(plan_revision="PLAN-2026-09-22-A"), ctx)
    assert results[ConstraintCode.C09].verdict is Verdict.FAIL
