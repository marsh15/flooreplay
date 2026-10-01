from __future__ import annotations

import json

import pytest

from flooreplay.incident_import import preview_incident_import, publish_incident_import

META = {"profile": "production-v1", "source_system": "output-ledger", "timezone": "Asia/Kolkata", "filename": "output.csv"}
SCOPE = "Synthetic A,S4,ORD-1,ST-42,sewing"
HEADERS = "id,record_type,available_at,start,end,quantity,unit,factory,line_id,order_id,style_id,stage\n"


def _production(quantity: str = "12") -> bytes:
    return (HEADERS + f"p1,final_good_delta,2026-09-28T09:15:00,2026-09-28T09:00:00,2026-09-28T09:15:00,{quantity},good_units,{SCOPE}\n").encode()


def test_csv_preview_normalizes_and_publishes_whole_file():
    preview = preview_incident_import(_production(), **META)
    assert preview["status"] == "READY"
    assert preview["row_count"] == 1
    published = publish_incident_import(preview)
    row = published["output_buckets"][0]
    assert row["quantity"] == 12
    assert row["start"] == "2026-09-28T09:00:00+05:30"
    assert row["source_id"] == "output-ledger:p1"


def test_invalid_row_blocks_entire_file_with_row_issue():
    raw = _production() + f"p2,final_good_delta,2026-09-28T09:30:00,2026-09-28T09:15:00,2026-09-28T09:30:00,,good_units,{SCOPE}\n".encode()
    preview = preview_incident_import(raw, **META)
    assert preview["status"] == "BLOCKED"
    assert preview["issues"][0]["row"] == 2
    with pytest.raises(ValueError, match="All rows"):
        publish_incident_import(preview)


def test_json_notes_preserve_late_availability_and_attribution():
    note = {"id": "n1", "record_type": "maintenance_note", "line_id": "S4", "author_role": "Technician", "summary": "Feed issue observed earlier", "occurred_at": "2026-09-28T10:14:00+05:30", "available_at": "2026-09-28T11:20:00+05:30"}
    preview = preview_incident_import(json.dumps({"records": [note]}).encode(), profile="notes-v1", source_system="maintenance", timezone="Asia/Kolkata", filename="notes.json")
    assert preview["status"] == "READY"
    event = preview["events"][0]
    assert event["assertion"] is True
    assert event["available_at"] > event["occurred_at"]


def test_explicit_line_block_only():
    event = {"id": "m1", "record_type": "machine_interruption", "line_id": "S4", "summary": "Machine stopped", "start": "2026-09-28T10:00:00+05:30", "end": "2026-09-28T10:15:00+05:30", "available_at": "2026-09-28T10:20:00+05:30", "line_blocking": True}
    preview = preview_incident_import(json.dumps([event]).encode(), profile="operations-v1", source_system="machine", timezone="Asia/Kolkata", filename="events.json")
    assert preview["status"] == "BLOCKED"
    assert "explicit line_block" in preview["issues"][0]["message"]


def test_cumulative_counts_and_remote_url_rejected():
    raw = _production().replace(b"final_good_delta", b"cumulative_output")
    assert preview_incident_import(raw, **META)["status"] == "BLOCKED"
    with pytest.raises(ValueError, match="Remote"):
        preview_incident_import(_production(), **{**META, "filename": "https://example.com/output.csv"})


def test_duplicate_ids_are_blocking():
    raw = _production() + _production().split(b"\n", 1)[1]
    preview = preview_incident_import(raw, **META)
    assert preview["status"] == "BLOCKED"
    assert "Duplicate" in preview["issues"][0]["message"]


def test_misaligned_bucket_is_blocking():
    shifted = _production().replace(b"09:00:00", b"09:05:00").replace(b"09:15:00", b"09:20:00")
    preview = preview_incident_import(shifted, **META)
    assert preview["status"] == "BLOCKED"
    assert "15-minute boundary" in preview["issues"][0]["message"]


