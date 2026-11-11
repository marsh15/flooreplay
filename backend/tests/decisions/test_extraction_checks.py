"""Extraction core: schema, lexicon, deterministic checks and provider doubles."""

from __future__ import annotations

import copy
import unicodedata
from decimal import Decimal
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from flooreplay.decisions.extraction.checks import (
    CHECKS_VERSION,
    LOT_ID_PATTERN,
    ChecksOutcome,
    CheckStatus,
    FieldStatus,
    SignalOutcome,
    locate_evidence,
    parse_qty,
    run_checks,
)
from flooreplay.decisions.extraction.lexicon import (
    LEXICON,
    LEXICON_VERSION,
    MAX_NOTE_CODE_POINTS,
    NoteTooLongError,
    has_issue_cue,
    lexicon_digest,
    lexicon_hits,
)
from flooreplay.decisions.extraction.provider import (
    GenerationProvider,
    MockProvider,
    ProviderCalledError,
    ProviderResult,
    RaisingProvider,
    empty_signal_raw,
)
from flooreplay.decisions.extraction.schema import (
    OPTIONAL_FIELDS,
    REQUIRED_FIELDS,
    SCHEMA_VERSION,
    SIGNAL_FIELDS,
    FieldValue,
    NoteSignal,
    SignalValidationError,
    Span,
    normalize_note,
    note_digest,
    note_signal_json_schema,
    validate_signal_payload,
)
from flooreplay.decisions.types import ReviewState, decision_digest

KNOWN = {"L-1042", "L-77"}
ALL_LOTS = {"L-1042", "L-77", "L-221", "L-1234", "L-12"}
FIELDS = ("lot_id", "issue", "qty", "unit", "colour", "fabric_quality")


def empty_fv() -> FieldValue:
    return FieldValue(value=None, evidence=None)


def mk(note: str, **spec: Any) -> NoteSignal:
    """Build a signal. Each field: absent/None, an evidence string, or (evidence, value)."""
    kw: dict[str, FieldValue] = {}
    for f in FIELDS:
        s = spec.get(f)
        if s is None:
            kw[f] = empty_fv()
        elif isinstance(s, str):
            kw[f] = FieldValue(value=s, evidence=s)
        else:
            kw[f] = FieldValue(value=s[1], evidence=s[0])
    return NoteSignal(language="en", **kw)


def run(note: str, known: Any = ALL_LOTS, **spec: Any) -> ChecksOutcome:
    return run_checks(note, mk(note, **spec), known)


def status(out: ChecksOutcome, field: str) -> FieldStatus:
    return next(f for f in out.fields if f.field == field).status


def fail_codes(out: ChecksOutcome, field: str) -> set[tuple[str, str]]:
    return {
        (r.check, r.code)
        for r in out.results
        if r.field == field and r.status != CheckStatus.PASSED
    }


def check_code(out: ChecksOutcome, field: str, check: str) -> str:
    return next(r.code for r in out.results if r.field == field and r.check == check)


GOOD_NOTE = "Lot L-1042 navy single jersey: shade variation, 1,200 kg held."
GOOD_SPEC: dict[str, Any] = {
    "lot_id": "L-1042",
    "issue": ("shade variation", "shade_fail"),
    "qty": ("1,200 kg", "1200"),
    "unit": "kg",
    "colour": ("navy", "NAVY"),
    "fabric_quality": ("single jersey", "Single Jersey"),
}


def good_signal() -> NoteSignal:
    return mk(GOOD_NOTE, **GOOD_SPEC)


def good_raw() -> dict[str, Any]:
    return good_signal().model_dump(mode="json")


# ---------------------------------------------------------------- versions


def test_version_constants():
    assert SCHEMA_VERSION == "note-signal-v2"
    assert LEXICON_VERSION == "lexicon-v2"
    assert CHECKS_VERSION == "checks-v2"
    assert LOT_ID_PATTERN == r"^L-\d{2,5}$"
    assert REQUIRED_FIELDS == ("lot_id", "issue", "qty", "unit")
    assert OPTIONAL_FIELDS == ("colour", "fabric_quality")
    assert SIGNAL_FIELDS == FIELDS


# Editing the lexicon (cues, negators, fault words, windows) must bump LEXICON_VERSION and
# add the new digest here. Stored extractions record lexicon_version; a silent edit would
# make the recorded version lie.
PINNED_LEXICON_DIGESTS = {
    "lexicon-v2": "sha256:eb196ffba0bc2ba7cd552f52bbb9af1d8ac3c09625310b61a7d373a0609bf941",
}


def test_lexicon_digest_is_pinned_to_its_version():
    assert LEXICON_VERSION in PINNED_LEXICON_DIGESTS
    assert lexicon_digest() == PINNED_LEXICON_DIGESTS[LEXICON_VERSION]


# ---------------------------------------------------------------- schema


def test_validate_roundtrip_accepts_digits():
    # Regression against the v1 `_numeric_prose` trap: digits in values are the point here.
    raw = good_raw()
    assert raw["qty"] == {"value": "1200", "evidence": "1,200 kg"}
    sig = validate_signal_payload(raw)
    assert sig.qty.value == "1200"
    assert sig.lot_id.value == "L-1042"
    assert sig.model_dump(mode="json") == raw


def test_field_has_value_and_evidence_but_no_offsets():
    assert set(FieldValue.model_fields) == {"value", "evidence"}
    raw = good_raw()
    raw["qty"]["span"] = {"start": 0, "end": 1, "text": "x"}
    with pytest.raises(SignalValidationError):
        validate_signal_payload(raw)
    raw = good_raw()
    raw["qty"]["start"] = 3
    with pytest.raises(SignalValidationError):
        validate_signal_payload(raw)


def test_null_field_is_accepted_as_absent():
    raw = good_raw()
    raw["colour"] = None
    sig = validate_signal_payload(raw)
    assert sig.colour == empty_fv()


def test_unknown_top_level_key_rejected():
    raw = good_raw()
    raw["confidence"] = "high"
    with pytest.raises(SignalValidationError):
        validate_signal_payload(raw)


