from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from flooreplay.decisions.facts import validate_fact
from flooreplay.decisions.imports import preview_import

SAMPLES = Path(__file__).parents[2] / "src/flooreplay/decisions/samples"
AS_OF = datetime(2026, 10, 20, 9, tzinfo=ZoneInfo("Asia/Kolkata"))
CASES = [
    ("erp-fabric-stock.csv", "erp-fabric-stock", {"lot_id": "lot_id", "qty": "qty", "unit": "unit", "fabric_quality": "quality", "colour": "colour", "allocation_order_id": "allocation_order_id", "allocation_qty": "allocation_qty"}),
    ("sheet-trims-status.csv", "sheet-trims-status", {"style_id": "style_id", "trim_id": "trim_id", "on_hand": "on_hand", "unit": "unit", "supplier": "supplier", "eta": "eta", "inbound_qty": "inbound_qty"}),
    ("shift-capacity.csv", "shift-capacity", {"line_id": "line_id", "date": "date", "available_minutes": "available_minutes", "unit": "unit", "efficiency_pct": "efficiency_pct", "commitment_order_id": "commitment_order_id", "committed_minutes": "committed_minutes"}),
    ("supplier-updates.csv", "supplier-updates", {"ref": "ref", "qty": "qty", "unit": "unit", "fabric_quality": "quality", "colour": "colour", "eta": "eta", "supplier": "supplier", "qc_issue": "qc_issue", "qc_qty": "qc_qty", "lot_id": "lot_id"}),
    ("order-requests.csv", "order-requests", {"order_id": "order_id", "buyer": "buyer", "style_id": "style_id", "colours": "colours", "ship_date": "ship_date", "order_value_inr": "order_value_inr", "partial_shipment_allowed": "partial_shipment_allowed", "fabric_quality": "fabric_quality", "consumption_per_pc": "consumption_per_pc", "consumption_unit": "consumption_unit", "sam_minutes": "sam_minutes", "trims": "trims"}),
    ("notes.csv", "notes", {"note_id": "note_id", "lot_hint": "lot_hint", "text": "text"}),
]


def test_every_sample_csv_has_a_ready_profile_case():
    assert {path.name for path in SAMPLES.glob("*.csv")} == {filename for filename, _, _ in CASES}


@pytest.mark.parametrize(("filename", "profile", "mapping"), CASES)
def test_each_synthetic_sample_previews_ready_and_emits_valid_facts(filename, profile, mapping):
    raw = (SAMPLES / filename).read_bytes()
    result = preview_import(
        raw, filename=filename, profile=profile, column_mapping=mapping, as_of=AS_OF,
        coverage_qualities=["SJ180", "SJ200"] if profile == "erp-fabric-stock" else None,
    )
    assert result.status == "READY", result.problems
    assert all(validate_fact(fact) == fact for fact in result.facts)
    if profile == "notes":
        assert len(result.notes) >= 3


def test_erp_sample_emits_fabric_allocations_and_supplier_qc_sample_emits_qc_facts():
    erp = preview_import(
        (SAMPLES / "erp-fabric-stock.csv").read_bytes(), filename="erp-fabric-stock.csv",
        profile="erp-fabric-stock", column_mapping=CASES[0][2], as_of=AS_OF,
        coverage_qualities=["SJ180", "SJ200"],
    )
    supplier = preview_import(
        (SAMPLES / "supplier-updates.csv").read_bytes(), filename="supplier-updates.csv",
        profile="supplier-updates", column_mapping=CASES[3][2], as_of=AS_OF,
    )
    assert {fact.kind.value for fact in erp.facts} == {"fabric_lot", "fabric_allocation"}
    qc = next(fact for fact in supplier.facts if fact.kind.value == "fabric_qc")
    assert qc.payload["origin"] == "supplier_updates"
    assert qc.payload["review_state"] == "checks_passed"


def test_supplier_qc_unit_column_is_used_instead_of_the_inbound_unit():
    raw = (
        b"ref,qty,unit,quality,colour,eta,supplier,qc_issue,qc_qty,qc_unit,lot_id\n"
        b"SUP-221,900,m,SJ180,NAVY,2026-10-25,Supplier A (synthetic),shade_fail,120,kg,L-221\n"
    )
    result = preview_import(
        raw, filename="supplier.csv", profile="supplier-updates",
        column_mapping={**CASES[3][2], "qc_unit": "qc_unit"}, as_of=AS_OF,
    )
    assert result.status == "READY", result.problems
    inbound = next(fact for fact in result.facts if fact.kind.value == "fabric_inbound")
    qc = next(fact for fact in result.facts if fact.kind.value == "fabric_qc")
    assert inbound.payload["qty"] == {"value": "900", "unit": "m"}
    assert qc.payload["qty"] == {"value": "120", "unit": "kg"}


@pytest.mark.parametrize("colour_json", ["null", "123", "1.5", '{"name":"NAVY"}', "true", '["NAVY"]'])
def test_order_colour_must_be_text_instead_of_coercing_other_json_values(colour_json):
    import csv
    import io

    source = csv.DictReader(io.StringIO((SAMPLES / "order-requests.csv").read_text()))
    row = next(source)
    row["colours"] = '[{"colour":' + colour_json + ',"qty_pcs":8}]'
    csv_text = io.StringIO(newline="")
    writer = csv.DictWriter(csv_text, fieldnames=list(row))
    writer.writeheader()
    writer.writerow(row)
    result = preview_import(
        csv_text.getvalue().encode(), filename="order.csv", profile="order-requests",
        column_mapping=CASES[4][2], as_of=AS_OF,
    )
    assert result.status == "BLOCKED"
    assert result.facts == ()
    assert any(problem.row == 2 and problem.field == "colours" for problem in result.problems)
