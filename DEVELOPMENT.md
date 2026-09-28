# FloorReplay development log and architecture walkthrough

This document explains what exists, why it is shaped the way it is, and what comes next. It is written for the project owner to retain command of the codebase.

## The one-sentence mental model

A replay is a pure function: `(pinned evidence, pinned configuration) -> structured, inspectable result`. Everything else in the system exists to make that function honest, reproducible, and inspectable.

## Why "pure engine" matters

`backend/src/flooreplay/domain/` contains no database access, no HTTP, no clock reads, no randomness at execution time. Consequences:

- The same inputs always produce the same result (verified by tests: same manifest -> same digests, same proposal).
- Domain blocks (`NEEDS_CONTEXT`) are ordinary return values, not exceptions, so HTTP can treat them as successful executions.
- Tests run in milliseconds without infrastructure; only the API integration tests touch PostgreSQL.

## The three separate axes (never collapse them)

1. **Execution lifecycle**: `RUNNING / COMPLETED / ERRORED / INTERRUPTED` — did the machinery finish?
2. **Domain outcome**: `NEEDS_CONTEXT / CONFLICTING_CONTEXT / NO_FEASIBLE_CANDIDATE / REJECTED_BY_CONSTRAINT / READY_FOR_REVIEW` — what did the evidence and rules conclude?
3. **Expectation verdict**: `PASS / FAIL / NOT_EVALUATED` — did this run behave the way we demand?

A replay that surprises us keeps its actual outcome; it is never relabeled "unexpected". The deliberate defect configuration proves this weekly: it produces `READY_FOR_REVIEW` (its actual outcome) while its expectation fails.

## How a replay executes (engine.py)

```
1. context digest   = SHA-256 over canonical {catalog, snapshots, event, decision_at, target}
2. gate             = is the evidence good enough to act on at all?
3. policy           = rank eligible operators, propose one or abstain
4. validator        = independently re-check the proposal (C01..C12), never trusting the policy
5. outcome          = READY_FOR_REVIEW (all pass) | REJECTED_BY_CONSTRAINT (any fail)
```

### The gate's honesty rules (gate.py)

- Missing evidence is never read as absence. No attendance row means `UNKNOWN`, not absent. No skill record means `UNKNOWN`, not level zero.
- Freshness is measured evidence-time vs the pinned `decision_at`, never `now()` and never upload time.
- Shared problems (stale snapshot, incomplete coverage, roster gaps, contradictions) block every policy: outcome `NEEDS_CONTEXT` or `CONFLICTING_CONTEXT`, and no policy runs.
- Candidate problems (absent, unqualified, occupied, unavailable) exclude that candidate only. A bad record for one operator never blocks a supported proposal for another.
- `NO_FEASIBLE_CANDIDATE` is only ever returned when the pool is *conclusively* excluded. If material unknown/stale evidence remains that could conceal a feasible candidate, the honest answer is `NEEDS_CONTEXT`.

### The policies (policies.py)

- `baseline-v1`: ranks core-eligible candidates but deliberately omits assignment-overlap filtering. Its limitation is labeled everywhere it appears.
- `improved-v1`: filters every supported requirement before ranking.
- Ranking is a transparent tuple: higher skill level, then same-line preference, then operator id. No invented utility weights, no optimality claim.

### The validator (validator.py)

Re-derives all twelve checks from pinned evidence. An unknown operator fails `C01` and makes dependent checks `NOT_EVALUATED` rather than inventing observations. Every FAIL carries an `EvidenceRef` (snapshot id + source row + field), which the UI turns into a clickable chip that opens the snapshot drawer with the row highlighted.

## Immutability and provenance

- Artifacts (catalog revision, snapshots, scenario revisions, expectations) are insert-only. Seeding is content-addressed: if content under a published ID changes, seeding fails loudly instead of silently rewriting history.
- Two digests per attempt: the **context digest** (the facts the decision was made on) and the **manifest digest** (everything pinned: artifacts, configuration, build, expectation).
- Idempotency is a database unique key: same key + same request returns the same attempt; same key + different request returns `409`.

## The synthetic world (fixtures.py)

