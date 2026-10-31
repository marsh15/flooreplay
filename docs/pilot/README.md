# Comparative pilot: collecting baseline and FloorReplay pairs

This folder holds the blank record for the comparative pilot defined in
[`../comparative-pilot.md`](../comparative-pilot.md). It contains no results.
No operational benefit has been measured.

- `comparative-pilot-template.csv`: header only. Copy it, then add one row per method attempt.
- Run the measurement tool offline (no API calls, no database):

  ```sh
  cd backend
  uv run --python 3.12 python -m flooreplay.pilot_measurement ../docs/pilot/my-pilot.csv --output ../docs/pilot/my-pilot-summary.json
  ```

  Invalid or blank input exits with status 1, lists every problem with its line number,
  and writes no summary. A summary is produced only from a complete, valid file.

## Before the first session

Write down, and keep with the consent record: case selection, complexity bands, what counts
as an actionable next check and as relevant evidence, exclusion rules, the analysis, and the
participant roles, experience and case authorship. Those details do not go in the CSV. Decide
them before timing anything. Get permission to take notes and to keep anonymized records.
Use participant codes, not names, and no customer or confidential production identifiers.

## Collecting honest pairs

- **One row per method attempt.** A baseline row and a FloorReplay row with the same `pair_id`
  form one pair. Both rows of a pair must share participant, cohort, complexity and method order.
- **Comparable, different cases.** Each method gets its own `case_id`, of the same complexity,
  so the first method does not teach the second. Different participants can use the same cases;
  do not count the same participant, case and method twice within a cohort.
- **Counterbalance the order.** Alternate `baseline_first` and `flooreplay_first` across participants.
- **Keep the same evidence available to both methods**, or note the difference in `notes`.
- **Keep failures.** Record `failed` and `timed_out` rows. Never delete a row because it went badly.
  Only `success` rows carry `completion_seconds`; failed and timed-out rows leave it blank.
- **Blank means not recorded. `0` means zero.** A blank cell is left out of every denominator.
  Do not fill it in afterwards.
- **Record times as elapsed seconds, when they happen**, from the start of that case for that
  method. Do not reconstruct them from memory.
- **Count every instance of author assistance**, training or interruption in `assistance_count`
  and describe it in `notes`. Assistance is never hidden inside a success.
- **Use one release per file.** Every FloorReplay row names the same commit in `release`.
  Baseline rows leave `release` blank.
- **Keep cohorts apart.** `synthetic` is the prototype walkthrough. `practitioner` is a real case
  from a consenting practitioner. Do not mix the two in one row.
- **AI conditions are out of scope for this file.** The CSV has no provider, model or cost columns.
  Run any AI-assisted condition as a separately identified pilot with its own record.

## Columns

| Column | Rule |
|---|---|
| `pair_id` | Required. Links one baseline row to one FloorReplay row. |
| `cohort` | Required. `synthetic` or `practitioner`. |
| `participant_id` | Required. Code only. Separate sessions in both cohorts are allowed. |
| `case_id` | Required. Unique per participant, method and cohort across the file. |
| `case_complexity` | Required. `low`, `medium` or `high`. Must match within a pair. |
| `method` | Required. `baseline` or `flooreplay`. |
| `method_order` | Required. `baseline_first` or `flooreplay_first`. Must match within a pair. |
| `release` | Required on `flooreplay` rows, blank on `baseline` rows. |
| `outcome` | Required. `success`, `failed` or `timed_out`. |
| `completion_seconds` | Required on `success`, blank on `failed` and `timed_out`. Seconds, 0 or more. |
| `first_missing_evidence_seconds` | Optional. Not after `completion_seconds`. |
| `report_seconds` | Optional. Seconds, 0 or more. |
| `evidence_expected`, `evidence_found` | Optional. Whole numbers; found cannot exceed expected. |
| `unsupported_conclusions`, `conclusions_assessed` | Optional. Whole numbers; unsupported cannot exceed assessed. |
| `errors`, `source_omissions`, `clarification_rounds`, `assistance_count` | Optional. Whole numbers, 0 or more. |
| `reviewer_confidence` | Optional. 1 to 5. |
| `usefulness_rating` | Optional. 1 to 5. 1 is unusable for the task; 5 is useful without material correction. |
| `notes` | Free text. Practitioner feedback and assistance descriptions go here. Not summarised. |

## Reading the summary

The summary separates the two cohorts. For each method it reports outcome counts and success
rate over all attempts. Times are summarised over the rows that recorded them. Paired medians and
per-pair differences use only comparable completed pairs, where both rows succeeded. The
`outcome_pairs` counts show every pair, including those where FloorReplay failed or timed out.

Describe a small convenience sample only in terms of the participants and cases observed. The
summary is not evidence of manufacturing benefit, productivity or return on investment, and
it cannot show that a change in output was caused by FloorReplay.
