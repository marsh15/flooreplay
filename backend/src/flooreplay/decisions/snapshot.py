"""Pure as-known snapshots over a list of facts.

Only the facts visible at the cutoff are validated, so a bad fact recorded later can
never break an older replay; `facts.validate_corrections(full_list)` is the separate
write-time check. No clock, database or randomness is used here.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from enum import StrEnum

from flooreplay.decisions.facts import semantic_digest, validate_corrections, validate_fact
from flooreplay.decisions.types import Fact, FactKind, FrozenModel, Instant, decision_digest


class Finding(FrozenModel):
    """Something the snapshot noticed that downstream gates must see."""

    code: str
    subject_id: str  # the fact the finding is about
    fact_ids: tuple[str, ...]


COMPETING_REPLACEMENT = "competing_replacement"


class Snapshot(FrozenModel):
    cutoff: Instant
    facts: tuple[Fact, ...]
    findings: tuple[Finding, ...]
    digest: str


class CurrentStatus(StrEnum):
    FOUND = "found"
    TIE_CONFLICT = "tie_conflict"  # same valid_from, different semantic payloads: CONFLICTING
    UNKNOWN = "unknown"  # no such entity at this cutoff; never zero


class CurrentResult(FrozenModel):
    status: CurrentStatus
    fact: Fact | None  # the chosen fact, only when FOUND
    facts: tuple[Fact, ...]  # every fact at the winning valid_from (empty when UNKNOWN)


def _sort_key(fact: Fact) -> tuple[str, str, object, object, str]:
    return (fact.kind.value, fact.entity_key, fact.valid_from, fact.known_at, fact.id)


def visible(facts: Iterable[Fact], cutoff: Instant) -> list[Fact]:
    """Facts known by `cutoff` and not superseded by another visible fact, in deterministic order.

    Raises CorrectionError if the visible subset is itself an invalid correction graph.
    """
    known = [f for f in facts if f.known_at <= cutoff]
    validate_corrections(known)
    replaced = {f.supersedes_id for f in known if f.supersedes_id is not None}
    return sorted((f for f in known if f.id not in replaced), key=_sort_key)


def _competing(facts: Iterable[Fact], cutoff: Instant) -> list[Finding]:
    children: dict[str, list[str]] = defaultdict(list)
    for fact in facts:
        if fact.supersedes_id is not None and fact.known_at <= cutoff:
            children[fact.supersedes_id].append(fact.id)
    return [
        Finding(code=COMPETING_REPLACEMENT, subject_id=target, fact_ids=tuple(sorted(ids)))
        for target, ids in sorted(children.items())
        if len(ids) > 1
    ]


def snapshot_at(facts: Iterable[Fact], cutoff: Instant) -> Snapshot:
    """The as-known view at `cutoff`. The input is never modified."""
    all_facts = list(facts)
    chosen = visible(all_facts, cutoff)
    for fact in chosen:
        validate_fact(fact)
    findings = tuple(sorted(_competing(all_facts, cutoff), key=lambda f: (f.code, f.subject_id)))
    body = {
        "cutoff": cutoff,
        "facts": [{"id": f.id, "semantic": semantic_digest(f)} for f in chosen],
        "findings": [f.model_dump(mode="python") for f in findings],
    }
    return Snapshot(
        cutoff=cutoff, facts=tuple(chosen), findings=findings, digest=decision_digest(body)
    )


def current(snapshot: Snapshot, kind: FactKind, entity_key: str) -> CurrentResult:
    """Observation semantics for one entity: latest valid_from wins; a payload tie conflicts."""
    candidates = [f for f in snapshot.facts if f.kind == kind and f.entity_key == entity_key]
    if not candidates:
        return CurrentResult(status=CurrentStatus.UNKNOWN, fact=None, facts=())
    newest = max(f.valid_from for f in candidates)
    tied = tuple(sorted((f for f in candidates if f.valid_from == newest), key=_sort_key))
    if len({semantic_digest(f) for f in tied}) > 1:
        return CurrentResult(status=CurrentStatus.TIE_CONFLICT, fact=None, facts=tied)
    latest_known = max(tied, key=lambda f: (f.known_at, f.id))
    return CurrentResult(status=CurrentStatus.FOUND, fact=latest_known, facts=tied)
