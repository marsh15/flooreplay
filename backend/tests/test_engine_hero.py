"""The hero demonstration, locked in as the repo's most valuable test."""

from __future__ import annotations

from flooreplay.domain import evaluation
from flooreplay.domain.engine import run_replay
from flooreplay.domain.types import ConstraintCode, DomainOutcome, IssueCode
from flooreplay.fixtures import CONFIGURATIONS

CFG = {c["id"]: c for c in CONFIGURATIONS}


def _run(cfg_id, ctx):
    cfg = CFG[cfg_id]
    return run_replay(ctx, cfg["settings"], cfg["policy_kind"]).outcome


def test_stale_skill_evidence_blocks_every_legitimate_policy(hero_v1):
    for cfg_id in ("CFG-BASELINE-V1", "CFG-IMPROVED-V1"):
        result = _run(cfg_id, hero_v1)
        assert result.outcome is DomainOutcome.NEEDS_CONTEXT
        assert result.proposal is None and result.abstention is None
        assert IssueCode.SKILL_STALE in {i.code for i in result.gate_issues}


def test_baseline_proposes_occupied_operator_and_is_rejected(hero_v2):
    result = _run("CFG-BASELINE-V1", hero_v2)
    assert result.outcome is DomainOutcome.REJECTED_BY_CONSTRAINT
    assert result.proposal is not None
    assert result.proposal.operator_id == "O204"
    failed = {c.code for c in result.constraints if c.verdict.value == "FAIL"}
    assert ConstraintCode.C07 in failed
    c07 = next(c for c in result.constraints if c.code is ConstraintCode.C07)
    assert c07.evidence, "C07 failure must link to evidence"


def test_improved_policy_proposes_supported_idle_operator(hero_v2):
    result = _run("CFG-IMPROVED-V1", hero_v2)
    assert result.outcome is DomainOutcome.READY_FOR_REVIEW
    assert result.proposal is not None
    assert result.proposal.operator_id == "O219"
    assert all(c.verdict.value == "PASS" for c in result.constraints)


def test_defect_configuration_is_caught_by_stale_evidence_expectation(hero_v1, hero_v2):
    """The deliberate regression must be detectable by the suite, not hidden."""
    from flooreplay.fixtures import hero_scenarios

    stale_scenario = hero_scenarios()[0]
    exp = stale_scenario.expectations["CFG-DEFECT-SKILLFRESH"]
    verdict = evaluation.evaluate(_run("CFG-DEFECT-SKILLFRESH", hero_v1), exp)
    assert verdict.verdict.value == "FAIL"
    assert any("SKILL_STALE" in f for f in verdict.failures)


def test_determinism_same_inputs_same_digest(hero_v2):
    r1 = _run("CFG-IMPROVED-V1", hero_v2)
    r2 = _run("CFG-IMPROVED-V1", hero_v2)
    assert r1.context_digest == r2.context_digest
    assert r1.proposal == r2.proposal


def test_context_digest_tracks_evidence(hero_v1, hero_v2):
    assert _run("CFG-IMPROVED-V1", hero_v1).context_digest != _run(
        "CFG-IMPROVED-V1", hero_v2
    ).context_digest
