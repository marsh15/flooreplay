from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from flooreplay.decisions.imports import PROFILES, preview_import
from flooreplay.decisions.types import FactKind, SourceProfile

AS_OF = datetime(2026, 10, 20, 9, tzinfo=ZoneInfo("Asia/Kolkata"))
FABRIC_CSV = (
    "lot,quantity,unit,quality,colour\n"
    "L-221,1200,m,SJ180,NAVY\n"
)
FABRIC_MAPPING = {
    "lot_id": "lot",
    "qty": "quantity",
    "unit": "unit",
    "fabric_quality": "quality",
    "colour": "colour",
}


def preview(raw: bytes = FABRIC_CSV.encode(), **overrides):
    arguments = {
        "filename": "stock.csv",
        "profile": "erp-fabric-stock",
        "column_mapping": FABRIC_MAPPING,
        "as_of": AS_OF,
        "coverage_qualities": ["SJ180"],
    }
    arguments.update(overrides)
    return preview_import(raw, **arguments)


def test_profiles_map_every_supported_name_to_domain_source():
    assert PROFILES == {
        "erp-fabric-stock": SourceProfile.ERP_FABRIC_STOCK,
        "sheet-trims-status": SourceProfile.SHEET_TRIMS_STATUS,
        "shift-capacity": SourceProfile.SHIFT_CAPACITY,
        "supplier-updates": SourceProfile.SUPPLIER_UPDATES,
        "order-requests": SourceProfile.ORDER_REQUESTS,
        "notes": SourceProfile.NOTES,
    }


def test_mapping_is_canonical_field_to_exact_csv_header_and_builds_real_fact():
    result = preview()
    assert result.status == "READY"
    fact, = result.facts
    assert fact.kind is FactKind.FABRIC_LOT
    assert fact.entity_key == "lot:L-221"
    assert fact.payload["qty"] == {"value": "1200", "unit": "m"}
    assert fact.valid_from == AS_OF and fact.known_at == AS_OF
    assert result.coverage is not None
    assert result.coverage.profile is SourceProfile.ERP_FABRIC_STOCK


@pytest.mark.parametrize(
    ("override", "expected_code"),
    [
        ({"column_mapping": {}}, "mapping_required"),
        ({"as_of": datetime(2026, 10, 20, 9)}, "as_of_timezone_required"),
        ({"column_mapping": {key: value for key, value in FABRIC_MAPPING.items() if key != "unit"}}, "unit_required"),
    ],
)
def test_mapping_clock_and_units_must_be_explicit(override, expected_code):
    result = preview(**override)
    assert result.status == "BLOCKED"
    assert expected_code in {problem.code for problem in result.problems}


@pytest.mark.parametrize(
    ("cell", "expected_code"),
    [("#N/A", "missing_value"), ("N/A", "missing_value"), ("-", "missing_value"), ("", "missing_value"), ('"1,200"', "thousands_separator")],
)
def test_unusable_or_ambiguous_quantity_cells_block(cell, expected_code):
    raw = f"lot,quantity,unit,quality,colour\nL-221,{cell},m,SJ180,NAVY\n".encode()
    result = preview(raw)
    assert result.status == "BLOCKED"
    assert expected_code in {problem.code for problem in result.problems}
    assert not result.facts


@pytest.mark.parametrize("date_text", ["03/04/2026", "2026-02-30"])
def test_ambiguous_or_impossible_dates_block(date_text):
    raw = f"style,trim,on_hand,unit,supplier,eta\nPOLO-221,button,200,pcs,Local,{date_text}\n".encode()
    result = preview_import(
        raw,
        filename="trims.csv",
        profile="sheet-trims-status",
        column_mapping={
            "style_id": "style", "trim_id": "trim", "on_hand": "on_hand",
            "unit": "unit", "supplier": "supplier", "eta": "eta",
        },
        as_of=AS_OF,
    )
    assert result.status == "BLOCKED"
    assert "invalid_date" in {problem.code for problem in result.problems}


def test_iso_and_day_month_name_dates_are_accepted():
    csv_text = "style,trim,on_hand,unit,supplier,eta\nPOLO-221,button,200,pcs,Local,03-Apr-2026\n"
    result = preview_import(
        csv_text.encode(), filename="trims.csv", profile="sheet-trims-status",
        column_mapping={"style_id": "style", "trim_id": "trim", "on_hand": "on_hand", "unit": "unit", "supplier": "supplier", "eta": "eta"},
        as_of=AS_OF,
    )
    assert result.status == "READY"
    assert result.facts[0].payload["eta"] == "2026-04-03"


def test_utf8_bom_is_accepted_and_tamil_notes_are_nfc_normalized():
    note = "L-221 துணி பிரச்சனை இல்லை"
    raw = ("\ufefflot,note\n," + note + "\n").encode("utf-8")
    result = preview_import(
        raw, filename="notes.csv", profile="notes",
        column_mapping={"lot_hint": "lot", "text": "note"}, as_of=AS_OF,
    )
    assert result.status == "READY"
    assert result.facts == ()
    assert result.notes[0].text == note
    assert result.notes[0].note_digest


def test_preview_ids_and_digest_are_deterministic_and_digest_ignores_known_at():
    first = preview()
    same = preview()
    assert [fact.id for fact in first.facts] == [fact.id for fact in same.facts]
    assert first.preview_digest == same.preview_digest
    assert first.facts[0].id.startswith("erp-fabric-stock:")