def test_unknown_nested_keys_rejected():
    raw = good_raw()
    raw["qty"]["extra"] = "x"
    with pytest.raises(SignalValidationError):
        validate_signal_payload(raw)


def test_missing_key_and_bad_language_rejected():
    raw = good_raw()
    del raw["colour"]
    with pytest.raises(SignalValidationError):
        validate_signal_payload(raw)
    raw = good_raw()
    raw["language"] = "hindi"
    with pytest.raises(SignalValidationError):
        validate_signal_payload(raw)


def test_numeric_json_types_rejected_for_text_values():
    raw = good_raw()
    raw["qty"]["value"] = 1200
    with pytest.raises(SignalValidationError):
        validate_signal_payload(raw)


def test_non_dict_rejected():
    with pytest.raises(SignalValidationError):
        validate_signal_payload([1, 2])  # type: ignore[arg-type]


def test_span_requires_ordered_nonnegative_offsets():
    with pytest.raises(ValueError):
        Span(start=-1, end=2, text="ab")
    with pytest.raises(ValueError):
        Span(start=5, end=2, text="")


def _walk(node: Any):
    yield node
    if isinstance(node, dict):
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def test_json_schema_shape():
    schema = note_signal_json_schema()
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    props = schema["properties"]
    assert set(props) == {*FIELDS, "language"}
    assert set(schema["required"]) == set(props)
    assert "$ref" not in str(schema)
    assert set(props["language"]["enum"]) == {"en", "ta", "tanglish", "mixed"}
    # a fresh copy each call
    schema["properties"].clear()
    assert note_signal_json_schema()["properties"]


def _field_object(prop: dict[str, Any]) -> dict[str, Any]:
    branches = prop["anyOf"]
    obj = next(b for b in branches if b.get("type") == "object")
    assert {"type": "null"} in branches
    return obj


def test_json_schema_fields_are_nullable_value_evidence_objects():
    props = note_signal_json_schema()["properties"]
    for f in FIELDS:
        obj = _field_object(props[f])
        assert set(obj["properties"]) == {"value", "evidence"}
        assert obj["required"] == ["value", "evidence"]
        assert obj["additionalProperties"] is False
        assert obj["properties"]["value"]["type"] == "string"
        assert obj["properties"]["evidence"]["type"] == "string"
    issue = _field_object(props["issue"])["properties"]["value"]
    assert set(issue["enum"]) == {"shade_fail", "gsm_fail", "defect"}
    unit = _field_object(props["unit"])["properties"]["value"]
    assert set(unit["enum"]) == {"kg", "m"}


def test_json_schema_is_openai_strict_and_provider_friendly():
    schema = note_signal_json_schema()
    banned = {"minimum", "maximum", "minLength", "maxLength", "pattern", "format", "title"}
    unions = 0
    for node in _walk(schema):
        if not isinstance(node, dict):
            continue
        if "properties" in node:  # an object schema (its keys are field names, not keywords)
            assert node["additionalProperties"] is False
            assert set(node["required"]) == set(node["properties"])
            keywords = set(node) - {"properties"}
        else:
            keywords = set(node)
        assert not keywords & banned, keywords
        unions += sum(k in node for k in ("anyOf", "oneOf")) + isinstance(node.get("type"), list)
    assert unions <= 8


def test_json_schema_has_a_description_per_field():
    props = note_signal_json_schema()["properties"]
    for f in (*FIELDS, "language"):
        assert props[f]["description"].strip()
    for f in FIELDS:
        assert "null" in props[f]["description"]
        assert "exact" in props[f]["description"]


# ---------------------------------------------------------------- lexicon


def test_lexicon_english_case_insensitive():
    hits = lexicon_hits("Big SHADE Variation seen", "shade_fail")
    assert [h.text for h in hits] == ["SHADE Variation"]
    assert hits[0].start == 4


def test_lexicon_word_boundary_avoids_whole():
    assert lexicon_hits("whole roll is fine", "defect") == []
    assert [h.text for h in lexicon_hits("two holes found", "defect")] == ["holes"]


def test_lexicon_tanglish():
    note = "lot L-77 la shade problem iruku, colour sariyilla"
    texts = [h.text for h in lexicon_hits(note, "shade_fail")]
    assert "shade problem iruku" in texts
    assert "colour sariyilla" in texts
    assert [h.text for h in lexicon_hits("gsm kammi aagiduchu", "gsm_fail")] == ["gsm kammi"]
    assert [h.text for h in lexicon_hits("roll la kizhinjiruku", "defect")] == ["kizhinjiruku"]


def test_lexicon_tamil_script():
    note = "இந்த ரோலில் ஓட்டை உள்ளது"
    hits = lexicon_hits(note, "defect")
    assert [h.text for h in hits] == ["ஓட்டை"]
    assert note[hits[0].start : hits[0].end] == "ஓட்டை"
    assert lexicon_hits("எடை குறைவு", "gsm_fail")
    assert lexicon_hits("நிற வேறுபாடு", "shade_fail")
    assert lexicon_hits("கறை இருக்கு", "defect")


def test_lexicon_hits_nonoverlapping_prefers_longest_and_issues_separate():
    hits = lexicon_hits("shade variation", "shade_fail")
    assert [h.text for h in hits] == ["shade variation"]
    assert lexicon_hits("shade variation", "gsm_fail") == []


def test_lexicon_nfd_input_is_normalised_and_offsets_are_nfc():
    nfc = "கொஞ்சம் ஓட்டை"
    nfd = unicodedata.normalize("NFD", nfc)
    assert len(nfd) > len(nfc)  # the vowel sign decomposes: offsets would shift
    hits = lexicon_hits(nfd, "defect")
    assert len(hits) == 1
    assert normalize_note(nfd)[hits[0].start : hits[0].end] == "ஓட்டை"
    assert hits[0].start == nfc.index("ஓட்டை")


def test_lexicon_unknown_issue_raises():
    with pytest.raises(KeyError):
        lexicon_hits("x", "late_delivery")
    with pytest.raises(KeyError):
        has_issue_cue("x", "late_delivery")


