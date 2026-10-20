"""Versioned issue lexicon: English, Tamil script and Tanglish (romanised Tamil) cues.

Draft — owner (Tamil speaker) review required before the benchmark.

The lists are deliberately modest. A cue hit is evidence that a note is *about* an
issue, used by the `issue_enum_and_lexicon` check; it never decides the issue itself.
Changing any entry requires bumping LEXICON_VERSION.
"""

from __future__ import annotations

import re
from functools import cache

from flooreplay.decisions.extraction.schema import Span, normalize_note

LEXICON_VERSION = "lexicon-v1"

# issue -> (english, tamil script, tanglish)
LEXICON: dict[str, dict[str, tuple[str, ...]]] = {
    "shade_fail": {
        "en": ("shade", "shade variation", "shade band", "colour mismatch", "color mismatch"),
        "ta": ("நிற வேறுபாடு", "நிறம் மாறுபாடு"),
        "tanglish": ("shade problem iruku", "colour sariyilla", "color sariyilla"),
    },
    "gsm_fail": {
        "en": ("gsm", "gsm low", "gsm variation", "gsm mismatch"),
        "ta": ("எடை குறைவு",),
        "tanglish": ("gsm kammi", "gsm kuraivu"),
    },
    "defect": {
        "en": ("hole", "defect", "stain", "damaged"),
        "ta": ("ஓட்டை", "கறை", "குறைபாடு"),
        "tanglish": ("kizhinjiruku", "ottai", "karai"),
    },
}


def _is_latin_cue(cue: str) -> bool:
    return cue.isascii()


@cache
def _patterns(issue: str) -> tuple[re.Pattern[str], ...]:
    groups = LEXICON[issue]  # KeyError on an unknown issue is intentional
    out: list[re.Pattern[str]] = []
    for cue in (c for lang in groups.values() for c in lang):
        body = re.escape(cue).replace(r"\ ", r"\s+")
        if _is_latin_cue(cue):
            # Whole word, plural/-ed allowed: "hole" matches "holes", not "whole".
            out.append(re.compile(rf"(?<!\w){body}(?:s|es|ed)?(?!\w)", re.IGNORECASE))
        else:
            # Tamil is agglutinative and caseless: exact substring, no word boundary.
            out.append(re.compile(body))
    return tuple(out)


def lexicon_hits(text: str, issue: str) -> list[Span]:
    """Non-overlapping cue hits (longest first at equal start), offsets into the NFC text.

    Latin cues match case-insensitively on whole words; Tamil cues match exactly.
    """
    note = normalize_note(text)
    candidates: list[tuple[int, int]] = []
    for pattern in _patterns(issue):
        candidates.extend((m.start(), m.end()) for m in pattern.finditer(note))
    candidates.sort(key=lambda se: (se[0], -(se[1] - se[0])))
    hits: list[Span] = []
    last_end = 0
    for start, end in candidates:
        if start >= last_end and end > start:
            hits.append(Span(start=start, end=end, text=note[start:end]))
            last_end = end
    return hits