Kaveri Garments Unit 3, Asia/Kolkata, 2026-09-22. Two lines, 22 operators, 2 styles, 8 operations, 12 named machines. The hero episode: decision 07:58, shift 08:00-16:30, `O117` cannot cover sleeve attach on Line 4 (machine SN-4407). `O204` is the most skilled but occupied on Line 3; `O219` is idle, skilled, same line. Revision 1 pins a stale skill snapshot (45 days); revision 2 pins the corrected one (4 days).

## Milestone 6: verification and presentation (fixtures_eval.py, eval_notes.py, E2E)

The theme: measure honestly, then demonstrate — never the other way round.

- **Held-out note evaluation.** `fixtures_eval.py` pins 16 labeled floor notes written *after* the parser rules were frozen; labels state what a careful human would extract (category, subject operators, operations, uncertainty), including deliberate traps: denied absences, display names instead of ids, a "will cover" operator who must not count as a subject, and a surname-only mention that must stay unresolved. `eval_notes.py` scores any parser against them with per-field accuracy and an exact-match rate. The **offline rule baseline honestly scores 50% exact** (category 62%, subjects 62%, operations 88%, uncertainty 100%): it only sees exact operator ids, so every name-based note fails — documented misses, not hidden ones, and precisely the reason the notes workflow treats parser output as a draft requiring human confirmation.
- **The rupee budget.** The live evaluation charges the pinned model's published per-token price, converted at a rate pinned in code (`INR_PER_USD = 88.0`), and refuses to cross `--budget-inr` (default 500). The guard checks before each case, so the case that crosses the line still counts and its cost is reported; the run ends `BUDGET_EXHAUSTED` with whatever was measured. The offline baseline costs nothing. Running `--live` without a key refuses ("refusing to pretend this is live").
- **End-to-end browser tests.** Ten Playwright specs (`frontend/e2e/`) drive the real app through the whole story: the library, the hero matrix (stale → needs context; corrected → ready proposing O219; baseline → rejected by C07), the later-context review (stale with reason codes; still supported on an identical digest), the notes flow (draft → confirm → fork, plus the manual path), and a full 32-case comparison run asserting the exact totals tiles (32 / 0 / 0 / 0). They found real selector ambiguity on the first pass (a `SCEN-HERO@2` regex also matching revisions 20–28; the note page owns four textboxes) — the fixes are stricter locators, not waits. `make e2e` runs them; `make e2e-install` fetches Chromium.
- **The demonstration script.** `DEMO.md` is a narrated seven-act walkthrough where every step names the principle it demonstrates, with a 5-minute cut for short slots.

## Milestone 5: reliability and public limits (recovery, ratelimit.py, DEPLOY.md)

The theme: the machinery is allowed to fail, never allowed to lie about having run.

- **Startup recovery.** `execute_replay` commits the attempt as `RUNNING` before executing, so a process that dies mid-execution leaves a stuck row. The FastAPI lifespan runs `recover_interrupted` once at boot: `RUNNING` → `INTERRUPTED`, with `completed_at` deliberately left empty (it never completed). Recovery is idempotent, logged, and failure-tolerant — if the database is unreachable at boot, the app still starts and `/health/ready` reports the truth. The library's "latest attempt" summaries already filtered on `COMPLETED`, so interrupted attempts surface only as their honest lifecycle badge, never as an outcome.
- **Public-mode execution limits.** The public demo gets two limits with different mechanisms, both honest about *why*:
  - Comparison execution is **absent** (`POST /api/v1/comparisons` is not registered; reads answer 405). One suite run executes 64 replays — that stays a local-owner action. Saved reports stay viewable everywhere.
  - Single replay executions and review checks are **rate limited** per client (`ratelimit.py`, sliding window, default 20/hour from `FLOORREPLAY_PUBLIC_REPLAYS_PER_HOUR`). The window is in-process memory — documented as the honest trade for free single-instance hosting: it bounds abuse, it is not an accounting system. Rejection is `429 RATE_LIMITED` with `Retry-After`, and the message itself points at the saved-report fallback.
