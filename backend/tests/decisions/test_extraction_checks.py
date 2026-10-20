"""Extraction core: schema, lexicon, deterministic checks and provider doubles."""

from __future__ import annotations

import copy
import unicodedata
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from flooreplay.decisions.extraction.checks import (
    CHECKS_VERSION,
    LOT_ID_PATTERN,
    check_entity_exists,
    check_issue_enum_and_lexicon,
    check_lot_regex,
    check_span_exact,
    check_value_reparses,
    run_checks,
)
from flooreplay.decisions.extraction.lexicon import LEXICON_VERSION, lexicon_hits
from flooreplay.decisions.extraction.provider import (
    GenerationProvider,
    MockProvider,
    ProviderCalledError,
    ProviderResult,
    RaisingProvider,
)
from flooreplay.decisions.extraction.schema import (
    SCHEMA_VERSION,
    FieldValue,
    NoteSignal,
    SignalValidationError,
    Span,
    normalize_note,
    note_digest,
    note_signal_json_schema,
    validate_signal_payload,
)
from flooreplay.decisions.types import ReviewState

KNOWN = {"L-1042", "L-77"}
FIELDS = ("lot_id", "issue", "qty", "unit", "colour", "fabric_quality")


def span_of(note: str, sub: str) -> Span:
    n = normalize_note(note)
    i = n.index(sub)
    return Span(start=i, end=i + len(sub), text=sub)


def fv(note: str, sub: str, value: str | None = None) -> FieldValue:
    return FieldValue(value=sub if value is None else value, span=span_of(note, sub))


def empty_fv() -> FieldValue:
    return FieldValue(value=None, span=None)


GOOD_NOTE = "Lot L-1042 navy single jersey: shade variation, 1,200 kg held."


def good_signal() -> NoteSignal:
    return NoteSignal(
        language="en",
        lot_id=fv(GOOD_NOTE, "L-1042"),
        issue=fv(GOOD_NOTE, "shade variation", "shade_fail"),
        qty=fv(GOOD_NOTE, "1,200 kg", "1200"),
        unit=fv(GOOD_NOTE, "kg"),
        colour=fv(GOOD_NOTE, "navy", "NAVY"),
        fabric_quality=fv(GOOD_NOTE, "single jersey", "Single Jersey"),
    )


def good_raw() -> dict[str, Any]:
    return good_signal().model_dump(mode="json")


def result(outcome, field, check):
    return next(r for r in outcome.results if r.field == field and r.check == check)


# ---------------------------------------------------------------- versions


def test_version_constants():
    assert SCHEMA_VERSION == "note-signal-v1"
    assert LEXICON_VERSION == "lexicon-v1"
    assert CHECKS_VERSION == "checks-v1"
    assert LOT_ID_PATTERN == r"^L-\d{2,5}$"


# ---------------------------------------------------------------- schema


def test_validate_roundtrip_accepts_digits():
    # Regression against the v1 `_numeric_prose` trap: digits in values are the point here.
    raw = good_raw()
    assert raw["qty"]["value"] == "1200"
    sig = validate_signal_payload(raw)
    assert sig.qty.value == "1200"
    assert sig.lot_id.value == "L-1042"
    assert sig.model_dump(mode="json") == raw


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
    raw = good_raw()
    raw["qty"]["span"]["note"] = "x"
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


def test_json_schema_shape():
    schema = note_signal_json_schema()
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    props = schema["properties"]
    assert set(props) == {*FIELDS, "language"}
    assert set(schema["required"]) == set(props)
    assert "$ref" not in str(schema)
    issue_value = props["issue"]["properties"]["value"]
    assert set(issue_value["enum"]) == {"shade_fail", "gsm_fail", "defect", None}
    assert set(props["language"]["enum"]) == {"en", "ta", "tanglish", "mixed"}
    assert set(props["unit"]["properties"]["value"]["enum"]) == {"kg", "m", None}
    # a fresh copy each call
    schema["properties"].clear()
    assert note_signal_json_schema()["properties"]


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


# ---------------------------------------------------------------- span_exact


def test_span_exact_pass_and_fail():
    ok = check_span_exact("lot_id", GOOD_NOTE, fv(GOOD_NOTE, "L-1042"))
    assert ok.passed and ok.check == "span_exact" and ok.field == "lot_id"
    s = span_of(GOOD_NOTE, "L-1042")
    wrong_text = FieldValue(value="L-1042", span=Span(start=s.start, end=s.end, text="L-1043"))
    assert not check_span_exact("lot_id", GOOD_NOTE, wrong_text).passed
    shifted = FieldValue(value="L-1042", span=Span(start=s.start + 1, end=s.end + 1, text="L-1042"))
    assert not check_span_exact("lot_id", GOOD_NOTE, shifted).passed