@pytest.mark.parametrize(
    "note,issue",
    [
        ("shade", "shade_fail"),
        ("shade card", "shade_fail"),
        ("gsm", "gsm_fail"),
        ("gsm 180", "gsm_fail"),
        ("lot L-77 shade, 50 kg", "shade_fail"),
    ],
)
def test_bare_shade_and_gsm_are_not_cues(note, issue):
    assert lexicon_hits(note, issue) == []


@pytest.mark.parametrize(
    "note,issue,text",
    [
        ("shade variation", "shade_fail", "shade variation"),
        ("a shade band seen", "shade_fail", "shade band"),
        ("shade problem", "shade_fail", "shade problem"),
        ("gsm low", "gsm_fail", "gsm low"),
        ("gsm kammi", "gsm_fail", "gsm kammi"),
        ("shade is bad", "shade_fail", "shade is bad"),
        ("gsm 180 low", "gsm_fail", "gsm 180 low"),
        ("low gsm", "gsm_fail", "low gsm"),
    ],
)
def test_fault_phrases_and_nearby_fault_words_are_cues(note, issue, text):
    assert [h.text for h in lexicon_hits(note, issue)] == [text]


def test_fault_word_beyond_three_tokens_is_not_a_cue():
    assert lexicon_hits("shade one two three low", "shade_fail") == []
    assert [h.text for h in lexicon_hits("shade one two low", "shade_fail")] == [
        "shade one two low"
    ]
    # a clause break stops the window
    assert lexicon_hits("shade, low", "shade_fail") == []


@pytest.mark.parametrize(
    "note",
    [
        "shade card approved",
        "gsm 180 ok",
        "no holes, no stain",
        "குறைபாடு இல்லை",
        "stain-free",
        "holes illa",
        "stain illai",
        "ஓட்டை இல்ல",
        "without damaged rolls",
        "not damaged",
        "shade variation ok",
        "gsm low approved",
    ],
)
def test_negated_notes_yield_no_cue_for_any_issue(note):
    for issue in LEXICON:
        assert lexicon_hits(note, issue) == [], (note, issue)
    assert not has_issue_cue(note)


def test_negation_is_directional_and_stops_at_clause_breaks():
    # "ok" belongs to the shade clause; it must not hide the holes that follow it.
    note = "L-221 shade ok but 20 holes, 50 kg"
    assert [h.text for h in lexicon_hits(note, "defect")] == ["holes"]
    # "no" in an earlier clause does not reach across the comma.
    assert lexicon_hits("no stain on roll", "defect") == []
    assert [h.text for h in lexicon_hits("no stain on roll, holes seen", "defect")] == ["holes"]
    assert [h.text for h in lexicon_hits("no shade card, holes seen", "defect")] == ["holes"]


def test_tamil_cue_must_not_start_inside_another_word():
    # கறை inside புகறையாக is not the stain cue.
    assert lexicon_hits("புகறையாக", "defect") == []
    assert [h.text for h in lexicon_hits("துணியில் கறை", "defect")] == ["கறை"]


def test_owner_review_pending_flags():
    cues = {c.text: c for issue in LEXICON.values() for c in issue}
    assert cues["karai"].owner_review_pending
    assert cues["ottai"].owner_review_pending
    for cue in cues.values():
        non_latin = not cue.text.isascii()
        if cue.lang in ("ta", "tanglish") or non_latin:
            assert cue.owner_review_pending, cue.text
        else:
            assert cue.lang == "en" and not cue.owner_review_pending, cue.text
    # pending cues still match
    assert lexicon_hits("ottai iruku", "defect")
    assert lexicon_hits("ஓட்டை இருக்கு", "defect")


def test_cue_text_is_nfc_and_languages_known():
    for issue in LEXICON.values():
        for cue in issue:
            assert normalize_note(cue.text) == cue.text
            assert cue.lang in ("en", "ta", "tanglish")


def test_has_issue_cue_fast_path():
    assert has_issue_cue("two holes found")
    assert has_issue_cue("two holes found", "defect")
    assert not has_issue_cue("two holes found", "gsm_fail")
    assert not has_issue_cue("all fine")
    assert not has_issue_cue("")


def test_overlong_notes_fail_closed():
    note = "holes " + "a" * MAX_NOTE_CODE_POINTS
    assert len(note) > MAX_NOTE_CODE_POINTS
    with pytest.raises(NoteTooLongError):
        lexicon_hits(note, "defect")
    with pytest.raises(NoteTooLongError):
        has_issue_cue(note)
    ok = "holes " + "a" * (MAX_NOTE_CODE_POINTS - 6)
    assert len(ok) == MAX_NOTE_CODE_POINTS
    assert lexicon_hits(ok, "defect")


def test_note_too_long_fails_every_claimed_field_in_checks():
    pad = "x" * MAX_NOTE_CODE_POINTS
    note = f"L-77 holes 50 kg {pad}"
    out = run(note, lot_id="L-77", issue=("holes", "defect"), qty=("50", "50"), unit="kg")
    assert out.review_state == ReviewState.NEEDS_REVIEW
    assert ("note_length", "note_too_long") in fail_codes(out, "issue")
    # a null signal on an overlong note is still not silently "no signal"
    empty = run_checks(note, mk(note), ALL_LOTS)
    assert empty.review_state == ReviewState.NEEDS_REVIEW
    assert empty.outcome == SignalOutcome.NEEDS_REVIEW


# ---------------------------------------------------------------- evidence location


def test_locate_unique_evidence_gives_code_point_span():
    nfc = normalize_note("லாட் L-77 ஓட்டை")
    loc = locate_evidence("லாட் L-77 ஓட்டை", "ஓட்டை")
    assert loc.code == "ok"
    assert loc.span is not None
    assert nfc[loc.span.start : loc.span.end] == "ஓட்டை" == loc.span.text
    assert loc.span.end - loc.span.start == 5


