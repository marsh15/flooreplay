# FloorReplay

A workbench for testing whether operational recommendations remain trustworthy when source data, decision rules, or software versions change.

FloorReplay reconstructs a bounded manufacturing situation from immutable evidence, decides whether the evidence supports a decision, runs a recommendation policy, validates its proposal independently, and compares the result against explicit expectations. The workflow is deliberately narrow: an operator cannot cover a planned sewing operation; can an available, qualified operator cover that vacant slot on its designated machine? The application proposes coverage for human review. It never writes to an external system.

All factory data is synthetic.

> FloorReplay is an unofficial engineering exploration using synthetic data. It is not affiliated with Genorai and has not been validated in a real factory.

## The hero demonstration

1. **Stale evidence blocks.** Scenario `SCEN-HERO@1` pins a skill snapshot assessed 45 days before the decision. The context gate returns `NEEDS_CONTEXT`; no policy runs.
2. **Correction creates a new revision.** `SCEN-HERO@2` pins a fresh skill snapshot. The historical revision is unchanged.
3. **Baseline proposes and is rejected.** The baseline policy (deliberately overlap-blind, and labeled as such) proposes `O204`, who is occupied on Line 3. Independent validation rejects the proposal with `C07` and links the overlapping assignment row.
4. **Improved policy proposes.** `O219` is idle, skilled, present; every constraint check passes; outcome `READY_FOR_REVIEW`.
5. **A deliberate regression is caught.** Configuration `CFG-DEFECT-SKILLFRESH` carries a 400-day skill-freshness budget. It lets stale evidence through the gate; the pinned expectation fails with visible reasons.

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

Shortcuts from the repo root: `make seed`, `make test`, `make lint`, `make typecheck`, `make verify`.

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
  fixtures.py        the synthetic factory and the hero episode
  models.py          ORM: immutable artifacts + replay attempts
  seeding.py         idempotent, content-addressed seeding
  service.py         execution orchestration, idempotency, manifests
  api.py             HTTP surface and error envelope
frontend/src/
  lib/api.ts         typed API client (hand-written; OpenAPI generation planned)
  pages/Library.tsx  scenario library
  pages/Workbench.tsx  replay workbench
```

## Imports (local owner)

The Imports screen (`/imports`, mounted only in local mode) follows: select a documented source profile, upload or load a curated example, inspect the normalized preview with row-level diagnostics, publish the exact preview as an immutable snapshot, then fork a scenario onto it.

- Profiles: `attendance-v1` (P/A/blank codes; blank means UNKNOWN, never absent) and `skills-v1` (levels 1-4). Naive timestamps are interpreted as Asia/Kolkata per the documented profile rule.
- Publication is all-or-nothing: any blocking issue (unsupported value, invalid timestamp, duplicate natural key, unknown entity, missing cell) refuses the publish. Raw bytes and their digest are retained in an audit table.
- Forking creates a new scenario revision with the imported snapshot; the original revision and every historical replay stay untouched.
- The curated examples include a successful import and a rejected one (five defect kinds in six rows).

## The 32-case operational suite and comparison report

`SUITE-OPS-V1` pins 32 named cases across six categories (deterministic selection, missing/stale/incomplete evidence, conflicting facts, candidate and resource constraints, abstention vs insufficient context, historical replay). Every case states the defect it would catch and carries per-configuration expectations. The Comparison screen executes the suite under two configurations and reports actual transitions:

- baseline vs improved: 32 unchanged pass (the baseline meets its documented limitation demands; behavior differences are shown separately as "behavior changed")
- improved vs the demonstration defect: 29 unchanged pass, **3 regressions** (the relaxed-freshness config lets stale evidence through on exactly the three stale-evidence cases), each with its failure reasons

An interrupted suite can never receive an overall passing verdict; comparison reports are persisted with a manifest digest and idempotency keys.

## Status and honest limits

Milestones 1-3 of 6 are complete: contracts, engine, persistence, seed, replay API, library and workbench screens, the CSV import/fork workflow, and the 32-case suite with comparison report, all walkable in the browser. Not yet built: AI note extraction, later-context review, public-mode execution limits, deployment. See `DEVELOPMENT.md` for the milestone log and architecture walkthrough.
