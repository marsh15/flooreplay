# CSV column mapping

CSV imports support downloadable synthetic examples and explicit column mapping. Local acceptance was recorded on October 1, 2026, during the third improvement pass. RELEASE_STATUS.md describes the local database interruption that limits the overall browser suite. Cumulative counter readings and reviewed identifier aliases were added on October 19, 2026. XLSX files and saved mapping presets are not supported.

## Choose and inspect the file

Sign in as an owner and open incident imports. Download a baseline, output, correction, operation or note example from `/import-examples/`. The [example instructions](../frontend/public/import-examples/README.md) describe a complete synthetic sequence with matching scope and increasing evidence cutoffs.

Choose the production, operations or notes profile and declare the source system and timezone. CSV headers must be unique. Match each canonical field to its source column. Check the first rows, date interpretation, units and scope before previewing. Mapping is explicit; similar column names do not establish that fields have the same meaning.

For an unfamiliar export, map its count column to quantity and declare what it records: count_mode `delta` for the good units in each 15-minute interval, or `cumulative` for a counter reading at each interval end. Map its source publication time to available_at, and its event time to occurred_at where appropriate. Never declare a running total as delta. Production intervals require start and end, a 15-minute boundary and exactly 15 minutes of duration.

## Defaults and omitted fields

A field default supplies the same value for every row in the file. For example, a single-line export may omit factory, line, order, style or stage columns. Set those fields only after checking the export's actual scope. A field cannot have both a source-column mapping and a default. A blank mapped cell remains blank; the default does not fill it automatically.

A source column can map to only one canonical field. Unknown canonical fields and references to nonexistent source headers are rejected. Inspect unmapped source columns before deciding to omit them, particularly correction IDs and relationship fields. source_id can be omitted when the generated source-system-plus-record-ID identity is suitable.

Production requires an explicit good_units unit, a nonnegative integer quantity and delta counts. A new incident requires baseline plan records. Existing incident imports append observations or corrections; they cannot replace the baseline plan. Corrections have a new id and a supersedes_id pointing to the original record.

Notes require author_role and a summary or text. Relationship cells contain JSON arrays. `[]` means no relationship claim. CSV quoting must preserve embedded JSON quotes. A typed SUPPORTS link records the source's assertion. It does not independently prove a cause. Explicit line blocks require the line_block record type, true line_blocking and a valid interval.

## Cumulative counter readings

With count_mode `cumulative`, each final_good_delta row is the counter value at its interval end. The preview subtracts the reading that ends exactly where the interval starts and publishes that difference as the interval delta. The delta is available at the later of its two readings' available_at times, so a cutoff never sees it before both readings existed.

A reading produces no delta when there is no earlier value to subtract: the first reading for a scope (ANCHOR), a reading after a missing interval (GAP) or a reading lower than the previous one (RESET). Its interval stays uncounted and the analysis reports the output as missing. Include the reading that ends at the window start to count the first interval. The preview lists every reading with its outcome; the list is part of the preview identity and is stored with the original file.

Baseline plans and corrections remain deltas. One file cannot mix delta and cumulative output for the same scope, a duplicate interval blocks the file, and a file whose readings derive no delta at all is blocked rather than published as an empty revision. Readings carried in earlier imports are not reused, so the first reading of each new file is an anchor.

## Identifier aliases

When a source names this incident's line, order, style or factory differently, add a reviewed alias such as `Line 4 → S4`. Each alias maps one exact source value to the incident's own identifier. Aliases cannot chain, map a value to itself or target another incident's identifier. With an alias map present, any row whose identifier is neither the incident's nor a reviewed alias blocks the preview.

Remapped records keep `original_identity` with the source value and `alias_map_version`, a digest of the map. The map is bound into the preview identity, so changing it requires a new preview, and an idempotent retry with a different map is refused. No identifier is matched by similarity.

## Preview and publish

Preview normalizes the source columns and shows diagnostics for each row. Any blocking row prevents publication of the whole file. Publication also checks the current incident revision, matching scope, known correction targets and allowed production intervals. A READY row preview does not establish that an unrelated target incident accepts the file.

The preview identity binds the original source bytes, selected columns, defaults, profile, timezone, scope and normalized interpretation. Editing any of these requires a new preview. Publication stores the original file and mapping alongside the immutable revision so a reviewer can reconstruct the interpretation. Earlier reports retain their previous records and cutoff.

CSV mapping applies to CSV files only. Existing canonical JSON and JSONL imports remain available; relationship fields in JSON are actual arrays rather than encoded strings. Private workspace access boundaries are implemented. Confidential customer records remain out of scope until authenticated hosted acceptance and the operational requirements for a real-data pilot are verified.