- **The saved-report fallback.** `GET /api/v1/replays/latest?scenario_id=&scenario_revision=&configuration_id=` returns the most recent `COMPLETED` attempt for an exact selection. The workbench renders it with a "Saved report" badge and an explicit banner: *loaded from history — not a fresh execution*. A saved report is always labeled; the UI never lets history impersonate a run.
- **Capabilities tell the truth.** `/capabilities` now reports the limits (`replays_per_hour_per_client`, `comparison_execution: local_only`), and the frontend renders from that instead of hardcoding: the comparison screen shows an owner-only notice instead of a button that would 405.
- **Deployment.** `render.yaml` (backend web service + frontend static site, free tier) with Neon's free PostgreSQL as the external database; `DEPLOY.md` has the full walk-through, including CORS via `FLOORREPLAY_CORS_ORIGINS` and `VITE_API_BASE` for the deployed frontend (the dev proxy still serves `/api` locally).

## Milestone 4: notes, later-context review, portable reports (parsing.py, Notes screen, review panel)

The theme: the model (or any parser) may *draft*, but only a human *confirms*, and only the confirmation writes history.

- **The parser boundary.** `parsing.py` exposes one interface with two implementations. `RuleBaselineParser` is offline and deterministic (regex extraction of the operator mention, operation words, unavailability phrasing, uncertainty words) and is the demo default — no API key needed. `OpenAIStructuredParser` calls the pinned `gpt-4.1-mini-2025-04-14` through raw `httpx` (no SDK, so no hidden retries), enforces the 2000-character cap, a 15-second monotonic deadline, and at most one retry; any failure raises `ParserUnavailable`. `get_parser(api_key)` picks; the API response always names the parser kind and live status so the UI can say "no API key configured" instead of pretending.
- **Drafts are never events.** A parse returns a `DraftExtraction` (operator, operation, moment, uncertainty flags) plus mention resolutions. Resolution is exact operator id or documented alias only; an ambiguous mention keeps its candidate list and stays ambiguous — ambiguity is data, not an error to suppress. Nothing persists until confirm.
- **Confirm forks.** `POST /notes/confirm` writes the immutable event and forks a new scenario revision with expectations carried over (`SCEN-HERO@28` in the demo database). The manual fallback radio records the event without any parser output; the parser call is audited either way (`parser_calls`: note digest, kind, model, latency, result or error).
- **Later-context review answers one question**: is the proposal I already have still supported by a *later, explicitly-pinned* context? `review_check(original_replay_id, target_scenario_id, target_revision)` re-runs the gate on the target revision's pinned context. Blocked → `BLOCKED_CONTEXT` with the issues. Otherwise compare the canonical context digests: identical → `STILL_SUPPORTED`; different → `STALE_RECOMMENDATION` with reason codes (`EVENT_CHANGED`, `DECISION_TIME_CHANGED`, `EVIDENCE_CHANGED`) and a recursive changed-path diff (`snapshots[4].rows[31].assessed_at`), element-wise through lists as well as dicts. The original replay is never altered.
- **The three review fixtures** (`SCEN-REVIEW-LATER` revs 1-3) are engine-verified to produce the three outcomes: the original 07:58 decision; refreshed evidence and plan revision C at 08:10 (stale); stale exports at 08:10 (blocked). All three are walkable from the workbench panel.
- **Portable reports.** `/api/v1/replays/{id}/export` returns the attempt's request, result, and both digests as one JSON document.
- **Bug found and fixed during the build:** the changed-path diff originally treated snapshot lists as atomic values; it now recurses element-wise with `[index]` paths, and the reason-code mapper strips `[...]` suffixes before classifying the path head.

## Milestone 3: the operational suite and comparison (fixtures_suite.py, Comparison screen)

