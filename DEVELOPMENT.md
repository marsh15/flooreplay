# Operator-coverage development log

This is the historical development log for the original operator-coverage workbench. It records the engine design, six milestones, defects found during review and the verification results for that version.

## Replay model

A replay is a pure function: `(pinned evidence, pinned configuration) -> structured, inspectable result`. The surrounding services pin its inputs, preserve its result and expose the evidence for inspection.

## Pure domain engine

`backend/src/flooreplay/domain/` contains no database access, no HTTP, no clock reads, no randomness at execution time. This gives the engine these properties:

- The same inputs always produce the same result (verified by tests: same manifest -> same digests, same proposal).
- Domain blocks (`NEEDS_CONTEXT`) are ordinary return values, not exceptions, so HTTP can treat them as successful executions.
- Tests run in milliseconds without infrastructure; only the API integration tests touch PostgreSQL.

## Execution, outcome and expectation

1. Execution lifecycle: `RUNNING / COMPLETED / ERRORED / INTERRUPTED`; did execution finish?
2. Domain outcome: `NEEDS_CONTEXT / CONFLICTING_CONTEXT / NO_FEASIBLE_CANDIDATE / REJECTED_BY_CONSTRAINT / READY_FOR_REVIEW`; what did the evidence and rules conclude?
3. Expectation verdict: `PASS / FAIL / NOT_EVALUATED`; did the run meet its pinned expectations?

A replay keeps its actual domain outcome even when it fails an expectation. The deliberate defect configuration demonstrates the distinction: it produces `READY_FOR_REVIEW` (its actual outcome) while its expectation fails.

## How a replay executes (engine.py)

```
1. context digest   = SHA-256 over canonical {catalog, snapshots, event, decision_at, target}
2. gate             = is the evidence good enough to act on at all?
3. policy           = rank eligible operators, propose one or abstain
4. validator        = independently re-check the proposal (C01..C12), never trusting the policy
5. outcome          = READY_FOR_REVIEW (all pass) | REJECTED_BY_CONSTRAINT (any fail)
```

### Evidence gate (gate.py)

- Missing evidence is never read as absence. No attendance row means `UNKNOWN`, not absent. No skill record means `UNKNOWN`, not level zero.
- Freshness is measured evidence-time vs the pinned `decision_at`, never `now()` and never upload time.
- Shared problems (stale snapshot, incomplete coverage, roster gaps, contradictions) block every policy: outcome `NEEDS_CONTEXT` or `CONFLICTING_CONTEXT`, and no policy runs.
- Candidate problems (absent, unqualified, occupied, unavailable) exclude that candidate only. A bad record for one operator never blocks a supported proposal for another.
- `NO_FEASIBLE_CANDIDATE` is only ever returned when the pool is *conclusively* excluded. If material unknown/stale evidence remains that could conceal a feasible candidate, the result is `NEEDS_CONTEXT`.

### The policies (policies.py)

- `baseline-v1`: ranks core-eligible candidates but deliberately omits assignment-overlap filtering. Its limitation is labeled everywhere it appears.
- `improved-v1`: filters every supported requirement before ranking.
- Ranking uses a tuple: higher skill level, then same-line preference, then operator id. The policies use no utility weights and make no optimality claim.

### The validator (validator.py)

The validator derives all twelve checks from pinned evidence independently. An unknown operator fails `C01` and makes dependent checks `NOT_EVALUATED` rather than inventing observations. Every FAIL carries an `EvidenceRef` (snapshot id + source row + field), which the UI turns into a clickable chip that opens the snapshot drawer with the row highlighted.

## Immutability and provenance

- Artifacts (catalog revision, snapshots, scenario revisions, expectations) are insert-only. Seeding is content-addressed: if content under a published ID changes, seeding fails with an error instead of silently rewriting history.
- Two digests per attempt: the context digest (the facts the decision was made on) and the manifest digest (everything pinned: artifacts, configuration, build, expectation).
- Idempotency is a database unique key: same key + same request returns the same attempt; same key + different request returns `409`.

## The synthetic world (fixtures.py)

Kaveri Garments Unit 3, Asia/Kolkata, 2026-09-22. Two lines, 22 operators, 2 styles, 8 operations, 12 named machines. The hero episode: decision 07:58, shift 08:00-16:30, `O117` cannot cover sleeve attach on Line 4 (machine SN-4407). `O204` is the most skilled but occupied on Line 3; `O219` is idle, skilled, same line. Revision 1 pins a stale skill snapshot (45 days); revision 2 pins the corrected one (4 days).

## Review of the early milestone implementation

