# FloorReplay operator-coverage archive

This document records the original operator-coverage workbench. Its commands, paths, deployment notes and milestone results describe that version.

The workbench tests whether operational recommendations remain trustworthy when source data, decision rules or software versions change.

FloorReplay reconstructs a bounded manufacturing situation from immutable evidence, decides whether the evidence supports a decision, runs a recommendation policy, validates its proposal independently, and compares the result against explicit expectations. The workflow covers a planned sewing operation whose assigned operator is unavailable. It checks whether an available, qualified operator can cover the slot on its designated machine. The application proposes coverage for human review. It never writes to an external system.

All factory data is synthetic. Real factory validation remains pending.

## The hero demonstration

1. Stale evidence blocks. Scenario `SCEN-HERO@1` pins a skill snapshot assessed 45 days before the decision. The context gate returns `NEEDS_CONTEXT`; no policy runs.
2. Correction creates a new revision. `SCEN-HERO@2` pins a fresh skill snapshot. The historical revision is unchanged.
3. Baseline proposes and is rejected. The baseline policy (overlap-blind, and labeled as such) proposes `O204`, who is occupied on Line 3. Independent validation rejects the proposal with `C07` and links the overlapping assignment row.
4. Improved policy proposes. `O219` is idle, skilled, present; every constraint check passes; outcome `READY_FOR_REVIEW`.
5. A deliberate regression is caught. Configuration `CFG-DEFECT-SKILLFRESH` carries a 400-day skill-freshness budget. It lets stale evidence through the gate; the pinned expectation fails with visible reasons.

## Stack

| Layer | Choice |
|---|---|
| Domain engine | Pure Python 3.12, Pydantic v2; no IO, no clock, no database |
| API | FastAPI, `/api/v1` |
| Persistence | PostgreSQL 17, SQLAlchemy 2, Alembic |
| Frontend | React, TypeScript, Vite, Tailwind CSS v4, shadcn/ui, TanStack Query |

## Run it