def test_locate_zero_and_many():
    assert locate_evidence("abc", "x").code == "span_not_found"
    assert locate_evidence("abc", "x").span is None
    assert locate_evidence("a b a", "a").code == "ambiguous_span"
    # overlapping occurrences are ambiguous too
    assert locate_evidence("aaa", "aa").code == "ambiguous_span"
    assert locate_evidence("abc", "").code == "span_not_found"


def test_locate_normalises_evidence_and_note_to_nfc():
    nfc = "கொஞ்சம் ஓட்டை"
    nfd = unicodedata.normalize("NFD", nfc)
    a = locate_evidence(nfd, unicodedata.normalize("NFD", "ஓட்டை"))
    b = locate_evidence(nfc, "ஓட்டை")
    assert a.span == b.span and a.span is not None


def test_checks_report_span_not_found_and_ambiguous_span():
    out = run("L-77 holes 50 kg", lot_id="L-78", issue=("holes", "defect"))
    assert status(out, "lot_id") == FieldStatus.FAILED
    assert ("span_located", "span_not_found") in fail_codes(out, "lot_id")
    note = "L-77 holes, more holes 50 kg"
    out = run(note, issue=("holes", "defect"))
    assert ("span_located", "ambiguous_span") in fail_codes(out, "issue")
    assert out.review_state == ReviewState.NEEDS_REVIEW


def test_located_span_is_recorded_in_the_outcome():
    out = run_checks(GOOD_NOTE, good_signal(), {"L-1042"})
    f = next(x for x in out.fields if x.field == "lot_id")
    assert f.span == Span(
        start=GOOD_NOTE.index("L-1042"), end=GOOD_NOTE.index("L-1042") + 6, text="L-1042"
    )


# ---------------------------------------------------------------- run_checks: pass paths


def test_run_checks_all_pass_and_is_self_describing():
    out = run_checks(GOOD_NOTE, good_signal(), {"L-1042", "L-77"})
    assert out.failed_fields == ()
    assert out.review_state == ReviewState.CHECKS_PASSED
    assert out.outcome == SignalOutcome.CHECKS_PASSED
    assert all(r.status == CheckStatus.PASSED for r in out.results)
    assert out.checks_version == CHECKS_VERSION == "checks-v2"
    assert out.lexicon_version == LEXICON_VERSION
    assert out.schema_version == SCHEMA_VERSION
    assert out.lot_pattern == LOT_ID_PATTERN
    assert out.known_lots_digest == decision_digest(["L-1042", "L-77"])
    assert out.note_digest == note_digest(GOOD_NOTE)
    values = {f.field: f.value for f in out.fields}
    assert values["qty"] == "1200"
    assert values["lot_id"] == "L-1042"
    assert values["issue"] == "shade_fail"
    assert values["unit"] == "kg"
    names = {(r.field, r.check) for r in out.results}
    assert ("lot_id", "lot_regex") in names
    assert ("lot_id", "entity_exists") in names
    assert ("issue", "issue_enum_and_lexicon") in names
    assert ("qty", "value_reparses") in names
    for f in FIELDS:
        assert any(r.field == f and r.check == "span_located" and r.passed for r in out.results)


def test_outcome_digest_is_stable_and_sensitive():
    a = run_checks(GOOD_NOTE, good_signal(), {"L-1042", "L-77"})
    b = run_checks(GOOD_NOTE, good_signal(), ["L-77", "L-1042", "L-77"])
    assert a == b
    assert a.canonical_digest() == b.canonical_digest()
    assert a.canonical_digest().startswith("sha256:")
    assert a.canonical_payload()["known_lots_digest"] == a.known_lots_digest
    c = run_checks(GOOD_NOTE, good_signal(), {"L-1042"})
    assert c.known_lots_digest != a.known_lots_digest
    assert c.canonical_digest() != a.canonical_digest()
    # the payload survives a JSON round trip unchanged
    import json

    assert json.loads(json.dumps(a.canonical_payload())) == a.canonical_payload()


def test_run_checks_is_deterministic():
    a = run_checks(GOOD_NOTE, good_signal(), KNOWN)
    b = run_checks(GOOD_NOTE, good_signal(), KNOWN)
    assert a == b


def test_run_checks_unknown_lot_needs_review():
    out = run_checks(GOOD_NOTE, good_signal(), {"L-9999"})
    assert out.review_state == ReviewState.NEEDS_REVIEW
    assert out.failed_fields == ("lot_id",)
    assert ("entity_exists", "unknown_lot") in fail_codes(out, "lot_id")


def test_run_checks_lying_value_is_isolated_to_its_field():
    out = run_checks(GOOD_NOTE, mk(GOOD_NOTE, **{**GOOD_SPEC, "qty": ("1,200 kg", "2400")}), KNOWN)
    assert out.failed_fields == ("qty",)
    assert ("value_reparses", "value_mismatch") in fail_codes(out, "qty")


def test_run_checks_tamil_note_end_to_end_with_nfd_input():
    nfc = "லாட் L-77 ல் ஓட்டை, 300 m கொஞ்சம் NAVY SJ180"
    note = unicodedata.normalize("NFD", nfc)
    out = run_checks(
        note,
        mk(
            note,
            lot_id="L-77",
            issue=("ஓட்டை", "defect"),
            qty=("300", "300"),
            unit="m",
            colour="NAVY",
            fabric_quality="SJ180",
        ),
        KNOWN,
    )
    assert out.failed_fields == (), [r for r in out.results if not r.passed]
    assert out.review_state == ReviewState.CHECKS_PASSED


def test_provider_signal_with_nfd_evidence_is_located():
    nfc = "லாட் L-77 ல் ஓட்டை, 300 m"
    out = run_checks(
        nfc,
        NoteSignal(
            language="ta",
            lot_id=FieldValue(value="L-77", evidence="L-77"),
            issue=FieldValue(value="defect", evidence=unicodedata.normalize("NFD", "ஓட்டை")),
            qty=FieldValue(value="300", evidence="300"),
            unit=FieldValue(value="m", evidence="m"),
            colour=empty_fv(),
            fabric_quality=empty_fv(),
        ),
        KNOWN,
    )
    assert out.review_state == ReviewState.CHECKS_PASSED, out.failed_fields