def test_span_exact_rejects_empty_text_missing_span_and_out_of_range():
    empty = FieldValue(value="x", span=Span(start=3, end=3, text=""))
    assert not check_span_exact("colour", GOOD_NOTE, empty).passed
    assert not check_span_exact("colour", GOOD_NOTE, FieldValue(value="x", span=None)).passed
    n = len(GOOD_NOTE)
    beyond = FieldValue(value="x", span=Span(start=n, end=n + 2, text="x."))
    assert not check_span_exact("colour", GOOD_NOTE, beyond).passed


def test_span_offsets_are_code_points_in_nfc_text_tamil_combining_marks():
    nfd_note = unicodedata.normalize("NFD", "லாட் L-77 கொஞ்சம் ஓட்டை உள்ளது")
    nfc_note = normalize_note(nfd_note)
    assert nfc_note != nfd_note
    i = nfc_note.index("ஓட்டை")
    # "ஓட்டை" is ஓ ட ் ட ை = 5 code points (the virama is a combining mark)
    assert len("ஓட்டை") == 5
    good = FieldValue(value="defect", span=Span(start=i, end=i + 5, text="ஓட்டை"))
    # raw NFD note is passed in; the check must NFC it first, offsets refer to NFC text
    assert check_span_exact("issue", nfd_note, good).passed
    j = nfd_note.index("ஓட்டை")
    assert j != i  # offsets into the un-normalised text would be wrong
    bad = FieldValue(value="defect", span=Span(start=j, end=j + 5, text="ஓட்டை"))
    assert not check_span_exact("issue", nfd_note, bad).passed


# ---------------------------------------------------------------- value_reparses


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
        ("1,200 kg", "1201", False),
        ("1.2k", "1200", False),
        ("1.2k", "1.2", False),
        ("2 lakh", "2", False),
        ("1,20", "120", False),
        ("12,3456", "123456", False),
        ("1.2.3", "1.2", False),
        ("1200 and 300", "1200", False),
        ("about", "1200", False),
    ],
)
def test_qty_reparse(sub, value, ok):
    note = f"stock {sub} here"
    r = check_value_reparses("qty", note, fv(note, sub, value))
    assert r.passed is ok, r.detail


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
    r = check_value_reparses("unit", note, fv(note, sub, value))
    assert r.passed is ok, r.detail


def test_text_fields_reparse_case_insensitively():
    note = "NAVY blue sj180"
    assert check_value_reparses("colour", note, fv(note, "NAVY", "navy")).passed
    assert check_value_reparses("fabric_quality", note, fv(note, "sj180", "SJ180")).passed
    assert not check_value_reparses("colour", note, fv(note, "NAVY", "black")).passed
    n2 = "lot l-77 ok"
    assert check_value_reparses("lot_id", n2, fv(n2, "l-77", "L-77")).passed


def test_reparse_fails_for_missing_value_or_span():
    assert not check_value_reparses("colour", "x", empty_fv()).passed
    assert not check_value_reparses("colour", "x", FieldValue(value="x", span=None)).passed


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
    assert check_lot_regex("lot_id", FieldValue(value=lot, span=None)).passed is ok


def test_lot_regex_missing_value_fails():
    assert check_lot_regex("lot_id", empty_fv()).passed is False


def test_entity_exists():
    assert check_entity_exists("lot_id", FieldValue(value="L-77", span=None), KNOWN).passed
    assert not check_entity_exists("lot_id", FieldValue(value="L-78", span=None), KNOWN).passed
    assert not check_entity_exists("lot_id", empty_fv(), KNOWN).passed
    assert not check_entity_exists("lot_id", FieldValue(value="L-77", span=None), set()).passed


def test_issue_enum_and_lexicon():
    n = "ஓட்டை இருக்கு L-77"
    assert check_issue_enum_and_lexicon("issue", n, FieldValue(value="defect", span=None)).passed
    # right enum, no cue in the note
    gsm = FieldValue(value="gsm_fail", span=None)
    assert not check_issue_enum_and_lexicon("issue", n, gsm).passed
    # value outside the enum
    assert not check_issue_enum_and_lexicon("issue", n, FieldValue(value="late", span=None)).passed
    assert not check_issue_enum_and_lexicon("issue", n, empty_fv()).passed
    # NFD notes still hit
    nfd = unicodedata.normalize("NFD", "கொஞ்சம் ஓட்டை")
    assert check_issue_enum_and_lexicon("issue", nfd, FieldValue(value="defect", span=None)).passed


# ---------------------------------------------------------------- run_checks


