"""Versioned issue lexicon: English, Tamil script and Tanglish (romanised Tamil) cues.

Draft — owner (Tamil speaker) review required before the benchmark. Every cue outside
English carries `owner_review_pending=True`; pending cues are still matched.

The lists are deliberately modest. A cue hit is evidence that a note is *about* an issue,
used by the `issue_enum_and_lexicon` check; it never decides the issue itself.

A cue is a fault statement, not a topic word: bare "shade" and bare "gsm" are not cues
("shade card approved", "gsm 180" say nothing is wrong). They count only inside a fault
phrase or within `PROXIMITY_WINDOW` tokens of a fault word. A hit is blocked when a negator
sits within `NEGATION_WINDOW` tokens of it in the same clause ("no holes", "gsm low
approved", "stain-free", "குறைபாடு இல்லை").

Changing anything in `lexicon_manifest()` requires bumping LEXICON_VERSION and the pinned
digest in the tests.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from collections.abc import Iterator
from dataclasses import dataclass
from functools import cache
from typing import Any, Literal

from flooreplay.decisions.extraction.schema import Span, normalize_note
from flooreplay.decisions.types import decision_digest

LEXICON_VERSION = "lexicon-v2"

# Notes are short supplier messages. Anything longer is not scanned: fail closed.
MAX_NOTE_CODE_POINTS = 5000
NEGATION_WINDOW = 3
PROXIMITY_WINDOW = 3

Lang = Literal["en", "ta", "tanglish"]


class NoteTooLongError(ValueError):
    """The note exceeds MAX_NOTE_CODE_POINTS; it is not scanned (`note_too_long`)."""

    code = "note_too_long"


@dataclass(frozen=True)
class Cue:
    text: str
    lang: Lang
    # True until the owner (a Tamil speaker) has reviewed the cue. Still matched meanwhile.
    owner_review_pending: bool


def _en(text: str) -> Cue:
    return Cue(text, "en", False)


def _ta(text: str) -> Cue:
    return Cue(text, "ta", True)


def _tg(text: str) -> Cue:
    return Cue(text, "tanglish", True)


LEXICON: dict[str, tuple[Cue, ...]] = {
    "shade_fail": (
        _en("shade variation"),
        _en("shade band"),
        _en("shade problem"),
        _en("shade mismatch"),
        _en("colour mismatch"),
        _en("color mismatch"),
        _ta("நிற வேறுபாடு"),
        _ta("நிறம் மாறுபாடு"),
        _tg("shade problem iruku"),
        _tg("colour sariyilla"),
        _tg("color sariyilla"),
    ),
    "gsm_fail": (
        _en("gsm low"),
        _en("gsm variation"),
        _en("gsm mismatch"),
        _ta("எடை குறைவு"),
        _tg("gsm kammi"),
        _tg("gsm kuraivu"),
    ),
    "defect": (
        _en("hole"),
        _en("defect"),
        _en("stain"),
        _en("damaged"),
        _ta("ஓட்டை"),
        _ta("கறை"),
        _ta("குறைபாடு"),
        _tg("kizhinjiruku"),
        _tg("ottai"),
        _tg("karai"),
    ),
}

# Topic words that count as a cue only next to a fault word.
PROXIMITY_STEMS: dict[str, tuple[str, ...]] = {"shade_fail": ("shade",), "gsm_fail": ("gsm",)}
FAULT_WORDS: tuple[str, ...] = (
    "variation",
    "band",
    "problem",
    "issue",
    "mismatch",
    "fail",
    "failed",
    "failure",
    "bad",
    "uneven",
    "low",
    "less",
    "kammi",
    "kuraivu",
    "sariyilla",
)
# Negators that precede the cue ("no holes") and ones that follow it ("holes illa").
PRE_NEGATORS: tuple[str, ...] = ("no", "not", "without")
POST_NEGATORS: tuple[str, ...] = (
    "ok",
    "okay",
    "approved",
    "not",
    "illa",
    "illai",
    "illaa",
    "இல்லை",
    "இல்ல",
)
NEGATING_SUFFIXES: tuple[str, ...] = ("-free",)
# Sentence/clause punctuation stops both windows. A "." or "," only counts before whitespace.
CLAUSE_BREAK = r"[;:!?\n()|।]|[,.](?=\s|$)"

_BREAK_RE = re.compile(CLAUSE_BREAK)
_TOKEN_RE = re.compile(r"\S+")
_TOKEN_PUNCT = "\"'`()[]{}.,;:!?-_/"
# Tamil letters and signs. A Tamil cue must not start inside a word, nor stop before a sign.
_TAMIL_LETTER_OR_SIGN = "\u0b80-\u0bff"
_TAMIL_COMBINING = "\u0b82\u0bbe-\u0bcd\u0bd7"


def lexicon_manifest() -> dict[str, Any]:
    """Everything that changes what the lexicon matches, as plain data."""
    return {
        "lexicon": {
            issue: [
                {"text": c.text, "lang": c.lang, "owner_review_pending": c.owner_review_pending}
                for c in cues
            ]
            for issue, cues in LEXICON.items()
        },
        "proximity_stems": {k: list(v) for k, v in PROXIMITY_STEMS.items()},
        "fault_words": list(FAULT_WORDS),
        "pre_negators": list(PRE_NEGATORS),
        "post_negators": list(POST_NEGATORS),
        "negating_suffixes": list(NEGATING_SUFFIXES),
        "negation_window": NEGATION_WINDOW,
        "proximity_window": PROXIMITY_WINDOW,
        "clause_break": CLAUSE_BREAK,
        "max_note_code_points": MAX_NOTE_CODE_POINTS,
    }


def lexicon_digest() -> str:
    return decision_digest(lexicon_manifest())


@cache
def _patterns(issue: str) -> tuple[re.Pattern[str], ...]:
    cues = LEXICON[issue]  # KeyError on an unknown issue is intentional
    out: list[re.Pattern[str]] = []
    for cue in cues:
        body = re.escape(cue.text).replace(r"\ ", r"\s+")
        if cue.text.isascii():
            # Whole word, plural/-ed allowed: "hole" matches "holes", not "whole".
            out.append(re.compile(rf"(?<!\w){body}(?:s|es|ed)?(?!\w)", re.IGNORECASE))
        else:
            # Tamil is agglutinative and caseless: suffixes may follow, but the cue must
            # not begin inside another word nor stop before a vowel sign / virama.
            out.append(re.compile(rf"(?<![{_TAMIL_LETTER_OR_SIGN}]){body}(?![{_TAMIL_COMBINING}])"))
    return tuple(out)


@cache
def _stem_pattern(stem: str) -> re.Pattern[str]:
    return re.compile(rf"(?<!\w){re.escape(stem)}(?:s)?(?!\w)", re.IGNORECASE)


@dataclass(frozen=True)
class _Tok:
    start: int
    end: int
    norm: str


class _Note:
    """An NFC note with its clause breaks, for window queries."""

    def __init__(self, text: str) -> None:
        self.text = normalize_note(text)
        if len(self.text) > MAX_NOTE_CODE_POINTS:
            raise NoteTooLongError(
                f"note has {len(self.text)} code points; the limit is {MAX_NOTE_CODE_POINTS}"
            )
        breaks = [m.span() for m in _BREAK_RE.finditer(self.text)]
        self._break_starts = [s for s, _ in breaks]
        self._breaks = breaks

    def clause_start(self, pos: int) -> int:
        """Start of the clause containing `pos` (the end of the last break before it)."""
        i = bisect_right(self._break_starts, pos - 1) - 1
        return self._breaks[i][1] if i >= 0 else 0

    def clause_end(self, pos: int) -> int:
        i = bisect_right(self._break_starts, pos - 1)
        return self._breaks[i][0] if i < len(self._breaks) else len(self.text)

    def tokens(self, lo: int, hi: int) -> list[_Tok]:
        out: list[_Tok] = []
        for m in _TOKEN_RE.finditer(self.text, lo, hi):
            raw = m.group(0)
            core = raw.strip(_TOKEN_PUNCT)
            if not core:
                continue
            start = m.start() + (len(raw) - len(raw.lstrip(_TOKEN_PUNCT)))
            out.append(_Tok(start, start + len(core), core.casefold()))
        return out

    def before(self, start: int, n: int) -> list[_Tok]:
        return self.tokens(self.clause_start(start), start)[-n:]

    def after(self, end: int, n: int) -> list[_Tok]:
        return self.tokens(end, self.clause_end(end))[:n]

    def negated(self, start: int, end: int) -> bool:
        tail = self.text[end : end + max(len(s) for s in NEGATING_SUFFIXES)].casefold()
        if any(tail.startswith(s) for s in NEGATING_SUFFIXES):
            return True
        if any(_is(t.norm, PRE_NEGATORS) for t in self.before(start, NEGATION_WINDOW)):
            return True
        return any(_is(t.norm, POST_NEGATORS) for t in self.after(end, NEGATION_WINDOW))

    def candidates(self, issue: str) -> Iterator[tuple[int, int]]:
        for pattern in _patterns(issue):
            for m in pattern.finditer(self.text):
                yield m.start(), m.end()
        for stem in PROXIMITY_STEMS.get(issue, ()):
            for m in _stem_pattern(stem).finditer(self.text):
                fault = next(
                    (t for t in self.after(m.end(), PROXIMITY_WINDOW) if t.norm in FAULT_WORDS),
                    None,
                )
                if fault is not None:
                    yield m.start(), fault.end
                    continue
                fault = next(
                    (t for t in self.before(m.start(), PROXIMITY_WINDOW) if t.norm in FAULT_WORDS),
                    None,
                )
                if fault is not None:
                    yield fault.start, m.end()

    def live_candidates(self, issue: str) -> Iterator[tuple[int, int]]:
        return ((s, e) for s, e in self.candidates(issue) if e > s and not self.negated(s, e))


def _is(token: str, negators: tuple[str, ...]) -> bool:
    # Tamil words take suffixes: "இல்லாமல்" starts with the negator "இல்ல".
    return any(token == n or (not n.isascii() and token.startswith(n)) for n in negators)


def lexicon_hits(text: str, issue: str) -> list[Span]:
    """Non-overlapping, non-negated cue hits (longest first at equal start), NFC offsets.

    Latin cues match case-insensitively on whole words; Tamil cues match exactly and never
    from the middle of a word. Raises `NoteTooLongError` for notes over
    MAX_NOTE_CODE_POINTS and `KeyError` for an unknown issue.
    """
    _patterns(issue)  # validate the issue before touching the note
    note = _Note(text)
    candidates = sorted(note.live_candidates(issue), key=lambda se: (se[0], -(se[1] - se[0])))
    hits: list[Span] = []
    last_end = 0
    for start, end in candidates:
        if start >= last_end:
            hits.append(Span(start=start, end=end, text=note.text[start:end]))
            last_end = end
    return hits


def has_issue_cue(text: str, issue: str | None = None) -> bool:
    """Fast path: is there any live cue (for `issue`, or for any issue)? Stops at the first.

    Raises `NoteTooLongError` like `lexicon_hits`: a note that is not scanned must not be
    read as "no cue".
    """
    issues = list(LEXICON) if issue is None else [issue]
    for name in issues:
        _patterns(name)
    note = _Note(text)
    return any(next(note.live_candidates(name), None) is not None for name in issues)
