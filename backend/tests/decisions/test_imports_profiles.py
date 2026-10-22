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