def test_run_checks_all_pass():
    out = run_checks(GOOD_NOTE, good_signal(), KNOWN)
    assert out.checks_version == CHECKS_VERSION
    assert out.failed_fields == ()
    assert out.review_state == ReviewState.CHECKS_PASSED
    assert all(r.passed for r in out.results)
    names = {(r.field, r.check) for r in out.results}
    assert ("lot_id", "lot_regex") in names
    assert ("lot_id", "entity_exists") in names
    assert ("issue", "issue_enum_and_lexicon") in names
    assert ("qty", "value_reparses") in names
    for f in FIELDS:
        assert result(out, f, "span_exact").passed


def test_run_checks_unknown_lot_needs_review():
    out = run_checks(GOOD_NOTE, good_signal(), {"L-9999"})
    assert out.review_state == ReviewState.NEEDS_REVIEW
    assert out.failed_fields == ("lot_id",)
    assert not result(out, "lot_id", "entity_exists").passed


def test_run_checks_missing_field_fails_with_all_its_checks():
    sig = good_signal().model_copy(update={"colour": empty_fv()})
    out = run_checks(GOOD_NOTE, sig, KNOWN)
    assert out.failed_fields == ("colour",)
    assert out.review_state == ReviewState.NEEDS_REVIEW
    colour = [r for r in out.results if r.field == "colour"]
    assert colour and not any(r.passed for r in colour)


def test_run_checks_lying_value_is_isolated_to_its_field():
    bad_qty = good_signal().model_copy(update={"qty": fv(GOOD_NOTE, "1,200 kg", "2400")})
    out = run_checks(GOOD_NOTE, bad_qty, KNOWN)
    assert out.failed_fields == ("qty",)
    assert not result(out, "qty", "value_reparses").passed
    assert result(out, "qty", "span_exact").passed


def test_run_checks_all_fields_empty():
    empty = NoteSignal(language="en", **{k: empty_fv() for k in FIELDS})
    out = run_checks("anything", empty, KNOWN)
    assert out.failed_fields == FIELDS
    assert out.review_state == ReviewState.NEEDS_REVIEW


def test_run_checks_tamil_note_end_to_end_with_nfd_input():
    nfc = "லாட் L-77 ல் ஓட்டை, 300 m கொஞ்சம் NAVY SJ180"
    note = unicodedata.normalize("NFD", nfc)
    sig = NoteSignal(
        language="mixed",
        lot_id=fv(nfc, "L-77"),
        issue=fv(nfc, "ஓட்டை", "defect"),
        qty=fv(nfc, "300"),
        unit=fv(nfc, "m"),
        colour=fv(nfc, "NAVY"),
        fabric_quality=fv(nfc, "SJ180"),
    )
    out = run_checks(note, sig, KNOWN)
    assert out.failed_fields == (), [r for r in out.results if not r.passed]
    assert out.review_state == ReviewState.CHECKS_PASSED


def test_run_checks_is_deterministic():
    a = run_checks(GOOD_NOTE, good_signal(), KNOWN)
    b = run_checks(GOOD_NOTE, good_signal(), KNOWN)
    assert a == b


# ---------------------------------------------------------------- providers


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


def test_mock_provider_unknown_note_returns_empty_signal():
    p = MockProvider({})
    r = p.extract("never seen", prompt_version="p1", schema={})
    sig = validate_signal_payload(r.raw)
    for f in FIELDS:
        assert getattr(sig, f) == empty_fv()
    out = run_checks("never seen", sig, KNOWN)
    assert out.review_state == ReviewState.NEEDS_REVIEW


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
def test_property_index_span_always_passes(case):
    note, sub = case
    i = note.index(sub)
    f = FieldValue(value=sub, span=Span(start=i, end=i + len(sub), text=sub))
    assert check_span_exact("colour", note, f).passed


@given(note_and_sub(), st.sampled_from([-1, 1]))
def test_property_off_by_one_shift_of_unique_span_fails(case, delta):
    note, sub = case
    if _overlapping_count(note, sub) != 1:
        return
    i = note.index(sub)
    start, end = i + delta, i + len(sub) + delta
    if start < 0:
        return  # not constructible: Span rejects negative offsets
    shifted = FieldValue(value=sub, span=Span(start=start, end=end, text=sub))
    assert not check_span_exact("colour", note, shifted).passed
    # moving only one edge changes the length and must fail too
    one_edge = FieldValue(value=sub, span=Span(start=i, end=i + len(sub) + 1, text=sub))
    assert not check_span_exact("colour", note, one_edge).passed


@given(note_and_sub())
def test_property_nfd_input_gives_same_verdict_as_nfc(case):
    note, sub = case
    i = note.index(sub)
    f = FieldValue(value=sub, span=Span(start=i, end=i + len(sub), text=sub))
    assert check_span_exact("colour", unicodedata.normalize("NFD", note), f).passed