Prerequisites: Python 3.12+ with [uv](https://docs.astral.sh/uv/), Node with pnpm, PostgreSQL (local or Docker).

```bash
# database (either start the compose service on :5433, or point FLOORREPLAY_DATABASE_URL at your own)
docker compose up -d db

# backend
cd backend
cp .env.example .env           # adjust the URL if needed
uv sync
uv run alembic upgrade head
uv run python -m flooreplay seed   # idempotent; run twice, second run changes nothing
uv run uvicorn flooreplay.api:app --port 8000

# frontend (another shell)
cd frontend
pnpm install
pnpm dev                       # http://localhost:5173, proxies /api to :8000
```

Shortcuts from the repo root: `make seed`, `make test`, `make lint`, `make typecheck`, `make verify`. Free-hosting deployment (Neon + Render) is preconfigured in `render.yaml` and walked through in `DEPLOY.md`.

## Repository map

```
backend/src/flooreplay/
  domain/            the pure replay engine (the point of the project)
    types.py         contracts: catalog, snapshots, outcomes, issues, constraints
    intervals.py     half-open [start, end) semantics
    hashing.py       canonical JSON + SHA-256 digests (context, manifest)
    gate.py          evidence adequacy: shared + candidate-specific checks
    policies.py      baseline-v1 / improved-v1 ranking and selection
    validator.py     independent C01..C12 constraint validation
    evaluation.py    expectation verdicts
    engine.py        gate -> policy -> validator orchestration
  fixtures.py        the synthetic factory, hero episode, later-review revisions
  fixtures_suite.py  the 32-case operational suite
  importing.py       documented CSV profiles, preview diagnostics, snapshot build
  parsing.py         note draft extraction: rule-baseline + pinned OpenAI parser
  models.py          ORM: immutable artifacts + replay attempts + audits
  seeding.py         idempotent, content-addressed seeding
  service.py         execution, comparison, review checks, idempotency, export
  api.py             HTTP surface and error envelope (mode-scoped routes)
frontend/src/
  lib/api.ts         typed API client (hand-written; OpenAPI generation planned)
  pages/Library.tsx     scenario library
  pages/Workbench.tsx   replay workbench + later-context review
  pages/Comparison.tsx  suite comparison report
  pages/Imports.tsx     CSV import / publish / fork (local mode)
  pages/Notes.tsx       floor note parse -> confirm -> fork (local mode)
```

## Imports (local owner)

In the Imports screen (`/imports`, mounted only in local mode), select a documented source profile, upload or load a curated example, inspect the normalized preview with row-level diagnostics, publish the exact preview as an immutable snapshot, then fork a scenario onto it.

- Profiles: `attendance-v1` (P/A/blank codes; blank means UNKNOWN, never absent) and `skills-v1` (levels 1-4). Naive timestamps are interpreted as Asia/Kolkata per the documented profile rule.
- Publication is all-or-nothing: the application refuses publication if it finds an unsupported value, invalid timestamp, duplicate natural key, unknown entity or missing cell. Raw bytes and their digest are retained in an audit table.
- Forking creates a new scenario revision with the imported snapshot; the original revision and every historical replay stay untouched.
- The curated examples include a successful import and a rejected one (five defect kinds in six rows).

## The 32-case operational suite and comparison report

`SUITE-OPS-V1` pins 32 named cases across six categories (deterministic selection, missing/stale/incomplete evidence, conflicting facts, candidate and resource constraints, abstention vs insufficient context, historical replay). Every case states the defect it would catch and carries per-configuration expectations. The Comparison screen executes the suite under two configurations and reports actual transitions:

- baseline vs improved: 32 unchanged pass (the baseline meets the expectations for its documented limitations; behavior differences are shown separately as "behavior changed")
- improved vs the demonstration defect: 29 unchanged pass, 3 regressions (the relaxed-freshness config lets stale evidence through on exactly the three stale-evidence cases), each with its failure reasons

An interrupted suite can never receive an overall passing verdict; comparison reports are persisted with a manifest digest and idempotency keys.

## Floor notes, later-context review, and portable reports

Floor notes (`/notes`, local mode only) produce a draft from a supervisor's free-text note. Human confirmation creates the evidence:

1. Paste a note (max 2000 characters) and parse it. The UI states which parser ran and whether it is live; the offline `rule-baseline` parser is the demo default when no OpenAI key is configured.
2. The parse returns a draft: candidate operator, operation, moment, uncertainty flags, and mention resolutions. Mentions resolve by exact operator id or documented alias only. Ambiguous mentions retain their candidate lists.
3. Confirming the draft creates an immutable event and forks a new scenario revision carrying the expectations; every historical revision and replay is untouched. A manual fallback lets you record the event without any parser output at all.
4. Every parser call is audited (raw note digest, parser kind, model, latency, result or error).

The optional OpenAI parser is pinned to `gpt-4.1-mini-2025-04-14` with a 2000-character cap, a 15-second deadline, and at most one retry; timeouts surface as `ParserUnavailable`, never as a silent fallback. The demo needs no API key.

The later-context review panel checks whether later, explicitly pinned evidence still supports an existing proposal. Pick any later scenario revision and run the check. The original replay is never altered, and the outcome is one of three:

- `still supported`: the later context's canonical digest is identical; the pinned facts are unchanged.
- `stale recommendation`: the digest differs; reason codes (`EVENT_CHANGED`, `DECISION_TIME_CHANGED`, `EVIDENCE_CHANGED`) plus an expandable list of canonical changed paths (down to individual rows and fields) show which rows and fields changed.
- `blocked context`: the gate itself now blocks; the blocking issues are listed.

The seeded `SCEN-REVIEW-LATER` revisions (original 07:58 decision, refreshed evidence at 08:10, stale exports at 08:10) demonstrate all three outcomes.

Every replay attempt has a portable JSON report at `/api/v1/replays/{id}/export` for offline review. It contains the request, result and both digests.

## Reliability and the public demo

- A replay attempt is persisted as `RUNNING` before execution starts. If the process dies mid-run, startup recovery marks it `INTERRUPTED`; execution did not finish. Interrupted attempts can never receive a passing verdict.
- The public demo keeps reads open but bounds execution: suite/comparison runs are local-owner only (absent endpoint), and single replays are rate limited per client (`429` with `Retry-After`).
- Each selection's most recent completed report is available at `/api/v1/replays/latest` and in the workbench, labeled "Saved report" to distinguish it from a fresh execution.
- `/api/v1/capabilities` reports the active limits so the UI uses the active configuration.

## Verification and demonstration

- Parser evaluation on held-out notes: `make eval-notes` scores the offline rule baseline against 16 labeled floor notes it has never seen (it scores 50% exact; name-based mentions are its documented blind spot, which is why notes require human confirmation). With an API key, `uv run python -m flooreplay.eval_notes --live` scores the pinned OpenAI model within a hard rupee budget (default ₹500) and stops with `BUDGET_EXHAUSTED` rather than overspending.
- End-to-end browser tests: `make e2e` (after `make e2e-install`) drives all ten flows in real Chromium: the hero matrix, later-context review, notes-to-fork, and a full 32-case comparison run.
- `DEMO.md` is a narrated seven-act demonstration script in which every step names the principle it demonstrates.

## Completion and remaining work

All six milestones are complete: contracts, engine, persistence, seed, replay API, library and workbench screens, the CSV import/fork workflow, the 32-case suite with comparison report, floor-note parsing with confirmation, later-context review, portable replay reports, interruption recovery, public-mode execution limits, deployment configuration, held-out parser evaluation, end-to-end browser tests, and the demonstration script. Each workflow can be demonstrated in the browser. The remaining steps require configuration and hosting access: supply an OpenAI key to score the live parser within its budget, and execute the free-hosting deployment via `DEPLOY.md`. See `DEVELOPMENT.md` for the milestone log and architecture walkthrough.