# ---------------------------------------------------------------- required / optional / no_signal


def test_optional_fields_may_be_null():
    spec = {k: v for k, v in GOOD_SPEC.items() if k in REQUIRED_FIELDS}
    out = run_checks(GOOD_NOTE, mk(GOOD_NOTE, **spec), KNOWN)
    assert out.review_state == ReviewState.CHECKS_PASSED
    assert out.failed_fields == ()
    assert status(out, "colour") == FieldStatus.MISSING
    assert status(out, "fabric_quality") == FieldStatus.MISSING
    assert all(r.status == CheckStatus.MISSING for r in out.results if r.field == "colour")


@pytest.mark.parametrize("field", REQUIRED_FIELDS)
def test_required_field_missing_needs_review(field):
    spec = {k: v for k, v in GOOD_SPEC.items() if k != field}
    out = run_checks(GOOD_NOTE, mk(GOOD_NOTE, **spec), KNOWN)
    assert out.review_state == ReviewState.NEEDS_REVIEW
    assert field in out.failed_fields
    assert status(out, field) == FieldStatus.MISSING
    assert all(r.status == CheckStatus.MISSING for r in out.results if r.field == field)


@pytest.mark.parametrize("field", OPTIONAL_FIELDS)
def test_optional_field_present_but_wrong_fails(field):
    spec = {**GOOD_SPEC, field: ("zzz", "zzz")}
    out = run_checks(GOOD_NOTE, mk(GOOD_NOTE, **spec), KNOWN)
    assert out.failed_fields == (field,)
    assert status(out, field) == FieldStatus.FAILED
    assert out.review_state == ReviewState.NEEDS_REVIEW
    assert all(r.status == CheckStatus.CLAIMED_AND_FAILED for r in out.results if r.field == field)


def test_claimed_and_failed_is_distinct_from_missing():
    out = run_checks(GOOD_NOTE, mk(GOOD_NOTE, **{**GOOD_SPEC, "qty": None}), KNOWN)
    assert {r.status for r in out.results if r.field == "qty"} == {CheckStatus.MISSING}
    out = run_checks(GOOD_NOTE, mk(GOOD_NOTE, **{**GOOD_SPEC, "qty": ("1,200 kg", "9")}), KNOWN)
    assert CheckStatus.CLAIMED_AND_FAILED in {r.status for r in out.results if r.field == "qty"}
    # value without evidence and evidence without value are claims that failed, not absences
    out = run_checks(GOOD_NOTE, mk(GOOD_NOTE, **{**GOOD_SPEC, "colour": (None, "NAVY")}), KNOWN)
    assert status(out, "colour") == FieldStatus.FAILED
    out = run_checks(GOOD_NOTE, mk(GOOD_NOTE, **{**GOOD_SPEC, "colour": ("navy", None)}), KNOWN)
    assert status(out, "colour") == FieldStatus.FAILED


def test_all_null_signal_is_no_signal():
    out = run_checks("anything at all", mk("anything at all"), KNOWN)
    assert out.outcome == SignalOutcome.NO_SIGNAL
    assert out.review_state is None
    assert out.failed_fields == ()
    assert all(f.status == FieldStatus.MISSING for f in out.fields)
    assert out.checks_version == CHECKS_VERSION


def test_colour_only_signal_is_not_no_signal():
    out = run("navy cloth", colour="navy")
    assert out.outcome == SignalOutcome.NEEDS_REVIEW
    assert out.review_state == ReviewState.NEEDS_REVIEW
    assert set(out.failed_fields) == set(REQUIRED_FIELDS)


# ---------------------------------------------------------------- fix 1: qty boundaries


def test_qty_inside_a_longer_number_fails():
    note = "L-221 holes in 12000 kg"
    out = run(note, lot_id="L-221", issue=("holes", "defect"), qty=("1200", "1200"), unit="kg")
    assert status(out, "qty") == FieldStatus.FAILED
    assert ("qty_boundary", "qty_not_standalone") in fail_codes(out, "qty")
    ok = run(note, lot_id="L-221", issue=("holes", "defect"), qty=("12000 kg", "12000"), unit="kg")
    assert status(ok, "qty") == FieldStatus.PASSED


def test_qty_inside_a_lot_id_fails():
    note = "L-1234 holes, 50 kg"
    out = run(note, lot_id="L-1234", issue=("holes", "defect"), qty=("1234", "1234"), unit="kg")
    assert status(out, "qty") == FieldStatus.FAILED
    assert ("qty_boundary", "qty_inside_lot_id") in fail_codes(out, "qty")
    ok = run(note, lot_id="L-1234", issue=("holes", "defect"), qty=("50 kg", "50"), unit="kg")
    assert out.review_state == ReviewState.NEEDS_REVIEW
    assert ok.review_state == ReviewState.CHECKS_PASSED, ok.failed_fields


@pytest.mark.parametrize(
    "note,evidence",
    [
        ("holes 1200.5 kg", "1200"),  # followed by .5
        ("holes 1,200 kg", "1"),  # inside a grouped number
        ("holes 1,200 kg", "200"),
        ("holes x1200 kg", "1200"),  # preceded by a word char
        ("holes .5 kg", "5"),  # preceded by a decimal point
    ],
)
def test_qty_boundary_rejects_partial_numbers(note, evidence):
    out = run(note, qty=(evidence, evidence))
    assert status(out, "qty") == FieldStatus.FAILED


def test_qty_followed_by_sentence_punctuation_is_fine():
    for note in ("holes 50 kg.", "holes 50 kg, ok", "holes 50 kg"):
        out = run(note, lot_id=None, qty=("50 kg", "50"), unit="kg")
        assert status(out, "qty") == FieldStatus.PASSED, note


# ---------------------------------------------------------------- fix 2: multipliers


