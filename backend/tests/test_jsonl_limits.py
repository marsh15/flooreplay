"""JSONL row bounds preserve existing source-line interpretation."""

import json

import pytest

from flooreplay.incident_import import MAX_ROWS, _records


def test_jsonl_accepts_exact_row_limit_and_blank_crlf_lines():
    raw = b"\r\n" + b"{}\r\n" * MAX_ROWS + b" \r\n"
    assert _records(raw, "source.jsonl") == [{}] * MAX_ROWS


def test_jsonl_refuses_row_limit_before_decoding_an_extra_record():
    raw = b"{}\n" * MAX_ROWS + b"not-json\n"
    with pytest.raises(ValueError, match="^More than 10,000 rows$"):
        _records(raw, "source.jsonl")


def test_jsonl_preserves_python_source_line_separators():
    # Preserve the historical splitlines contract, including rejection of raw U+2028 in a string.
    assert _records(b"{}\x0c{}", "source.jsonl") == [{}, {}]
    with pytest.raises(json.JSONDecodeError):
        _records('{"note":"a\u2028b"}'.encode(), "source.jsonl")