A full review of the milestone 1-3 code (plus the first half of 4) against the documented evidence rules found the following defects and maintenance issues:

- Evidence selection was row-order dependent (a determinism bug in both gate and validator): when an export carried history for one operator, "last row in the list" won, so the same facts in a different file order could produce a different outcome. Both readers now select the record with the latest `observed_at`/`assessed_at`, and the validator also reads the *first* pinned snapshot of each kind, exactly like the gate. Covered by regression tests that replay row-order permutations.
- Future-dated attendance rows were trusted (skills had a future-evidence check; attendance did not). The gate now flags a row observed after `decision_at` as MATERIAL `FUTURE_EVIDENCE`, and validator C02 fails any proposal resting on it; the same rule C05 already enforced for skills. A future attendance row can no longer support a proposal through any policy.
- UI evidence and error handling: the Imports page kept a stale preview (and could publish an old digest against a new body; a violation of the preview publication contract); the workbench could show one replay's review verdict under a different replay (review outcomes are now keyed to the attempt they checked); the Notes page could cite a parser call whose text no longer matched the note (the draft is now tracked against the text it parsed, with a visible stale banner, and confirm drops the citation); oversized-file errors rendered in a hidden branch; saved-report errors were all mislabeled "nothing saved"; several query failures silently blanked sections; the report download link ignored `VITE_API_BASE`.
- Other correctness fixes: `ROSTER_P` was missing O112, so the curated example never exercised its own blank→UNKNOWN path (and silently triggered a roster-gap warning); unknown configuration ids were labeled "defect" in the library; clickable table rows gained keyboard access; a malformed `revision` URL param now shows an explicit not-found notice instead of silently falling back.
- Maintenance fixes: `clamp_to_instant`, `PolicyKind.ALL`, an over-indented engine block, a `type: ignore` replaced by an assert, function-level imports hoisted, and seeding now accepts only the `"computed-at-publish"` sentinel; an incorrect embedded digest fails with an error instead of being silently rewritten.