- **32 named cases** (`fixtures_suite.py`), each derived from the hero episode by a targeted mutation with an explicit defect statement and per-configuration demands. The cases were authored against the engine and validated case-by-case before any persistence was wired: 0 unintended mismatches, and exactly 3 intended defect-config failures (B1/F1/F4, the stale-evidence regressions the defect exists to exhibit).
- **Expectations are demands, not observations.** The baseline configuration legitimately fails healthy-coverage demands (its overlap blind spot is documented), so its demands are written as "REJECTED by C07"; the comparison therefore compares each config against its own pinned demands, and pass/fail is judgment, not taste.
- **Comparison execution** (`run_comparison`): sequential, at most the suite's items, a monotonic 30-second budget checked between cases, results persisted as one report with a manifest digest and database-enforced idempotency. Classifications: UNCHANGED_PASS / FIXED / REGRESSION / UNCHANGED_FAIL; behavior changes (both pass, different decisions) are reported separately, never folded into pass/fail. An interrupted suite stores INTERRUPTED and can never pass overall.
- **Two engine gaps found by authoring the suite**, both fixed and now covered: (1) a recorded-unusable designated machine now conclusively blocks at the gate (NO_FEASIBLE_CANDIDATE with TARGET_MACHINE_UNUSABLE evidence) instead of waiting to fail C06 after a wasted proposal; (2) conclusive gate issues are no longer dropped from the result's issue list.
- **Honesty notes carried into the fixtures**: operators without a skill row are MATERIAL unknowns, so "everyone excluded" cases only become conclusive NO_FEASIBLE_CANDIDATE with a complete skill matrix; one operator's stale/future/unknown evidence never blocks a supported candidate elsewhere in the pool (cases E1/E2, C4).

## Milestone 2: the import pipeline (importing.py, Imports screen)

The import flow turns an imperfect external export into immutable evidence without ever lying about what it received:

- **Fixed, documented source profiles** (`attendance-v1`, `skills-v1`) declare required columns, accepted codes, and the natural key. Extra columns are allowed and listed as ignored.
- **Normalization is recorded, not silent**: `P` -> PRESENT, `A` -> ABSENT, blank -> UNKNOWN (never absent), naive timestamps -> Asia/Kolkata. Every applied rule appears on the row in the preview, and the original cells are preserved next to the normalized values.
- **Row-level diagnostics** carry a code, severity, column, and raw value: MISSING_REQUIRED_CELL, UNSUPPORTED_VALUE, INVALID_TIMESTAMP, UNKNOWN_OPERATOR/OPERATION, DUPLICATE_NATURAL_KEY, FORMULA_LIKE_CELL (warning), ROSTER_GAP (warning; the replay gate still does the blocking).
- **Publication is all-or-nothing and idempotent** by preview digest. The publish endpoint recomputes the preview and refuses if the digest does not match (nothing is published on the quiet). The raw bytes land in `import_audits` beside the snapshot they became.
- **Forking** (`POST /scenarios/{id}/revisions/{rev}/fork`) swaps one pinned snapshot for the imported one in a *new* revision with expectations carried over. History stays immutable: replaying the old revision still returns its old outcome (asserted by test).
- **Public mode mounts none of these routes** (`create_app(mode=...)`): hiding buttons is not the mechanism, absent endpoints are.

## What exists after milestone 1

- Domain engine with the properties above, 45 tests including Hypothesis property invariants (mypy strict + ruff clean).
- PostgreSQL 17 schema (Alembic), idempotent seed, FastAPI `/api/v1` with error envelope and idempotent replay execution.
- React workbench: scenario library and replay workbench (outcome first; issues, constraints, evidence, manifest in reading order; every finding links to its source row).
- The hero demonstration is walkable end to end in the browser, including the caught regression of the defect configuration.

## What is deliberately not built yet

The six milestones are complete. The remaining steps are human ones, not code:

- The **live** parser evaluation needs an OpenAI key: `uv run python -m flooreplay.eval_notes --live` scores the pinned model on the held-out set within its budget. Until then only the rule baseline's honest 50% is on record.
- **Deployment execution** (accounts, DNS) is a fill-in-the-variables exercise via `render.yaml` + `DEPLOY.md`, not yet carried out.
- The OpenAI parser path otherwise needs a key to exercise; everything else is fully walkable without one.

## Dev commands

- `make seed` — idempotent fixture load
- `make test` / `make lint` / `make typecheck` — all must stay green
- `make backend-dev` + `make frontend-dev` — run the app
- Backend DB config: `FLOORREPLAY_DATABASE_URL` (default `postgresql+psycopg://localhost:5433/flooreplay`; local Postgres 17 brew service runs on 5433, Docker compose `db` service maps 5433 as well)