@pytest.mark.parametrize(
    "note,ev",
    [
        ("holes 1.2 lakh m", "1.2"),
        ("holes 5k m", "5"),
        ("holes 2 crore m", "2"),
        ("holes 3 lac m", "3"),
    ],
)
def test_multiplier_after_the_span_fails(note, ev):
    out = run(note, qty=(ev, ev), unit="m")
    assert status(out, "qty") == FieldStatus.FAILED
    assert ("value_reparses", "multiplier") in fail_codes(out, "qty")


def test_kg_is_not_mistaken_for_a_multiplier():
    out = run("holes 5 kg", qty=("5", "5"), unit="kg")
    assert ("value_reparses", "multiplier") not in fail_codes(out, "qty")


# ---------------------------------------------------------------- qty reparse table


@pytest.mark.parametrize(
    "sub,value,ok",
    [
        ("1,200 kg", "1200", True),
        ("1200", "1200", True),
        ("1200.5", "1200.5", True),
        ("12,34,567", "1234567", True),
        ("1,20,000", "120000", True),
        ("1,234,567", "1234567", True),
        ("1200kg", "1200", True),
        ("1200.0", "1200", True),
        ("1,200 kg", "1201", False),
        ("1.2k", "1200", False),
        ("1.2k", "1.2", False),
        ("2 lakh", "2", False),
        ("1,20", "120", False),
        ("12,3456", "123456", False),
        ("1.2.3", "1.2", False),
        ("1200 and 300", "1200", False),
        ("about", "1200", False),
        ("000", "0", False),
        ("0", "0", False),
    ],
)
def test_qty_reparse(sub, value, ok):
    note = f"stock {sub} here"
    out = run(note, qty=(sub, value))
    assert (status(out, "qty") == FieldStatus.PASSED) is ok, [
        r.detail for r in out.results if r.field == "qty" and not r.passed
    ]


# ---------------------------------------------------------------- fix 6: strict digits


def test_parse_qty_is_ascii_fullmatch_positive_and_canonical():
    assert parse_qty("1200") == Decimal("1200")
    assert parse_qty("1200\n") is None
    assert parse_qty("１２００") is None  # fullwidth
    assert parse_qty("௧௨௦௦") is None  # Tamil digits
    assert parse_qty("000") is None
    assert parse_qty("0") is None
    assert parse_qty("0.0") is None
    assert parse_qty("0.5") == Decimal("0.5")
    assert parse_qty(" 1200") is None


@pytest.mark.parametrize("bad", ["１２００", "௧௨௦௦"])
def test_non_ascii_digits_fail(bad):
    note = f"holes {bad} kg"
    out = run(note, qty=(bad, bad))
    assert status(out, "qty") == FieldStatus.FAILED


def test_trailing_newline_in_qty_value_or_evidence_fails():
    note = "holes 1200\nkg"
    assert status(run(note, qty=("1200", "1200\n")), "qty") == FieldStatus.FAILED
    assert status(run(note, qty=("1200\n", "1200")), "qty") == FieldStatus.FAILED
    assert status(run(note, qty=("1200\n", "1200\n")), "qty") == FieldStatus.FAILED


def test_qty_is_recorded_as_canonical_decimal_text():
    note = "holes 1200.0 kg"
    out = run(note, qty=("1200.0", "1200.0"))
    assert status(out, "qty") == FieldStatus.PASSED
    assert next(f for f in out.fields if f.field == "qty").value == "1200"
    out = run("holes 0.50 kg", qty=("0.50", "0.5"))
    assert next(f for f in out.fields if f.field == "qty").value == "0.5"


# ---------------------------------------------------------------- fix 3: token boundaries


def test_lot_id_prefix_of_a_longer_lot_fails():
    note = "L-1234 holes 50 kg"
    out = run(note, lot_id="L-12")
    assert status(out, "lot_id") == FieldStatus.FAILED
    assert ("token_boundary", "not_a_whole_token") in fail_codes(out, "lot_id")


def test_lot_id_inside_a_longer_token_fails():
    out = run("XL-221 holes 50 kg", lot_id="L-221")
    assert status(out, "lot_id") == FieldStatus.FAILED
    assert ("token_boundary", "not_a_whole_token") in fail_codes(out, "lot_id")


def test_lot_id_followed_by_punctuation_is_a_whole_token():
    out = run("lot L-221, holes 50 kg", lot_id="L-221")
    assert status(out, "lot_id") == FieldStatus.PASSED


def test_colour_inside_a_word_fails():
    out = run("colour required, holes 50 kg", colour="red")
    assert status(out, "colour") == FieldStatus.FAILED
    assert ("token_boundary", "not_a_whole_token") in fail_codes(out, "colour")
    assert status(run("colour red, holes 50 kg", colour="red"), "colour") == FieldStatus.PASSED


def test_fabric_quality_inside_a_hyphenated_token_fails():
    out = run("single-jersey rolls, holes 50 kg", fabric_quality="single")
    assert status(out, "fabric_quality") == FieldStatus.FAILED


def test_blank_values_fail():
    out = run("ab cd", colour=(" ", " "))
    assert ("value_reparses", "value_blank") in fail_codes(out, "colour")
    out = run("navy cloth", colour=("navy", "   "))
    assert status(out, "colour") == FieldStatus.FAILED
    assert ("value_reparses", "value_blank") in fail_codes(out, "colour")
    out = run("navy - cloth", colour=("-", "-"))
    assert ("value_reparses", "value_blank") in fail_codes(out, "colour")


def test_padded_evidence_fails():
    out = run("colour navy cloth", colour=("navy ", "navy"))
    assert status(out, "colour") == FieldStatus.FAILED


def test_text_fields_reparse_case_insensitively():
    note = "NAVY blue sj180 holes 50 kg"
    assert status(run(note, colour=("NAVY", "navy")), "colour") == FieldStatus.PASSED
    assert (
        status(run(note, fabric_quality=("sj180", "SJ180")), "fabric_quality") == FieldStatus.PASSED
    )
    assert status(run(note, colour=("NAVY", "black")), "colour") == FieldStatus.FAILED
    n2 = "lot l-77 ok"
    assert status(run(n2, lot_id=("l-77", "L-77")), "lot_id") == FieldStatus.PASSED


