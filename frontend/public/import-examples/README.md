# Synthetic CSV import examples

These files describe one invented incident on line S-CSV. They contain no factory records. Use them to try normalization; they do not validate operations. Do not import confidential records into the public synthetic demonstration.

| File | Profile | Purpose |
|---|---|---|
| production-v1.csv | production-v1 | One baseline plan bucket for creating a new incident |
| production-output-v1.csv | production-v1 | One observed 15-minute final-good delta |
| production-output-correction-v1.csv | production-v1 | Corrects csv-output-1 from 12 to 14 good units |
| operations-v1.csv | operations-v1 | An explicitly confirmed material-linked line block |
| notes-v1.csv | notes-v1 | A late maintenance observation with no asserted hypothesis support |

## Suggested local sequence

Sign in as an owner. Create a new incident with a unique identifier and this scope: factory `Synthetic CSV factory`, line `S-CSV`, order `ORD-CSV`, style `STYLE-CSV`, stage `sewing`. Set the observation window to `2026-09-28T09:00:00+05:30` through `2026-09-28T09:15:00+05:30`, timezone `Asia/Kolkata`, cutoff `2026-09-28T09:15:00+05:30`, and source system `synthetic-csv`. Preview production-v1.csv and create the incident only after all rows pass.

Append production-output-v1.csv with cutoff `2026-09-28T09:16:00+05:30`. Then append the correction with cutoff `2026-09-28T09:25:00+05:30`. The correction requires the original csv-output-1 record already in this incident. Its new identifier and supersedes_id preserve the original reading. Do not publish both as unrelated output counts.

Append operations-v1.csv and notes-v1.csv against the latest revision with strictly increasing cutoffs admitting their availability times. For example, use `2026-09-28T09:26:00+05:30` for the operation and `2026-09-28T09:30:00+05:30` for the note. A cutoff determines which evidence was available for the revision. It can differ from the end of the production window: the late note describes 09:08 but is unavailable before 09:30.

For another incident, change every scope field and record ID to match the target. Existing baseline plans are immutable, so use the baseline file to create a new incident. Preview checks how the importer interprets each row. Publication also checks incident scope, revision freshness and replacement relationships.

## Column meanings

Production quantity is a nonnegative integer count of final good units in exactly one 15-minute interval. It is a delta, not a running total, percentage, target rate or total garment count across stages. start must land on a 15-minute boundary; end must be exactly 15 minutes later. unit is explicitly `good_units`; count_mode is explicitly `delta`. Cumulative counts remain unsupported.

available_at is when the source made the record available. occurred_at is when the event or observation happened. Explicit timestamp offsets take precedence; timezone interprets timestamps that lack an offset. Keep the preview's normalized dates visible and check them before publication.

source_id is optional and otherwise becomes `source_system:id`. Scope is explicit in these examples. Mapping defaults may supply absent scope fields only when deliberately selected; they must not silently overwrite conflicting row values. Profile and source system are separate import settings.

Relationship fields contain JSON arrays, not comma-separated words. For example, linked_categories contains `["material"]`. CSV quotes inside such cells must be doubled, as the downloaded file demonstrates. hypothesis_links accepts objects with category and relation `SUPPORTS` or `CONTRADICTS`. An empty array `[]` makes no relationship claim. A note requires author_role; author_role is source attribution, not account authentication.

A block contributes line-wide time only when record_type is `line_block`, line_blocking is explicitly true, and it has valid start/end intervals. A machine interruption or maintenance note does not automatically count as a production block.
