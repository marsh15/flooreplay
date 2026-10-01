# FloorReplay demonstration

Use the synthetic example to show how a supervisor investigates a sewing-line shortfall. This is a product walkthrough, not proof of factory effectiveness. See [INCIDENT_DEMO.md](INCIDENT_DEMO.md) for the evidence details and [RELEASE_STATUS.md](RELEASE_STATUS.md) for measured checks.

## Start locally

Run `docker compose up --build --wait` and open [the application](http://localhost:5174). Alternatively follow the native setup in [README.md](README.md). Create separate owner and reviewer accounts with the prompted CLI before demonstrating protected actions. No provider request is needed for the deterministic walkthrough.

## Five-minute walkthrough

1. Open "Delayed start on sewing line S4" in the incident library. State the job: determine what is known about a shortfall and choose the next evidence check.
2. Select revision 1. At its 11:00 cutoff, the plan totals 160 final good units and recorded output totals 87. Inspect the records behind the 73-unit shortfall. Explain that missing intervals are unknown, not zero.
3. Open the material record and line-block assertion. The explicit block intervals total 30 minutes. Do not claim that this explains every missing unit. Read the machine and QC uncertainties.
4. Switch to revision 2 and open its comparison with the earlier revision. Inspect changed metrics, newly available and corrected records, hypotheses and review reminders. Explain why the maintenance note first becomes available here: it entered the source system at 11:20. The earlier report remains pinned to its original evidence.
5. Sign in and submit/review a current proposal with a rationale. Explain exactly what that records. Approval does not execute factory work or prove resolution.
6. Print the deterministic report and inspect its revision, report identity, evidence and assumptions. The AI panel is excluded from this print view. The portable JSON export remains available to authenticated users.

The second pass adds the assigned-check walkthrough below, with local acceptance recorded on October 1, 2026. Do not present proposal approval as completed operational work.

## Optional engineering walkthrough

Open the evaluation lab. Explain arithmetic and citation-membership results with their denominators. OpenAI smoke and pilot have recorded structural results. Independent claim-support review and manufacturing validation remain pending. The authenticated claim-review interface accepts judgments and rationales against the exact output digest and retains durable receipts. This control does not supply independent reviewer findings. Only make a paid draft request when the account and allowance permit it; inspect the output's citations, limitations and receipt afterward.

A citation check proves that a reference belongs to the permitted evidence packet. It does not prove that the referenced record supports the claim. A retrieved precedent is a comparison case, not proof of the current cause.

## Explain the implementation without a script

Trace one CSV through preview validation, immutable revision publication and cutoff filtering. Explain a shortfall calculation using its complete intervals. Explain why late evidence cannot enter an earlier report. Show how the request identity recovers a saved AI result after an interruption, and why an uncertain paid request cannot silently repeat.

The older qualified-operator coverage workflow is archived in [COVERAGE_ARCHIVE.md](COVERAGE_ARCHIVE.md) and the `coverage-v1` Git tag.

## Assigned-check walkthrough

Sign in and create a check from a current proposal. Select an active assignee and a due time. Start the check, then submit a source-linked response with all requested fields. Inspect the resulting evidence revision and confirm that the original report remains unchanged.

Record the action actually taken, completion time, assessment and remaining uncertainty. Optional observed output must include its observation time. Explain that subsequent output does not prove the action caused a change. Show the shift handover and its outstanding checks, owners and deadlines.

Mark the incident resolved only as a separate decision with a rationale, after all checks are completed or cancelled and at least one has a completed outcome. Explain that new evidence makes the old revision-bound resolution stale. Review the full rules in [incident workflow](docs/incident-workflow.md).