# ---------------------------------------------------------------- lot regex / entity / issue


@pytest.mark.parametrize(
    "lot,ok",
    [
        ("L-12", True),
        ("L-99999", True),
        ("L-1", False),
        ("L-123456", False),
        ("l-123", False),
        ("L123", False),
        ("L-12a", False),
        ("XL-123", False),
        ("L-123\n", False),
    ],
)
def test_lot_regex(lot, ok):
    note = f"lot {lot} holes"
    out = run(note, known={lot}, lot_id=(lot, lot))
    assert (check_code(out, "lot_id", "lot_regex") == "ok") is ok


def test_issue_enum_and_lexicon():
    n = "ஓட்டை இருக்கு L-77"
    assert status(run(n, issue=("ஓட்டை", "defect")), "issue") == FieldStatus.PASSED
    # right enum, evidence is not a gsm cue
    out = run(n, issue=("ஓட்டை", "gsm_fail"))
    assert ("issue_enum_and_lexicon", "no_cue_in_evidence") in fail_codes(out, "issue")
    out = run(n, issue=("ஓட்டை", "late"))
    assert ("issue_enum_and_lexicon", "not_in_enum") in fail_codes(out, "issue")
    nfd = unicodedata.normalize("NFD", "கொஞ்சம் ஓட்டை")
    assert status(run(nfd, issue=("ஓட்டை", "defect")), "issue") == FieldStatus.PASSED


def test_issue_cue_elsewhere_in_the_note_does_not_support_the_claim():
    note = "L-221 shade ok but 20 holes, 50 kg"
    out = run(note, lot_id="L-221", issue=("holes", "shade_fail"), qty=("50 kg", "50"), unit="kg")
    assert status(out, "issue") == FieldStatus.FAILED
    assert ("issue_enum_and_lexicon", "no_cue_in_evidence") in fail_codes(out, "issue")
    good = run(note, lot_id="L-221", issue=("holes", "defect"), qty=("50 kg", "50"), unit="kg")
    assert good.review_state == ReviewState.CHECKS_PASSED, good.failed_fields


def test_issue_evidence_overlapping_a_different_issue_cue_fails():
    note = "L-221 shade variation and holes, 50 kg"
    out = run(note, issue=("shade variation and holes", "shade_fail"))
    assert ("issue_enum_and_lexicon", "other_issue_cue") in fail_codes(out, "issue")
    ok = run(note, issue=("shade variation", "shade_fail"))
    assert status(ok, "issue") == FieldStatus.PASSED


def test_negated_issue_cue_does_not_support_the_claim():
    out = run("L-221 no holes, 50 kg", issue=("holes", "defect"))
    assert status(out, "issue") == FieldStatus.FAILED


# ---------------------------------------------------------------- unit adjacency


def test_unit_must_sit_next_to_the_qty():
    note = "holes 50 kg, ask M"
    out = run(note, qty=("50", "50"), unit=("M", "m"))
    assert status(out, "unit") == FieldStatus.FAILED
    assert ("unit_adjacent", "unit_not_adjacent") in fail_codes(out, "unit")
    ok = run(note, qty=("50", "50"), unit=("kg", "kg"))
    assert status(ok, "unit") == FieldStatus.PASSED


def test_unit_attached_to_the_number_is_adjacent():
    note = "holes 50kg"
    out = run(note, qty=("50kg", "50"), unit=("kg", "kg"))
    assert status(out, "qty") == FieldStatus.PASSED
    assert status(out, "unit") == FieldStatus.PASSED


def test_unit_evidence_may_include_the_number():
    out = run("holes 300 m", qty=("300", "300"), unit=("300 m", "m"))
    assert status(out, "unit") == FieldStatus.PASSED
    out = run("holes 300 m, 9 m", qty=("300", "300"), unit=("9 m", "m"))
    assert status(out, "unit") == FieldStatus.FAILED


def test_unit_without_a_qty_span_fails():
    out = run("holes 50 kg", unit=("kg", "kg"))
    assert ("unit_adjacent", "unit_not_adjacent") in fail_codes(out, "unit")


def test_unit_inside_a_longer_word_fails():
    out = run("holes 50 kgx", qty=("50", "50"), unit=("kg", "kg"))
    assert status(out, "unit") == FieldStatus.FAILED


@pytest.mark.parametrize(
    "sub,value,ok",
    [
        ("kg", "kg", True),
        ("KGS", "kg", True),
        ("kilo", "kg", True),
        ("கிலோ", "kg", True),
        ("m", "m", True),
        ("mtr", "m", True),
        ("Meters", "m", True),
        ("metre", "m", True),
        ("மீட்டர்", "m", True),
        ("kg", "m", False),
        ("mtr", "kg", False),
        ("roll", "kg", False),
        ("kg or m", "kg", False),
    ],
)
def test_unit_reparse(sub, value, ok):
    note = f"1200 {sub} total"
    out = run(note, qty=("1200", "1200"), unit=(sub, value))
    assert (status(out, "unit") == FieldStatus.PASSED) is ok, fail_codes(out, "unit")


# ---------------------------------------------------------------- fix 7: grapheme safety


def test_span_cutting_a_tamil_cluster_fails():
    note = "சிவப்பு holes 50 kg"
    out = run(note, colour=("சிவப", "சிவப"))
    assert status(out, "colour") == FieldStatus.FAILED
    assert ("grapheme_safe", "splits_grapheme") in fail_codes(out, "colour")
    out = run(note, colour=("்பு", "்பு"))
    assert ("grapheme_safe", "splits_grapheme") in fail_codes(out, "colour")
    assert status(run(note, colour=("சிவப்பு", "சிவப்பு")), "colour") == FieldStatus.PASSED


# ---------------------------------------------------------------- fix 8: multi-item notes


