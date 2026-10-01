# CSV column mapping

The third improvement pass adds downloadable synthetic examples and explicit CSV column interpretation. Local acceptance is recorded on October 1, 2026. The overall browser suite has a local database interruption limitation described in RELEASE_STATUS.md. It does not add cumulative-count conversion, XLSX files or saved mapping presets.

## Choose and inspect the file

Sign in as an owner and open incident imports. Download a baseline, output, correction, operation or note example from `/import-examples/`. The [example instructions](../frontend/public/import-examples/README.md) describe a complete synthetic sequence with matching scope and increasing evidence cutoffs.

Choose the production, operations or notes profile and declare the source system and timezone. CSV headers must be unique. Match each canonical field to its source column. Check the first rows, date interpretation, units and scope before previewing. Mapping is explicit; similar column names do not establish that fields have the same meaning.

For an unfamiliar export, map its count column to quantity only if it records 15-minute final-good deltas. Map its source publication time to available_at, and its event time to occurred_at where appropriate. Do not map a cumulative total to quantity. Production intervals require start and end, a 15-minute boundary and exactly 15 minutes of duration.

## Defaults and omitted fields

A deliberate field default supplies one constant across the file. For example, a single-line export may omit factory, line, order, style or stage columns. Set those fields only after checking the export's actual scope. A field cannot have both a source-column mapping and a default. A blank mapped cell remains blank; the default does not fill it automatically.

A source column can map to only one canonical field. Unknown canonical fields and references to nonexistent source headers are rejected. Inspect unmapped source columns before deciding to omit them, particularly correction IDs and relationship fields. source_id can be omitted when the generated source-system-plus-record-ID identity is suitable.

Production requires an explicit good_units unit, a nonnegative integer quantity and delta counts. A new incident requires baseline plan records. Existing incident imports append observations or corrections; they cannot replace the baseline plan. Corrections have a new id and a supersedes_id pointing to the original record.

Notes require author_role and a summary or text. Relationship cells contain JSON arrays. `[]` means no relationship claim. CSV quoting must preserve embedded JSON quotes. A typed SUPPORTS link is a source assertion; it is not independent proof of cause. Explicit line blocks require the line_block record type, true line_blocking and a valid interval.

## Preview and publish

Preview normalizes the source columns and shows row diagnostics. Any blocking row prevents publication of the whole file. Publication also checks the current incident revision, matching scope, known correction targets and allowed production intervals. A READY row preview does not establish that an unrelated target incident accepts the file.

The preview identity binds the original source bytes, selected columns, defaults, profile, timezone, scope and normalized interpretation. Editing any of these requires a new preview. Publication stores the original file and mapping alongside the immutable revision so a reviewer can reconstruct the interpretation. Earlier reports retain their previous records and cutoff.

CSV mapping applies to CSV files only. Existing canonical JSON and JSONL imports remain available; relationship fields in JSON are actual arrays rather than encoded strings. Confidential customer records remain out of scope until private workspace access boundaries are implemented and verified.
