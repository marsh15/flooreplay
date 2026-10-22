"""Draft corpus provenance, language balance, exact evidence and manifest integrity."""

from __future__ import annotations

import json
import runpy
import shutil
from collections import Counter
from pathlib import Path

from flooreplay.decisions.extraction.schema import (
    SIGNAL_FIELDS,
    normalize_note,
    validate_signal_payload,
)

CORPUS = Path(__file__).parents[2] / "evaluation" / "note-benchmark-v1"


def _rows(path: Path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _verify(root: Path):
    return runpy.run_path(str(CORPUS / "verify.py"))["verify_manifest"](root)


def test_corpus_manifest_tracks_one_hundred_draft_synthetic_notes_and_stratified_pilot():
    report = _verify(CORPUS)
    assert report["problems"] == []
    assert report["counts"] == {"en": 40, "ta": 30, "tanglish": 30}
    assert report["pilot_counts"] == {"en": 12, "ta": 9, "tanglish": 9}
    assert report["frozen"] is False
    notes = _rows(CORPUS / "notes.jsonl")
    gold = _rows(CORPUS / "gold.jsonl")
    assert len(notes) == len(gold) == 100
    assert len({note["text"] for note in notes}) == 100
    assert Counter(note["language"] for note in notes) == report["counts"]
    by_id = {note["note_id"]: note for note in notes}
    for annotation in gold:
        note = by_id[annotation["note_id"]]
        assert note["synthetic"] is True and note["drafted_by"] == "codex"
        assert annotation["gold_status"] == "draft_unreviewed"
        assert annotation["text"] == note["text"] == normalize_note(note["text"])
        assert annotation["language"] == note["language"]
        validate_signal_payload(
            {name: annotation[name] for name in SIGNAL_FIELDS} | {"language": note["language"]}
        )
        for field in SIGNAL_FIELDS:
            claim = annotation[field]
            if claim is not None:
                assert claim["value"] is not None
                assert claim["evidence"] in note["text"]
    pilot = _rows(CORPUS / "pilot.jsonl")
    assert all(set(item) == {"note_id"} for item in pilot)


def test_manifest_verifier_detects_byte_changes_even_when_json_records_are_unchanged(tmp_path):
    copied = tmp_path / "corpus"
    shutil.copytree(CORPUS, copied)
    notes = copied / "notes.jsonl"
    notes.write_bytes(notes.read_bytes() + b"\n")
    assert "digest mismatch: notes.jsonl" in _verify(copied)["problems"]


def test_manifest_verifier_reports_missing_files(tmp_path):
    copied = tmp_path / "corpus"
    shutil.copytree(CORPUS, copied)
    (copied / "gold.jsonl").unlink()
    assert "missing file: gold.jsonl" in _verify(copied)["problems"]


def test_manifest_verifier_reports_malformed_record_ids_without_crashing(tmp_path):
    copied = tmp_path / "corpus"
    shutil.copytree(CORPUS, copied)
    for filename in ("gold.jsonl", "pilot.jsonl"):
        path = copied / filename
        rows = _rows(path)
        rows[0]["note_id"] = {"invalid": "id"}
        path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    report = _verify(copied)
    assert "duplicate or invalid note_id: gold.jsonl" in report["problems"]
    assert "duplicate or invalid note_id: pilot.jsonl" in report["problems"]
