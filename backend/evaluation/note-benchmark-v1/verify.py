"""Verify local draft corpus bytes and relationships; never certify or change gold labels."""

from __future__ import annotations

import hashlib
import json
import sys
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

FILES = ("notes.jsonl", "gold.jsonl", "pilot.jsonl")
LANGUAGES = ("en", "ta", "tanglish")
FIELDS = ("lot_id", "issue", "qty", "unit", "colour", "fabric_quality")


def verify_manifest(root: Path) -> dict[str, Any]:
    problems: list[str] = []
    try:
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        if not isinstance(manifest, dict) or not isinstance(manifest.get("files"), dict):
            raise ValueError("manifest must declare its files")
    except (OSError, ValueError) as exc:
        return {
            "problems": [f"invalid manifest: {exc}"],
            "counts": {},
            "pilot_counts": {},
            "frozen": False,
        }
    if set(manifest["files"]) != set(FILES):
        problems.append("manifest must track notes.jsonl, gold.jsonl and pilot.jsonl")
    rows: dict[str, list[dict[str, Any]]] = {}
    for filename in FILES:
        records: list[dict[str, Any]] = []
        rows[filename] = records
        path = root / filename
        if not path.is_file():
            problems.append(f"missing file: {filename}")
            continue
        raw = path.read_bytes()
        entry = manifest["files"].get(filename, {})
        if not isinstance(entry, dict):
            problems.append(f"invalid manifest entry: {filename}")
            entry = {}
        if hashlib.sha256(raw).hexdigest() != entry.get("sha256"):
            problems.append(f"digest mismatch: {filename}")
        try:
            for line_number, line in enumerate(raw.decode("utf-8").splitlines(), start=1):
                if not line.strip():
                    continue
                record = json.loads(line)
                if not isinstance(record, dict):
                    raise ValueError(f"line {line_number} is not an object")
                records.append(record)
        except (UnicodeError, ValueError) as exc:
            problems.append(f"invalid JSONL: {filename}: {exc}")
        if len(records) != entry.get("records"):
            problems.append(f"record count mismatch: {filename}")
    notes, gold, pilot = (rows[name] for name in FILES)
    for filename, records in rows.items():
        ids = [record.get("note_id") for record in records]
        if any(not isinstance(value, str) or not value for value in ids):
            problems.append(f"missing note_id: {filename}")
        if len({value for value in ids if isinstance(value, str)}) != len(ids):
            problems.append(f"duplicate or invalid note_id: {filename}")
    notes_by_id = {note["note_id"]: note for note in notes if isinstance(note.get("note_id"), str)}
    if {item.get("note_id") for item in gold if isinstance(item.get("note_id"), str)} != set(
        notes_by_id
    ):
        problems.append("gold note IDs differ from notes")
    for note in notes:
        text = note.get("text")
        if note.get("synthetic") is not True or note.get("drafted_by") != "codex":
            problems.append(f"missing synthetic drafting provenance: {note.get('note_id')}")
        if note.get("language") not in LANGUAGES:
            problems.append(f"unsupported language: {note.get('note_id')}")
        if not isinstance(text, str) or not text or unicodedata.normalize("NFC", text) != text:
            problems.append(f"missing or non-NFC text: {note.get('note_id')}")
    for annotation in gold:
        annotation_id = annotation.get("note_id")
        note = notes_by_id.get(annotation_id, {}) if isinstance(annotation_id, str) else {}
        if annotation.get("text") != note.get("text") or annotation.get("language") != note.get(
            "language"
        ):
            problems.append(f"gold source mismatch: {annotation.get('note_id')}")
        if not isinstance(annotation.get("gold_status"), str) or not annotation["gold_status"]:
            problems.append(f"missing gold status: {annotation.get('note_id')}")
        for field in FIELDS:
            claim = annotation.get(field)
            if field not in annotation:
                problems.append(f"missing gold field: {annotation.get('note_id')}.{field}")
            elif claim is not None and (
                not isinstance(claim, dict)
                or set(claim) != {"value", "evidence"}
                or not isinstance(claim.get("value"), str)
                or not isinstance(claim.get("evidence"), str)
                or not claim["evidence"]
                or claim["evidence"] not in str(note.get("text", ""))
            ):
                problems.append(f"invalid gold evidence: {annotation.get('note_id')}.{field}")
    for item in pilot:
        if (
            set(item) != {"note_id"}
            or not isinstance(item.get("note_id"), str)
            or item["note_id"] not in notes_by_id
        ):
            problems.append("pilot must contain only known note IDs")
    counts = Counter(
        note.get("language") for note in notes if isinstance(note.get("language"), str)
    )
    pilot_counts = Counter(
        notes_by_id[item["note_id"]]["language"]
        for item in pilot
        if isinstance(item.get("note_id"), str)
        and item["note_id"] in notes_by_id
        and isinstance(notes_by_id[item["note_id"]].get("language"), str)
    )
    actual_counts = {language: counts[language] for language in LANGUAGES}
    actual_pilot = {language: pilot_counts[language] for language in LANGUAGES}
    if actual_counts != manifest.get("counts_by_language") or len(notes) != manifest.get(
        "note_count"
    ):
        problems.append("note/language counts differ from manifest")
    if actual_pilot != manifest.get("pilot_counts_by_language") or len(pilot) != manifest.get(
        "pilot_count"
    ):
        problems.append("pilot/language counts differ from manifest")
    return {
        "problems": problems,
        "counts": actual_counts,
        "pilot_counts": actual_pilot,
        "frozen": manifest.get("frozen"),
    }


if __name__ == "__main__":
    report = verify_manifest(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    raise SystemExit(1 if report["problems"] else 0)