def test_file_boundaries_and_declared_timezone():
    with pytest.raises(ValueError, match="1 byte to 2 MiB"):
        preview_incident_import(b"x" * (2 * 1024 * 1024 + 1), **META)
    with pytest.raises(ValueError, match="decoded"):
        preview_incident_import(b"\xff", **META)
    with pytest.raises(ValueError, match="Unknown timezone"):
        preview_incident_import(_production(), **{**META, "timezone": "Mars/Base"})


def test_preview_identity_binds_timezone_scope_and_normalized_interpretation():
    raw = _production()
    first = preview_incident_import(raw, **META, scope={"line_id": "S4"})
    alternate = preview_incident_import(raw, **{**META, "timezone": "UTC"}, scope={"line_id": "S4"})
    changed_scope = preview_incident_import(raw, **META, scope={"line_id": "S5"})
    assert first["raw_digest"] == alternate["raw_digest"] == changed_scope["raw_digest"]
    assert len({first["preview_digest"], alternate["preview_digest"], changed_scope["preview_digest"]}) == 3


def test_imported_links_support_and_counterevidence_reproduce_engine_relationships():
    from flooreplay.incident_engine import analyze_incident
    records = [
        {"id": "block", "record_type": "line_block", "line_id": "S4", "summary": "Line awaiting fabric", "start": "2026-09-28T09:00:00", "end": "2026-09-28T09:15:00", "available_at": "2026-09-28T09:20:00", "line_blocking": True, "hypothesis_links": [{"category": "material", "relation": "SUPPORTS"}]},
        {"id": "denial", "record_type": "routine_note", "line_id": "S4", "summary": "Material was ready", "occurred_at": "2026-09-28T09:10:00", "available_at": "2026-09-28T09:21:00", "contradiction_refs": ["block"]},
    ]
    preview = preview_incident_import(json.dumps(records).encode(), profile="operations-v1", source_system="shift-log", timezone="Asia/Kolkata", filename="operations.json")
    assert preview["status"] == "READY"
    assert preview["events"][0]["hypothesis_links"][0]["source_id"] == "shift-log:block"
    report = analyze_incident({"scope": {"line_id": "S4", "unit": "good_units"}, "window": {"start": "2026-09-28T09:00:00+05:30", "end": "2026-09-28T09:30:00+05:30"}, "cutoff": "2026-09-28T09:30:00+05:30", **publish_incident_import(preview)})
    assert report["hypotheses"][0]["status"] == "CONTRADICTED"
    assert report["hypotheses"][0]["contradicting_evidence"] == ["denial"]


def test_inspection_keeps_original_headers_and_bounds_samples():
    from flooreplay.incident_import import inspect_incident_csv

    raw = b'Row ID,Good Output\n' + b''.join(f'r{i},{i}\n'.encode() for i in range(7))
    inspected = inspect_incident_csv(raw, filename='shift.csv', profile='production-v1')
    assert inspected['headers'] == ['Row ID', 'Good Output']
    assert inspected['row_count'] == 7 and len(inspected['sample_rows']) == 5
    assert inspected['sample_rows'][0] == {'Row ID': 'r0', 'Good Output': '0'}
    fields = {field['name']: field for field in inspected['fields']}
    assert fields['count_mode']['required'] is True
    assert {'source_id', 'supersedes_id'} <= set(fields)
    notes = inspect_incident_csv(raw, filename='notes.csv', profile='notes-v1')
    assert {'author_role', 'hypothesis_links', 'contradiction_refs'} <= {field['name'] for field in notes['fields']}


@pytest.mark.parametrize('raw', [b'id,id\na,b\n', b'id,  \na,b\n', b'id,name\na\n', b'id,name\na,b,c\n'])
def test_csv_structural_errors_use_shared_inspection_and_preview_parser(raw):
    from flooreplay.incident_import import inspect_incident_csv

    with pytest.raises(ValueError):
        inspect_incident_csv(raw, filename='shift.csv', profile='production-v1')
    with pytest.raises(ValueError):
        preview_incident_import(raw, **META)