def test_file_and_row_caps_block_the_import():
    from flooreplay.decisions.imports import MAX_BYTES, MAX_ROWS

    oversized = preview(b"x" * (MAX_BYTES + 1))
    assert oversized.status == "BLOCKED"
    assert "file_too_large" in {problem.code for problem in oversized.problems}

    raw = "lot,quantity,unit,quality,colour\n" + "L-221,1,m,SJ180,NAVY\n" * (MAX_ROWS + 1)
    too_many = preview(raw.encode())
    assert too_many.status == "BLOCKED"
    assert "too_many_rows" in {problem.code for problem in too_many.problems}


def test_naive_as_of_returns_a_blocked_preview_instead_of_failing_digesting():
    result = preview(as_of=datetime(2026, 10, 20, 9))
    assert result.status == "BLOCKED"
    assert "as_of_timezone_required" in {problem.code for problem in result.problems}


def test_nonempty_missing_sentinel_in_optional_field_blocks_import():
    raw = b"lot,quantity,unit,quality,colour,gsm\nL-221,1200,m,SJ180,NAVY,N/A\n"
    result = preview(raw, column_mapping={**FABRIC_MAPPING, "gsm": "gsm"})
    assert result.status == "BLOCKED"
    assert "missing_value" in {problem.code for problem in result.problems}


def test_order_json_decimal_values_are_parsed_without_float_coercion():
    raw = (
        b'order,buyer,style,colours,ship,value,partial,quality,consumption,consumption_unit,sam,trims\n'
        b'PO-1,Buyer,POLO-221,"[{""colour"":""NAVY"",""qty_pcs"":8}]",2026-11-30,1000,true,SJ180,0.72,m,18,"[{""trim_id"":""BUTTON"",""qty_per_pc"":0.25}]"\n'
    )
    result = preview_import(
        raw, filename="order.csv", profile="order-requests",
        column_mapping={
            "order_id": "order", "buyer": "buyer", "style_id": "style", "colours": "colours",
            "ship_date": "ship", "order_value_inr": "value", "partial_shipment_allowed": "partial",
            "fabric_quality": "quality", "consumption_per_pc": "consumption",
            "consumption_unit": "consumption_unit", "sam_minutes": "sam", "trims": "trims",
        }, as_of=AS_OF,
    )
    assert result.status == "READY", result.problems
    bom = next(fact for fact in result.facts if fact.kind is FactKind.BOM)
    assert bom.payload["trims"][0]["qty_per_pc"] == "0.25"


def test_order_json_fields_must_be_arrays_of_objects():
    raw = (
        b'order,buyer,style,colours,ship,value,partial,quality,consumption,consumption_unit,sam,trims\n'
        b'PO-1,Buyer,POLO-221,"{""colour"":""NAVY""}",2026-11-30,1000,true,SJ180,0.72,m,18,[]\n'
    )
    result = preview_import(
        raw, filename="order.csv", profile="order-requests",
        column_mapping={
            "order_id": "order", "buyer": "buyer", "style_id": "style", "colours": "colours",
            "ship_date": "ship", "order_value_inr": "value", "partial_shipment_allowed": "partial",
            "fabric_quality": "quality", "consumption_per_pc": "consumption",
            "consumption_unit": "consumption_unit", "sam_minutes": "sam", "trims": "trims",
        }, as_of=AS_OF,
    )
    assert result.status == "BLOCKED"
    assert "invalid_array" in {problem.code for problem in result.problems}


@pytest.mark.parametrize(
    ("raw", "expected_code"),
    [
        (b"", "empty_file"),
        (b"\xff", "invalid_encoding"),
        (b"\nL-221,1200,m,SJ180,NAVY\n", "invalid_headers"),
        (b"lot,quantity,unit,quality,colour\nL-221,1200,m,SJ180\n", "invalid_row_width"),
    ],
)
def test_invalid_csv_envelopes_block_without_facts(raw, expected_code):
    result = preview(raw)
    assert result.status == "BLOCKED"
    assert expected_code in {problem.code for problem in result.problems}
    assert result.facts == ()


@pytest.mark.parametrize("number", ["NaN", "Infinity", "-2", "1e3", "1234567890123456789012345678901"])
def test_nonfinite_negative_exponent_and_oversized_quantities_block(number):
    raw = f"lot,quantity,unit,quality,colour\nL-221,{number},m,SJ180,NAVY\n".encode()
    result = preview(raw)
    assert result.status == "BLOCKED"
    assert not result.facts


def test_unknown_mappings_and_preview_digest_inputs_are_explicit():
    unknown = preview(column_mapping={**FABRIC_MAPPING, "lot": "lot"})
    assert "unknown_mapping_field" in {problem.code for problem in unknown.problems}

    base = preview()
    changed_mapping = preview(column_mapping={**FABRIC_MAPPING, "gsm": "not_a_header"})
    changed_as_of = preview(as_of=datetime(2026, 10, 21, 9, tzinfo=ZoneInfo("Asia/Kolkata")))
    changed_unit = preview(units={"qty": "kg"})
    changed_coverage = preview(coverage_qualities=["SJ180", "SJ200"])
    assert len({base.preview_digest, changed_mapping.preview_digest, changed_as_of.preview_digest,
                changed_unit.preview_digest, changed_coverage.preview_digest}) == 5


def test_mapped_unit_column_takes_precedence_over_import_unit_defaults():
    result = preview(units={"qty": "kg"})
    assert result.status == "READY", result.problems
    assert result.facts[0].payload["qty"] == {"value": "1200", "unit": "m"}