def test_two_lots_and_two_quantities_make_every_field_ambiguous():
    note = "L-221 holes 50 kg; L-1234 shade variation 300 kg"
    out = run(
        note,
        lot_id="L-221",
        issue=("holes", "defect"),
        qty=("50 kg", "50"),
        unit=("kg", "kg"),
        colour=None,
    )
    assert out.review_state == ReviewState.NEEDS_REVIEW
    for f in FIELDS:
        assert ("ambiguous_note", "ambiguous_note") in fail_codes(out, f), f
    assert set(out.failed_fields) == set(FIELDS)


def test_two_quantities_alone_are_ambiguous():
    out = run("L-221 holes 50 kg and 20 kg", lot_id="L-221")
    assert ("ambiguous_note", "ambiguous_note") in fail_codes(out, "lot_id")


def test_ambiguous_all_null_signal_is_not_no_signal():
    out = run_checks("L-221 holes 50 kg; L-1234 shade 300 kg", mk(""), ALL_LOTS)
    assert out.review_state == ReviewState.NEEDS_REVIEW
    assert out.outcome == SignalOutcome.NEEDS_REVIEW


def test_repeating_one_lot_or_a_gsm_figure_is_not_ambiguous():
    note = "L-221 holes 50 kg (rolls of 180 gsm), lot L-221"
    out = run(note, issue=("holes", "defect"), qty=("50 kg", "50"), unit=("kg", "kg"))
    assert ("ambiguous_note", "ambiguous_note") not in fail_codes(out, "issue")
    assert status(out, "issue") == FieldStatus.PASSED


# ---------------------------------------------------------------- providers


def test_provider_protocol_documents_nfc_contract():
    assert "normalize_note" in (GenerationProvider.__doc__ or "")


def test_mock_provider_is_deterministic_and_table_driven():
    note = "Lot L-77 gsm low"
    canned = good_raw()
    p = MockProvider({note_digest(note): canned})
    r1 = p.extract(note, prompt_version="p1", schema=note_signal_json_schema())
    r2 = p.extract(note, prompt_version="p1", schema=note_signal_json_schema())
    assert r1 == r2
    assert isinstance(r1, ProviderResult)
    assert r1.raw == canned
    assert r1.model == p.model and p.name == "mock"
    validate_signal_payload(r1.raw)
    # mutating the returned dict cannot poison the table
    r1.raw["language"] = "ta"
    assert p.extract(note, prompt_version="p1", schema={}).raw == canned


def test_mock_provider_digest_is_nfc_insensitive():
    nfc = "கொஞ்சம் ஓட்டை"
    p = MockProvider({note_digest(nfc): good_raw()})
    nfd = unicodedata.normalize("NFD", nfc)
    assert p.extract(nfd, prompt_version="p1", schema={}).raw == good_raw()


def test_mock_provider_token_counts_use_the_nfc_length():
    nfc = "கொஞ்சம் ஓட்டை " * 40
    nfd = unicodedata.normalize("NFD", nfc)
    assert len(nfd) // 4 != len(nfc) // 4
    p = MockProvider({})
    a = p.extract(nfc, prompt_version="p1", schema={})
    b = p.extract(nfd, prompt_version="p1", schema={})
    assert a.input_tokens == b.input_tokens == len(nfc) // 4


def test_mock_provider_unknown_note_returns_the_empty_signal():
    p = MockProvider({})
    r = p.extract("never seen", prompt_version="p1", schema={})
    assert r.raw == empty_signal_raw()
    sig = validate_signal_payload(r.raw)
    for f in FIELDS:
        assert getattr(sig, f) == empty_fv()
    out = run_checks("never seen", sig, KNOWN)
    assert out.outcome == SignalOutcome.NO_SIGNAL
    assert out.review_state is None


def test_providers_satisfy_protocol():
    providers: list[GenerationProvider] = [MockProvider({}), RaisingProvider()]
    assert all(isinstance(p.name, str) and isinstance(p.model, str) for p in providers)


def test_raising_provider_always_raises():
    p = RaisingProvider()
    with pytest.raises(ProviderCalledError):
        p.extract("x", prompt_version="p1", schema={})
    with pytest.raises(ProviderCalledError):
        p.extract("", prompt_version="p2", schema={"a": 1})


def test_mock_table_not_aliased():
    canned = good_raw()
    snapshot = copy.deepcopy(canned)
    p = MockProvider({note_digest("a"): canned})
    canned["language"] = "ta"
    assert p.extract("a", prompt_version="p", schema={}).raw == snapshot


# ---------------------------------------------------------------- hypothesis

_ALPHABET = st.sampled_from(list("ab c-L01.,kg") + list("ஓட்டைகொ கிலோ") + ["́", "é", "ß"])


def _overlapping_count(note: str, sub: str) -> int:
    n, i = 0, note.find(sub)
    while i != -1:
        n += 1
        i = note.find(sub, i + 1)
    return n


@st.composite
def note_and_sub(draw):
    raw = draw(st.text(alphabet=_ALPHABET, min_size=1, max_size=40))
    note = unicodedata.normalize("NFC", raw) or "a"
    i = draw(st.integers(0, len(note) - 1))
    j = draw(st.integers(i + 1, len(note)))
    return note, note[i:j]


@given(note_and_sub())
def test_property_locate_agrees_with_occurrence_count(case):
    note, sub = case
    loc = locate_evidence(note, sub)
    count = _overlapping_count(note, sub)
    if count == 1:
        assert loc.code == "ok" and loc.span is not None
        assert note[loc.span.start : loc.span.end] == sub == loc.span.text
    elif count > 1:
        assert loc.code == "ambiguous_span" and loc.span is None
    else:  # pragma: no cover - sub is a substring of note by construction
        assert loc.code == "span_not_found"


@given(note_and_sub())
def test_property_nfd_input_locates_the_same_span_as_nfc(case):
    note, sub = case
    nfd = unicodedata.normalize("NFD", note)
    assert locate_evidence(nfd, sub) == locate_evidence(note, sub)


@given(note_and_sub())
def test_property_absent_evidence_is_never_located(case):
    note, sub = case
    loc = locate_evidence(note, sub + "☃")
    assert loc.code == "span_not_found" and loc.span is None
