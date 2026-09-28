"""Held-out floor notes for parser evaluation.

These notes were written AFTER the parser rules were frozen and were never
used to develop or tune either parser. The labels state what a careful human
would extract, not what any parser happens to produce — so misses are real
measurements, not bugs in the fixture set. Scoring semantics:

- event_category: OPERATOR_UNAVAILABLE vs UNSUPPORTED
- subject_operator_ids: the operators the NOTE says are unavailable
  (a "will cover" operator is not a subject)
- operation_ids: operations the note asks to cover
- uncertainty: the note hedges the absence itself ("might", "may be"),
  not unrelated hedging

The rule baseline is EXPECTED to miss the hard cases here; that is what the
evaluation exists to measure and document, not to hide.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NoteCase:
    id: str
    note: str
    event_category: str
    subject_operator_ids: tuple[str, ...] = ()
    operation_ids: tuple[str, ...] = ()
    uncertainty: bool = False
    probes: str = ""


HELD_OUT_NOTES: tuple[NoteCase, ...] = (
    NoteCase(
        id="NOTE-E01",
        note="O117 will not be in today. Sleeve attach on Line 4 will need cover.",
        event_category="OPERATOR_UNAVAILABLE",
        subject_operator_ids=("O117",),
        operation_ids=("OP-SLM",),
        probes="clean exact-id unavailability with operation",
    ),
    NoteCase(
        id="NOTE-E02",
        note="R. Balamurugan reported sick this morning.",
        event_category="OPERATOR_UNAVAILABLE",
        subject_operator_ids=("O117",),
        probes="display name instead of id",
    ),
    NoteCase(
        id="NOTE-E03",
        note="O204 might not come in today, not sure yet.",
        event_category="OPERATOR_UNAVAILABLE",
        subject_operator_ids=("O204",),
        uncertainty=True,
        probes="hedged absence; colloquial 'not come'",
    ),
    NoteCase(
        id="NOTE-E04",
        note="Please reschedule the line so we can clear the KST-411 order today.",
        event_category="UNSUPPORTED",
        probes="out-of-scope planning request",
    ),
    NoteCase(
        id="NOTE-E05",
        note="Our sleeve attach operator is absent today, Line 4.",
        event_category="OPERATOR_UNAVAILABLE",
        subject_operator_ids=(),
        operation_ids=("OP-SLM",),
        probes="unavailability without any operator id; manual resolution path",
    ),
    NoteCase(
        id="NOTE-E06",
        note="O112 and O130 are both on leave today.",
        event_category="OPERATOR_UNAVAILABLE",
        subject_operator_ids=("O112", "O130"),
        probes="two subjects in one note",
    ),
    NoteCase(
        id="NOTE-E07",
        note="O219 informed that he will be unavailable on 2026-09-30 from 06:00.",
        event_category="OPERATOR_UNAVAILABLE",
        subject_operator_ids=("O219",),
        probes="future-dated ISO instant",
    ),
    NoteCase(
        id="NOTE-E08",
        note="S. Deepika cannot work today — collar join needs cover on Line 3.",
        event_category="OPERATOR_UNAVAILABLE",
        subject_operator_ids=("O108",),
        operation_ids=("OP-COL",),
        probes="display name plus operation",
    ),
    NoteCase(
        id="NOTE-E09",
        note="O117 says he is NOT absent, he will be in and cover his machine.",
        event_category="UNSUPPORTED",
        probes="denied absence: the word 'absent' appears but the event is denied",
    ),
    NoteCase(
        id="NOTE-E10",
        note="O133 is on leave; O158 will cover sleeve attach for him.",
        event_category="OPERATOR_UNAVAILABLE",
        subject_operator_ids=("O133",),
        operation_ids=("OP-SLM",),
        probes="subject vs cover-provider distinction",
    ),
    NoteCase(
        id="NOTE-E11",
        note="Line 4 bar-tack: O190 is absent.",
        event_category="OPERATOR_UNAVAILABLE",
        subject_operator_ids=("O190",),
        operation_ids=("OP-BTK",),
        probes="operation-first phrasing",
    ),
    NoteCase(
        id="NOTE-E12",
        note="Change the plan for tomorrow, the KST-208 order moved.",
        event_category="UNSUPPORTED",
        probes="out-of-scope planning request, second phrasing",
    ),
    NoteCase(
        id="NOTE-E13",
        note="O177 can't make it in today, family emergency.",
        event_category="OPERATOR_UNAVAILABLE",
        subject_operator_ids=("O177",),
        probes="contraction phrasing",
    ),
    NoteCase(
        id="NOTE-E14",
        note="O196 may be late by 30 minutes.",
        event_category="UNSUPPORTED",
        subject_operator_ids=(),
        uncertainty=True,
        probes="late arrival is not a slot vacancy",
    ),
    NoteCase(
        id="NOTE-E15",
        note="O152 reported sick. Hem lock coverage needed on Line 4.",
        event_category="OPERATOR_UNAVAILABLE",
        subject_operator_ids=("O152",),
        operation_ids=("OP-HLM",),
        probes="two sentences, subject then operation",
    ),
    NoteCase(
        id="NOTE-E16",
        note="Balamurugan is absent today.",
        event_category="OPERATOR_UNAVAILABLE",
        subject_operator_ids=("O117",),
        probes="surname-only mention; resolution must stay honest (no fuzzy guess)",
    ),
)


def case_labels(case: NoteCase) -> dict[str, object]:
    """The label dict the scorer compares the resolved draft against."""
    return {
        "event_category": case.event_category,
        "subject_operator_ids": list(case.subject_operator_ids),
        "operation_ids": list(case.operation_ids),
        "uncertainty": case.uncertainty,
    }


__all__ = ["HELD_OUT_NOTES", "NoteCase", "case_labels"]