State after the audit: 103 backend tests (3 new), 10 E2E specs, mypy strict, ruff, eslint, and the production build pass; the 32-case suite outcomes are unchanged (the fixes close latent holes the suite's fixtures happened not to exercise).

## Milestone 6: verification and presentation (fixtures_eval.py, eval_notes.py, E2E)

Measure the results before demonstrating the workflow.

- Held-out note evaluation. `fixtures_eval.py` pins 16 labeled floor notes written *after* the parser rules were frozen; labels state what a careful human would extract (category, subject operators, operations, uncertainty), including deliberate traps: denied absences, display names instead of ids, a "will cover" operator who must not count as a subject, and a surname-only mention that must stay unresolved. `eval_notes.py` scores any parser against them with per-field accuracy and an exact-match rate. The offline rule baseline scores 50% exact (category 62%, subjects 62%, operations 88%, uncertainty 100%): it only sees exact operator ids, so every name-based note fails. These recorded misses explain why the notes workflow requires human confirmation of parser drafts.
- The rupee budget. The live evaluation charges the pinned model's published per-token price, converted at a rate pinned in code (`INR_PER_USD = 88.0`), and refuses to cross `--budget-inr` (default 500). The guard checks before each case, so the case that crosses the line still counts and its cost is reported; the run ends `BUDGET_EXHAUSTED` with whatever was measured. The offline baseline costs nothing. Running `--live` without a key refuses ("refusing to pretend this is live").
- End-to-end browser tests. Ten Playwright specs (`frontend/e2e/`) drive the real app through the whole story: the library, the hero matrix (stale → needs context; corrected → ready proposing O219; baseline → rejected by C07), the later-context review (stale with reason codes; still supported on an identical digest), the notes flow (draft → confirm → fork, plus the manual path), and a full 32-case comparison run asserting the exact totals tiles (32 / 0 / 0 / 0). They found real selector ambiguity on the first pass (a `SCEN-HERO@2` regex also matching revisions 20-28; the note page has four textboxes). Stricter locators fixed the ambiguity without adding waits. `make e2e` runs them; `make e2e-install` fetches Chromium.
- The demonstration script. `DEMO.md` is a narrated seven-act walkthrough where every step names the principle it demonstrates, with a 5-minute cut for short slots.

## Milestone 5: reliability and public limits (recovery, ratelimit.py, DEPLOY.md)

Execution failures remain visible in the recorded lifecycle.

- Startup recovery. `execute_replay` commits the attempt as `RUNNING` before executing, so a process that dies mid-execution leaves a stuck row. The FastAPI lifespan runs `recover_interrupted` once at boot: `RUNNING` → `INTERRUPTED`, with `completed_at` deliberately left empty (it never completed). Recovery is idempotent, logged, and failure-tolerant; if the database is unreachable at boot, the app still starts and `/health/ready` reports database availability. The library's "latest attempt" summaries already filtered on `COMPLETED`, so interrupted attempts surface only as their lifecycle badge, never as an outcome.
- Public-mode execution limits. The public demo gets two limits with different mechanisms, each with a stated reason:
  - Comparison execution is absent (`POST /api/v1/comparisons` is not registered; reads answer 405). One suite run executes 64 replays; that stays a local-owner action. Saved reports stay viewable everywhere.
  - Single replay executions and review checks are rate limited per client (`ratelimit.py`, sliding window, default 20/hour from `FLOORREPLAY_PUBLIC_REPLAYS_PER_HOUR`). The window is stored in process memory. This bounds abuse on free single-instance hosting; it cannot provide durable usage accounting. Rejection is `429 RATE_LIMITED` with `Retry-After`, and the message itself points at the saved-report fallback.
- The saved-report fallback. `GET /api/v1/replays/latest?scenario_id=&scenario_revision=&configuration_id=` returns the most recent `COMPLETED` attempt for an exact selection. The workbench renders it with a "Saved report" badge and an explicit banner: *loaded from history; not a fresh execution*. The UI labels the report as historical.
- Capabilities report active limits. `/capabilities` now reports the limits (`replays_per_hour_per_client`, `comparison_execution: local_only`), and the frontend renders from that instead of hardcoding: the comparison screen shows an owner-only notice instead of a button that would 405.
- Deployment. `render.yaml` (backend web service + frontend static site, free tier) with Neon's free PostgreSQL as the external database; `DEPLOY.md` has the full walkthrough, including CORS via `FLOORREPLAY_CORS_ORIGINS` and `VITE_API_BASE` for the deployed frontend (the dev proxy still serves `/api` locally).

## Milestone 4: notes, later-context review, portable reports (parsing.py, Notes screen, review panel)

A parser creates a draft. A human confirms it before the application records an event.

- The parser boundary. `parsing.py` exposes one interface with two implementations. `RuleBaselineParser` is offline and deterministic (regex extraction of the operator mention, operation words, unavailability phrasing, uncertainty words) and is the demo default without an API key. `OpenAIStructuredParser` calls the pinned `gpt-4.1-mini-2025-04-14` through raw `httpx` (no SDK, so no hidden retries), enforces the 2000-character cap, a 15-second monotonic deadline, and at most one retry; any failure raises `ParserUnavailable`. `get_parser(api_key)` picks; the API response always names the parser kind and live status so the UI can display "no API key configured" when appropriate.
- Drafts require confirmation. A parse returns a `DraftExtraction` (operator, operation, moment, uncertainty flags) plus mention resolutions. Resolution is exact operator id or documented alias only; an ambiguous mention retains its unresolved candidate list. Nothing persists until confirm.
- Confirm forks. `POST /notes/confirm` writes the immutable event and forks a new scenario revision with expectations carried over (`SCEN-HERO@28` in the demo database). The manual fallback radio records the event without any parser output; the parser call is audited either way (`parser_calls`: note digest, kind, model, latency, result or error).
- Later-context review checks whether *later, explicitly pinned* evidence still supports an existing proposal. `review_check(original_replay_id, target_scenario_id, target_revision)` re-runs the gate on the target revision's pinned context. Blocked → `BLOCKED_CONTEXT` with the issues. Otherwise compare the canonical context digests: identical → `STILL_SUPPORTED`; different → `STALE_RECOMMENDATION` with reason codes (`EVENT_CHANGED`, `DECISION_TIME_CHANGED`, `EVIDENCE_CHANGED`) and a recursive changed-path diff (`snapshots[4].rows[31].assessed_at`), element-wise through lists as well as dicts. The original replay is never altered.
- The three review fixtures (`SCEN-REVIEW-LATER` revs 1-3) are engine-verified to produce the three outcomes: the original 07:58 decision; refreshed evidence and plan revision C at 08:10 (stale); stale exports at 08:10 (blocked). All three are walkable from the workbench panel.
- Portable reports. `/api/v1/replays/{id}/export` returns the attempt's request, result, and both digests as one JSON document.
- Bug found and fixed during the build: the changed-path diff originally treated snapshot lists as atomic values; it now recurses element-wise with `[index]` paths, and the reason-code mapper strips `[...]` suffixes before classifying the path head.

## Milestone 3: the operational suite and comparison (fixtures_suite.py, Comparison screen)

- 32 named cases (`fixtures_suite.py`), each derived from the hero episode by a targeted mutation with an explicit defect statement and per-configuration demands. The cases were authored against the engine and validated case-by-case before any persistence was wired: 0 unintended mismatches, and exactly 3 intended defect-config failures (B1/F1/F4, the stale-evidence regressions the defect exists to exhibit).
- Expectations specify the required behavior. The baseline configuration legitimately fails healthy-coverage demands (its overlap blind spot is documented), so its demands are written as "REJECTED by C07"; the comparison therefore compares each config against its own pinned demands, and pass/fail records whether the result meets those expectations.
- Comparison execution (`run_comparison`): sequential, at most the suite's items, a monotonic 30-second budget checked between cases, results persisted as one report with a manifest digest and database-enforced idempotency. Classifications: UNCHANGED_PASS / FIXED / REGRESSION / UNCHANGED_FAIL; behavior changes (both pass, different decisions) are reported separately, never folded into pass/fail. An interrupted suite stores INTERRUPTED and can never pass overall.
- Two engine gaps found by authoring the suite, both fixed and now covered: (1) a recorded-unusable designated machine now conclusively blocks at the gate (NO_FEASIBLE_CANDIDATE with TARGET_MACHINE_UNUSABLE evidence) instead of waiting to fail C06 after a wasted proposal; (2) conclusive gate issues are no longer dropped from the result's issue list.
- Evidence rules in the fixtures: operators without a skill row are MATERIAL unknowns, so "everyone excluded" cases only become conclusive NO_FEASIBLE_CANDIDATE with a complete skill matrix; one operator's stale/future/unknown evidence never blocks a supported candidate elsewhere in the pool (cases E1/E2, C4).

## Milestone 2: the import pipeline (importing.py, Imports screen)

The import flow preserves the original export and records its interpretation before creating immutable evidence:

- Fixed, documented source profiles (`attendance-v1`, `skills-v1`) declare required columns, accepted codes, and the natural key. Extra columns are allowed and listed as ignored.
- The preview records normalization: `P` -> PRESENT, `A` -> ABSENT, blank -> UNKNOWN (never absent), naive timestamps -> Asia/Kolkata. Every applied rule appears on the row in the preview, and the original cells are preserved next to the normalized values.
- Row-level diagnostics carry a code, severity, column, and raw value: MISSING_REQUIRED_CELL, UNSUPPORTED_VALUE, INVALID_TIMESTAMP, UNKNOWN_OPERATOR/OPERATION, DUPLICATE_NATURAL_KEY, FORMULA_LIKE_CELL (warning), ROSTER_GAP (warning; the replay gate still does the blocking).
- Publication is all-or-nothing and idempotent by preview digest. The publish endpoint recomputes the preview and refuses publication if the digest does not match. The raw bytes are stored in `import_audits` beside the snapshot they became.
- Forking (`POST /scenarios/{id}/revisions/{rev}/fork`) swaps one pinned snapshot for the imported one in a *new* revision with expectations carried over. History stays immutable: replaying the old revision still returns its old outcome (asserted by test).
- Public mode mounts none of these routes (`create_app(mode=...)`): the API omits the endpoints as well as their UI controls.

## What exists after milestone 1

- Domain engine with the properties above, 45 tests including Hypothesis property invariants (mypy strict + ruff clean).
- PostgreSQL 17 schema (Alembic), idempotent seed, FastAPI `/api/v1` with error envelope and idempotent replay execution.
- React workbench: scenario library and replay workbench (outcome first; issues, constraints, evidence, manifest in reading order; every finding links to its source row).
- The hero demonstration is walkable end to end in the browser, including the caught regression of the defect configuration.

## Remaining work at milestone completion

All six milestones were complete at the end of this log. The remaining work required credentials and hosting access:

- The live parser evaluation needs an OpenAI key: `uv run python -m flooreplay.eval_notes --live` scores the pinned model on the held-out set within its budget. Until then only the rule baseline's 50% is on record.
- Deployment execution (accounts, DNS) is a configuration task via `render.yaml` + `DEPLOY.md`, not carried out at the time of this log.
- The OpenAI parser path otherwise needs a key to exercise; everything else is fully walkable without one.

## Development commands

- `make seed`: idempotent fixture load
- `make test` / `make lint` / `make typecheck`: required checks
- `make backend-dev` + `make frontend-dev`: run the app
- Backend DB config: `FLOORREPLAY_DATABASE_URL` (default `postgresql+psycopg://localhost:5433/flooreplay`; local Postgres 17 brew service runs on 5433, Docker compose `db` service maps 5433 as well)
