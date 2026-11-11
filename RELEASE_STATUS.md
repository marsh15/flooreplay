# Release status: FloorReplay 2.0 (order decisions)

Branch `codex/v2-outer-layer`, checked on 2026-11-11 against a freshly migrated and seeded disposable PostgreSQL database. All data is synthetic. The earlier version's evidence is in [docs/v1/RELEASE_STATUS.md](docs/v1/RELEASE_STATUS.md).

## Verified locally

| Check | Result |
| --- | --- |
| Backend tests (`pytest`) | 1,368 collected, all pass; 995 of them in `tests/decisions` |
| Backend lint (`ruff`) and types (`mypy`, 83 source files) | Clean |
| `dataset-verify` (v1 dataset) | PASSED |
| `decision-cases-verify` (9 synthetic cases: labels, engine and declared comparison agree) | PASSED |
| Seeding twice | The second run creates nothing (all six demo counters are 0) |
| Generated contract (`export-openapi`, `generate:api`) | No drift in `backend/openapi.json`, `frontend/src/lib/generated-api.ts` or `frontend/src/data` |
| Frontend lint, type check and production build | Clean |
| Browser suite (`playwright test`, 116 tests, 4 workers) | 113 pass, 3 fail (see below) |
| Order decision browser specs (workbench, timeline, lab, review, imports, transport, live) | Pass; the specs run an accessibility scan on the pages they open |
| Live spec against the real API and the seeded demo | Passes, including one sign-in, a recorded decision and an owner adopting a policy in a private workspace |
| `uv audit --frozen` | No known vulnerabilities in 64 packages |
| `pnpm audit --audit-level high` | Passes. One moderate advisory remains (minimatch, reached only through `typescript-eslint` in development tooling) |

The three browser failures are v1 live specs (`incident-csv-mapping-live`, `incident-workflow-live`, `ledger-features`). They failed once in a four-worker run and pass (7 of 7) when run one at a time. They share seeded incidents, so they interfere under parallelism. They are not order decision code, and I have not changed them.

An independent read-only review of the backend changes found no access-control violation. It found five low-severity issues; three were fixed (anonymous replays are now limited to 120 a minute per client, order summaries use the same settled cutoff as the decision view, and seeding no longer fails on a clock earlier than the demo date). Two remain open and are listed below.

## What was not verified

- **Not deployed.** The hosted site still runs the earlier version (commit `f5bab391`). There is no hosted acceptance receipt for 2.0, no authenticated hosted check and no run of GitHub Actions on this branch, which has not been pushed. A deployment runs migrations and then seeds, so the demo appears on first start; take a database backup first (see [DEPLOY.md](DEPLOY.md)).
- **No practitioner validation.** No interview is recorded. The constraint list and default parameters are drafts ([discovery notes](docs/v2/discovery.md)).
- **No model accuracy.** The 100-note English, Tamil and Tanglish corpus (`backend/evaluation/note-benchmark-v1/`) holds unreviewed draft labels, and no model has been scored against it. Extraction is not reachable from the web app. A Tamil speaker must review the labels before any comparison is meaningful.
- **No load or abuse testing.** The anonymous replay limit lives in process memory, so it resets on restart and does not span instances.

## Known limits

- Material fabric or trims shortfalls give NEEDS_REVIEW; split shipments are not proposed.
- The public demo is read-only. Recording a decision or adopting a policy needs a private workspace: `python -m flooreplay decisions-demo --owner <username>` loads the demo into one. Loading runs outside HTTP on purpose, because authoring `known_at` is refused on every request path.
- Review items do not carry the original note text, only the quoted evidence and its character range.
- Posting the same decision twice records it twice; the latest record is final.
- A stored evaluation's replay key does not include coverage. Evaluations stored before 2.0 started loading stock-export coverage may report a digest mismatch when reconstructed.
- An order's timeline shows at most 500 facts.
- The live browser spec's signed-in half adopts a policy, which a workspace can do once, so it needs a freshly loaded sandbox (CI provides one).

## Next steps that need a person

1. Push the branch and let GitHub Actions run; fix anything it finds.
2. Review the Tamil gold labels, or leave the benchmark out of any claim.
3. Back up the production database, deploy, and run `scripts/hosted_acceptance.py` with an owner login; commit the dated receipt to `docs/evidence/`.
4. Hold at least two practitioner conversations before presenting the defaults as anything but drafts.