def test_explicit_mapping_defaults_and_identity_are_part_of_interpretation():
    raw = b'Identity,Kind,Known at,From,To,Good Qty,Same Qty\nr1,final_good_delta,2026-09-28T09:15:00,2026-09-28T09:00:00,2026-09-28T09:15:00,12,12\n'
    mapping = {'id': 'Identity', 'record_type': 'Kind', 'available_at': 'Known at', 'start': 'From', 'end': 'To', 'quantity': 'Good Qty'}
    defaults = {'unit': 'good_units', 'factory': 'Synthetic A', 'line_id': 'S4', 'order_id': 'ORD-1', 'style_id': 'ST-42', 'stage': 'sewing', 'count_mode': 'delta'}
    preview = preview_incident_import(raw, **META, column_mapping=mapping, field_defaults=defaults)
    assert preview['status'] == 'READY'
    assert preview['output_buckets'][0]['quantity'] == 12
    assert preview['column_mapping'] == mapping and preview['field_defaults'] == defaults
    alternate = preview_incident_import(raw, **META, column_mapping={**mapping, 'quantity': 'Same Qty'}, field_defaults=defaults)
    assert alternate['output_buckets'] == preview['output_buckets']
    assert alternate['raw_digest'] == preview['raw_digest'] and alternate['preview_digest'] != preview['preview_digest']
    empty = preview_incident_import(_production(), **META, column_mapping={}, field_defaults={'count_mode': 'delta'})
    assert empty['status'] == 'BLOCKED' and not empty['output_buckets']
    legacy = preview_incident_import(_production(), **META)
    assert legacy['interpretation_version'] == 'incident-import-v2' and 'column_mapping' not in legacy


@pytest.mark.parametrize('mapping,defaults,message', [
    ({'unknown': 'id'}, {'count_mode': 'delta'}, 'Unknown canonical'),
    ({'id': 'id'}, {'id': 'constant-id', 'count_mode': 'delta'}, 'both a mapped'),
    ({'id': 'id', 'source_id': 'id'}, {'count_mode': 'delta'}, 'more than one'),
    ({'id': 'missing'}, {'count_mode': 'delta'}, 'missing'),
    ({'id': 'id'}, {}, 'explicit count_mode'),
])
def test_mapping_rejects_ambiguous_or_unconfirmed_interpretation(mapping, defaults, message):
    with pytest.raises(ValueError, match=message):
        preview_incident_import(_production(), **META, column_mapping=mapping, field_defaults=defaults)


def test_mapping_csv_only_and_blank_source_values_never_default():
    with pytest.raises(ValueError, match='only to CSV'):
        preview_incident_import(b'[]', **{**META, 'filename': 'output.json'}, column_mapping={})
    raw = _production().replace(b',12,', b',,')
    mapping = {field: field for field in HEADERS.strip().split(',')}
    result = preview_incident_import(raw, **META, column_mapping=mapping, field_defaults={'count_mode': 'delta'})
    assert result['status'] == 'BLOCKED' and 'quantity' in result['issues'][0]['message']


@pytest.mark.parametrize('profile,kind,extra', [
    ('operations-v1', 'line_block', {'line_blocking': 'true', 'start': '2026-09-28T09:00:00', 'end': '2026-09-28T09:15:00'}),
    ('notes-v1', 'maintenance_note', {'author_role': 'Technician'}),
])
def test_mapped_operations_and_notes_preserve_typed_links(profile, kind, extra):
    raw = b'Ticket,Observation,Known,Occurred\nN1,Recorded source observation,2026-09-28T09:20:00,2026-09-28T09:10:00\n'
    result = preview_incident_import(raw, profile=profile, source_system='shift-log', timezone='Asia/Kolkata', filename='events.csv', column_mapping={'id': 'Ticket', 'summary': 'Observation', 'available_at': 'Known', 'occurred_at': 'Occurred'}, field_defaults={'record_type': kind, 'line_id': 'S4', 'hypothesis_links': '[{"category":"machine","relation":"SUPPORTS"}]', **extra})
    assert result['status'] == 'READY'
    event = result['events'][0]
    assert event['hypothesis_links'] == [{'category': 'machine', 'relation': 'SUPPORTS', 'source_id': 'shift-log:N1'}]
    assert (event.get('assertion') is True) == (profile == 'notes-v1')
