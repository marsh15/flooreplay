"""Pure as-known snapshots over a list of facts.

Only the facts visible at the cutoff are checked, so a bad fact recorded later can
never break an older replay; `facts.validate_corrections(full_list)` is the separate
write-time check. No clock, database or randomness is used here.

Two kinds of fact. *Observations* (every kind except `facts.EVENT_KINDS`) describe the
current state of an entity: `current()` picks the latest `valid_from`. `valid_to` is
informational and `current()` ignores it. *Events* (`fabric_qc`, `resolution`) accumulate:
read them with `events()`; the FABRIC constraint sums them.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from enum import StrEnum

from flooreplay.decisions.facts import (
    EVENT_KINDS,
    FactValidationError,
    semantic_digest,
    validate_corrections,
    validate_fact,
)
from flooreplay.decisions.types import Fact, FactKind, FrozenModel, Instant, decision_digest

COMPETING_REPLACEMENT = "competing_replacement"
INVALID_PAYLOAD = "invalid_payload"


class Finding(FrozenModel):
    """Something the snapshot noticed that downstream gates must see."""

    code: str
    kind: FactKind
    entity_key: str
    subject_id: str  # competing_replacement: the replaced fact; invalid_payload: the bad fact
    fact_ids: tuple[str, ...]
    detail: str = ""  # invalid_payload: the FactValidationError code


class Snapshot(FrozenModel):
    cutoff: Instant
    facts: tuple[Fact, ...]
    findings: tuple[Finding, ...]
    digest: str


class NotAnObservation(ValueError):
    """`current()` was asked about an event kind; use `events()`."""


class CurrentStatus(StrEnum):
    FOUND = "found"
    TIE_CONFLICT = "tie_conflict"  # same valid_from, different semantic payloads
    COMPETING = "competing"  # two visible replacements of one target: nothing is picked
    UNKNOWN = "unknown"  # no such entity at this cutoff; never zero


class CurrentResult(FrozenModel):
    status: CurrentStatus
    fact: Fact | None  # the chosen fact, only when FOUND
    # FOUND/TIE_CONFLICT: every fact at the winning valid_from. COMPETING: the competing
    # facts. UNKNOWN: empty.
    facts: tuple[Fact, ...]


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


def _competing(known: list[Fact]) -> list[Finding]:
    """One finding per target with 2+ replacements; `fact_ids` are the tips of each branch.

    A branch is followed to its end (A <- B <- C is the single tip C), so a later
    correction of one competitor is still reported as the competitor.
    """
    by_id = {f.id: f for f in known}
    children: dict[str, list[str]] = defaultdict(list)
    for fact in known:
        if fact.supersedes_id is not None:
            children[fact.supersedes_id].append(fact.id)

    def tips(fact_id: str) -> set[str]:
        kids = children.get(fact_id)
        return {fact_id} if not kids else set().union(*(tips(k) for k in kids))

    findings: list[Finding] = []
    for target, kids in sorted(children.items()):
        if len(kids) > 1:
            first = by_id[kids[0]]
            findings.append(
                Finding(
                    code=COMPETING_REPLACEMENT,
                    kind=first.kind,
                    entity_key=first.entity_key,
                    subject_id=target,
                    fact_ids=tuple(sorted(set().union(*(tips(k) for k in kids)))),
                )
            )
    return findings


def _fact_digest_body(fact: Fact) -> dict[str, object]:
    return {
        "id": fact.id,
        "kind": fact.kind,
        "entity_key": fact.entity_key,
        "valid_from": fact.valid_from,
        "valid_to": fact.valid_to,
        "known_at": fact.known_at,
        "supersedes_id": fact.supersedes_id,
        "source": fact.source,
        "artifact_id": fact.artifact_id,
        "semantic": semantic_digest(fact),
    }


def snapshot_at(facts: Iterable[Fact], cutoff: Instant) -> Snapshot:
    """The as-known view at `cutoff`. The input is never modified.

    A visible fact that fails `validate_fact` is left out of `facts` and reported as an
    `invalid_payload` finding (detail = the error code) for the gate to treat as missing.
    A broken correction graph among visible facts still raises `CorrectionError`.
    """
    all_facts = list(facts)
    known = [f for f in all_facts if f.known_at <= cutoff]
    chosen: list[Fact] = []
    findings = _competing(known)
    for fact in visible(all_facts, cutoff):
        try:
            validate_fact(fact)
        except FactValidationError as exc:
            findings.append(
                Finding(
                    code=INVALID_PAYLOAD,
                    kind=fact.kind,
                    entity_key=fact.entity_key,
                    subject_id=fact.id,
                    fact_ids=(fact.id,),
                    detail=exc.code,
                )
            )
        else:
            chosen.append(fact)
    ordered = tuple(sorted(findings, key=lambda f: (f.code, f.subject_id)))
    body = {
        "cutoff": cutoff,
        "facts": [_fact_digest_body(f) for f in chosen],
        "findings": [f.model_dump(mode="python") for f in ordered],
    }
    return Snapshot(
        cutoff=cutoff, facts=tuple(chosen), findings=ordered, digest=decision_digest(body)
    )


def events(snapshot: Snapshot, kind: FactKind, entity_key: str) -> list[Fact]:
    """Every visible, unsuperseded fact for (kind, entity_key), in deterministic order."""
    return sorted(
        (f for f in snapshot.facts if f.kind == kind and f.entity_key == entity_key),
        key=_sort_key,
    )


def current(snapshot: Snapshot, kind: FactKind, entity_key: str) -> CurrentResult:
    """Observation semantics for one entity: latest valid_from wins; a payload tie conflicts.

    Competing replacements win over everything: if any candidate sits in a
    `competing_replacement` finding the result is COMPETING with those candidates.
    Raises NotAnObservation for event kinds. `valid_to` is ignored.
    """
    if kind in EVENT_KINDS:
        raise NotAnObservation(f"{kind.value} is an event kind; use events()")
    candidates = events(snapshot, kind, entity_key)
    if not candidates:
        return CurrentResult(status=CurrentStatus.UNKNOWN, fact=None, facts=())
    competing_ids = {
        i
        for finding in snapshot.findings
        if finding.code == COMPETING_REPLACEMENT
        for i in finding.fact_ids
    }
    competing = tuple(f for f in candidates if f.id in competing_ids)
    if competing:
        return CurrentResult(status=CurrentStatus.COMPETING, fact=None, facts=competing)
    newest = max(f.valid_from for f in candidates)
    tied = tuple(f for f in candidates if f.valid_from == newest)
    if len({semantic_digest(f) for f in tied}) > 1:
        return CurrentResult(status=CurrentStatus.TIE_CONFLICT, fact=None, facts=tied)
    latest_known = max(tied, key=lambda f: (f.known_at, f.id))
    return CurrentResult(status=CurrentStatus.FOUND, fact=latest_known, facts=tied)
