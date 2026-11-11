# FloorReplay

**Should we accept this urgent order?** FloorReplay helps a knit-garment exporter in Tiruppur or Coimbatore answer that question. It replays an order decision as it was known at any chosen time, shows the arithmetic behind fabric, trims, capacity and approval checks, says plainly when the evidence cannot be trusted, and leaves the final call and its reason to a person.

> **Status.** A complete, tested prototype on **synthetic data**. There has been no factory pilot and no practitioner interview, the default policy values are unvalidated drafts, and no operational benefit is claimed. See [what this is not](#what-this-is-not).

## Try it

Open the app (see [Run locally](#run-locally)); no account is needed for the public demo, a fictional factory called "Tiruppur Knits (synthetic)".

1. On **Order decisions**, open **POLO-221**. The gate is READY and the engine recommends ACCEPT. Each constraint card shows its steps; select a fact id to see its source, both clocks and any correction chain.
2. Choose **Knowledge timeline**. Move the slider back: at 11:00 IST a dyeing-house note says 1,200 m of lot L-221 failed shade while the ERP still shows 4,000 m, so the gate is CONFLICTING and the engine asks for review. At 12:30 QA records 2,800 m usable and the gate turns READY again.
3. Open the other orders: POLO-222 needs capped overtime (accept with conditions), POLO-223 is short of fabric (needs review; split shipments are not built), POLO-224 has a stale trims sheet, POLO-225 is over the approval limit.
4. Open the **Replay lab**. A stored run compares a candidate policy with the current one over nine frozen past cases: one is fixed, one regresses. Adoption needs a complete stored run and a written acknowledgement for the regression, and only a workspace owner can do it.

To record decisions or adopt a policy yourself, sign in as an owner and load the demo into your private workspace: `python -m flooreplay decisions-demo --owner <username>`.

## How it decides

- **Facts with two clocks.** Every import row becomes an immutable fact with `valid_from` (when it was true) and `known_at` (when the system learned it). Corrections supersede; nothing is overwritten or deleted, and the database enforces it.
- **A gate before arithmetic.** READY, STALE, INCOMPLETE or CONFLICTING, with every finding kept. Freshness is judged at the cutoff, never the wall clock.
- **Six constraints.** Fabric per colour, safety stock, trims per item, sewing capacity, capped overtime and the approval threshold return PASS, FAIL or NOT_EVALUATED with their ordered steps.
- **A recommendation, not a decision.** ACCEPT, ACCEPT_WITH_CONDITIONS, DECLINE or NEEDS_REVIEW. Anything uncertain needs review. A person records the final outcome and a reason; overrides are kept.
- **Replay.** `(facts known at a cutoff, policy, engine version) → decision` is a pure function with a stable digest.
- **No model in the decision.** Optional note extraction only proposes structured signals; deterministic checks verify each one and failures go to review.

Read [PRODUCT.md](PRODUCT.md) for scope and [ARCHITECTURE.md](ARCHITECTURE.md) for modules and guarantees.

## What is built

| Area | State |
| --- | --- |
| Decision engine (facts, snapshots, gate, constraints, recommendation, replay, policy comparison) | Built and tested, including property tests |
| Append-only store, evaluations, human records, regression runs, owner-only adoption | Built and tested against PostgreSQL |
| CSV imports (stock, trims, capacity, supplier updates, orders with bills of materials, notes) | Preview with explicit mapping, then publish; ambiguous dates, thousands separators and unknown units are blocked |
| Order workbench, knowledge timeline, replay lab, review queue, imports | Built; the public demo is read-only |
| Note extraction (English, Tamil, Tanglish) with deterministic checks | Built and tested with mock providers; **not reachable from the web app** |
| Note benchmark | A 100-note draft corpus and offline scorer; **labels are unreviewed drafts** |

## What this is not

- Not validated with factory staff. The constraint list and defaults come from [discovery notes](docs/v2/discovery.md) that no practitioner has reviewed.
- Not a source of accuracy claims. The note corpus labels have not been reviewed by a Tamil speaker, and no model has been scored against them.
- Not a split-shipment planner. A material fabric or trims shortfall asks for review.
- Not connected to live ERP systems. Evidence arrives as CSV files.
- Not rate limited for anonymous replays. Anyone can request replays of the public demo at any cutoff; a deployment that exposes real data must not use this configuration.

## Run locally

With Docker Desktop or Docker Engine:

```sh
docker compose up --build --wait
```

Open [the application](http://localhost:5174). The API and database bind to loopback ports 8001 and 5434. Startup runs migrations and seeds the database, including the demo; repeating it creates nothing new.

Create accounts with prompted passwords:

```sh
docker compose exec api python -m flooreplay account-create owner --role owner
docker compose exec api python -m flooreplay decisions-demo --owner owner
```

For development use Python 3.12+, uv, Node 22.12+ and pnpm 10.30.0, with PostgreSQL that provides pgvector:

```sh
cd backend
cp .env.example .env
uv sync --frozen
uv run alembic upgrade head
uv run python -m flooreplay seed
uv run uvicorn flooreplay.api:app --port 8000
```

In a second shell: `cd frontend && pnpm install --frozen-lockfile && pnpm dev`.

## Verification

```sh
make test-db                                    # disposable PostgreSQL on port 5435
export FLOORREPLAY_TEST_DATABASE_URL=postgresql+psycopg://flooreplay_test@localhost:5435/flooreplay_release_test
export FLOORREPLAY_DATABASE_URL=$FLOORREPLAY_TEST_DATABASE_URL
make verify                                     # lint, types, backend tests
make dataset-verify                             # v1 dataset and the decision cases
make e2e                                        # browser specs (backend on :8000, seeded)
```

Test database names must end in `_test`. [RELEASE_STATUS.md](RELEASE_STATUS.md) records the latest results with their counts and what remains unverified.

## Earlier versions

Version 1, shortfall investigations for a sewing line, is still in the app under "Earlier versions" and gets no new features. Its documents are in [docs/v1](docs/v1/), including its [product guide](docs/v1/PRODUCT.md), [release evidence](docs/v1/RELEASE_STATUS.md) and [demo guide](docs/v1/DEMO.md). The archived operator-coverage product is tagged `coverage-v1`.

## Configuration and deployment

`FLOORREPLAY_ANTHROPIC_API_KEY` and `FLOORREPLAY_OPENAI_API_KEY` are optional and server-side only; nothing in the order decision screens calls a provider. Seeding, migrations and the demo never make paid calls.

See [DEPLOY_VERCEL.md](DEPLOY_VERCEL.md) for Vercel, Render and Neon and [DEPLOY.md](DEPLOY.md) for containers, backups and recovery. The [v2 plan](docs/v2/PLAN.md) records the approved design and its later changes are in [the changelog](docs/v2/changelog.md).
