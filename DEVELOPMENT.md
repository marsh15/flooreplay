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

- AI note extraction with confirmation workflow and manual fallback (milestone 4)
- Suite execution + baseline comparison report (milestone 3)
- Later-context review checks (milestone 4)
- Interruption recovery, public-mode limits, deployment (milestone 5)
- The 32-case operational suite grows with milestone 3; today the expectation machinery is proven on the hero scenarios.

## Dev commands

- `make seed` — idempotent fixture load
- `make test` / `make lint` / `make typecheck` — all must stay green
- `make backend-dev` + `make frontend-dev` — run the app
- Backend DB config: `FLOORREPLAY_DATABASE_URL` (default `postgresql+psycopg://localhost:5433/flooreplay`; local Postgres 17 brew service runs on 5433, Docker compose `db` service maps 5433 as well)
