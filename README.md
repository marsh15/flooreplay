# FloorReplay

FloorReplay reconstructs a sewing-line incident from the operational evidence available at a selected cutoff. Production metrics, hypotheses, precedents and recovery proposals keep their input references. New evidence creates a new revision; earlier reports retain their original meaning. All factory data is synthetic.

The current release adds authenticated owner/reviewer accounts, OpenAI generation, pgvector hybrid search, a persistent ₹500 allowance, durable request recovery and deployment packaging. Live OpenAI smoke and pilot checks pass; the locked evaluation stopped at a validation failure. The supplied review reports that the public site loaded incidents and ran deterministic analysis. This repository does not yet contain dated acceptance evidence for authenticated hosted flows. Independent human claim review remains pending.

## Run the application

With Docker Desktop or Docker Engine running:

```sh
docker compose up --build --wait
```

Open [the local app](http://localhost:5174). Compose uses PostgreSQL with pgvector on loopback port 5434 and the API on port 8001. Startup migrates and seeds idempotently and makes no paid calls.

Create individual accounts with prompted passwords:

```sh
docker compose exec api python -m flooreplay account-create owner --role owner
docker compose exec api python -m flooreplay account-create reviewer --role reviewer
```

Anonymous visitors can inspect incidents, use lexical search and run bounded deterministic analysis. Reviewers can request AI, use hybrid retrieval, export reports and submit/review proposals. Owners can also import records, publish/index a corpus and manage accounts. Sign-in tokens live only in browser memory and expire after eight hours. Reloading requires signing in again. Account disabling revokes access immediately.

For an existing local PostgreSQL installation, use Python 3.12+, uv, Node 22 and pnpm 10.30:

```sh
cd backend
cp .env.example .env
uv sync --frozen
uv run alembic upgrade head
uv run python -m flooreplay seed
uv run python -m flooreplay account-create owner --role owner
uv run uvicorn flooreplay.api:app --port 8000
```

In another shell, run `cd frontend && pnpm install --frozen-lockfile && pnpm dev`. PostgreSQL must provide the vector extension. For online hosting, follow [DEPLOY_VERCEL.md](DEPLOY_VERCEL.md): Vercel frontend, Render API and Neon database. See [DEPLOY.md](DEPLOY.md) for local verification, backup and rollback.

## Investigate the featured incident

Open **Delayed start on sewing line S4**. Revision 1 records 160 planned versus 87 good units at the 11:00 cutoff. The maintenance note entered at 11:20 is unavailable. Revision 2 adds that note and a corrected machine observation. Evidence chips open the exact source record. Metrics include their unit, formula, interval and source references.

Target pressure uses the observation watermark and explicitly labeled elapsed-time assumptions. Missing production buckets are unknown rather than zero. A chronological sequence and a retrieved historical cause cannot establish the current cause. Competing corrections and contradictory observations remain visible.

Sign in to submit a proposal and review it with a rationale. The server records your account identity and rejects a stale revision. Approval is a FloorReplay review record; there is no factory-system execution.

## OpenAI configuration and spending

Set `FLOORREPLAY_OPENAI_API_KEY` in the backend environment. The generation default is `gpt-4.1-mini-2025-04-14`; embeddings use `text-embedding-3-small` with 512 dimensions. Responses use structured contracts and `store=false`. The SDK makes no automatic retries. Every generation, repair, embedding and live evaluation reserves allowance before contacting the provider.

The PostgreSQL ledger has a fixed ₹500 ceiling, initially allocated as ₹100 development, ₹200 indexing/evaluation, ₹100 reviewer use and ₹100 buffer. At most two provider operations run concurrently. Timed-out or interrupted calls retain uncertain reservations. Repeating a request identity returns its recorded result instead of initiating another paid call.

Pricing is versioned using the official rates checked on September 30, 2026: $0.40/$1.60 per million generation input/output tokens and $0.02 per million embedding tokens. The default INR accounting conversion is a configurable fixed 90 INR/USD assumption. Reconcile provider charges and applicable fees separately; the ledger is an application allowance. Source pages: [generation model](https://developers.openai.com/api/docs/models/gpt-4.1-mini), [embedding model](https://developers.openai.com/api/docs/models/text-embedding-3-small).

Publish a cutoff-bound corpus without spending, then explicitly index it:

```sh
cd backend
uv run python -m flooreplay corpus-publish release-v1 --cutoff 2026-09-30T00:00:00+00:00 --owner owner
uv run python -m flooreplay usage
uv run python -m flooreplay corpus-index release-v1 --owner owner
```

Hybrid search uses exact cosine ranking and PostgreSQL lexical ranking, with up to 20 candidates each, reciprocal rank fusion constant 60 and five distinct incidents. The exact corpus manifest excludes the current lineage, unavailable revisions and evaluation-only cases. Seeding and migrations never index a corpus.

Generation has task-specific contracts for investigations, answers, summaries, recovery and note assertions. The application renders selected metric values; generated prose cannot invent quantities. Citation validation proves source membership, while semantic support still requires human review. Historical Qwen artifacts remain labeled with their original provider and review records. They do not measure OpenAI quality. Active Qwen/Ollama clients, weights and the separate worker requirement have been removed.

## Dataset and verification

The release contains 180 additional episodes, with 120 historical, 30 development and 30 locked investigations across 24 evidence structures. Hidden synthetic truth and labels are separate from runtime observations. All 60 investigation cases pass frozen arithmetic and evidence-structure checks. Template/lineage leakage checks pass; independent semantic support and paraphrase review are pending. This is generator-author-reviewed synthetic material, with no manufacturing-expert validation.

Tests use a separate database whose name ends in `_test`. Never point destructive test setup at the working database. CI supplies no provider key. It runs backend lint/types/tests, frontend lint/build, dependency audit, OpenAPI generation, saved-artifact consistency, browser tests and deployment configuration validation.

```sh
make verify
make dataset-verify
make e2e
```

See [RELEASE_STATUS.md](RELEASE_STATUS.md) for measured evidence and remaining release gates. The budgeted live evaluation command runs smoke, pilot and locked stages in order, stops on a blocking defect and preserves measured denominators:

```sh
cd backend
uv run python -m flooreplay eval-openai --owner owner --stage smoke
uv run python -m flooreplay eval-openai --owner owner --stage pilot
uv run python -m flooreplay eval-openai --owner owner --stage locked
```

Run the same progression with `--retrieval-mode hybrid --corpus release-v1` and output paths such as `evaluation/hybrid/openai-smoke.json`, `evaluation/hybrid/openai-pilot.json` and `evaluation/hybrid/openai-locked.json`. Each stage checkpoints its request identities before spending. Repeating the same command resumes the checkpoint and cannot silently repeat a billed request. A completed five-case smoke is required before the pilot, and a completed ten-case pilot before locked evaluation. Human claim-support labels must attach to the actual new responses. A valid schema does not establish semantic accuracy.

`make export-demo` generates the saved frontend bundles from backend reports through one command. `make generate-api` regenerates frontend request types from OpenAPI. The legacy coverage workflow is preserved in [COVERAGE_ARCHIVE.md](COVERAGE_ARCHIVE.md).

Human support annotations use `POST /api/v1/ai-runs/{run_id}/claim-review` with an authenticated session, a canonical claim path such as `claims.0`, `supported`, `rationale` and an idempotency key. Each annotation records the actor and exact output digest separately from the immutable draft. Current-provider metrics read durable evaluation runs and their annotations; independent dataset semantic review remains a separate pending gate.

## Improvement work

The product focuses on a supervisor investigating a sewing-line shortfall and coordinating the next checks. The September 30 improvement adds guided entry, a curated incident library with filters and pagination, separate status labels, revision comparisons, state-aware next checks, authenticated claim annotations and printable deterministic reports. Assigned tasks, response tracking and spreadsheet column mapping remain follow-up work. [PRODUCT.md](PRODUCT.md) states the workflow, [DEMO.md](DEMO.md) gives the current walkthrough, and [IMPROVEMENT_PLAN.md](IMPROVEMENT_PLAN.md) turns the supplied 36 ideas into deliverables and evidence gates. [Practitioner interviews](docs/practitioner-interview.md) and the [comparative pilot template](docs/comparative-pilot.md) are ready to use. They contain no interview findings or measured customer benefit.

The improvement pass passes 178 backend tests, Ruff, mypy, frontend lint and build. Browser evidence covers 33 scenarios across a full run with 31 passing and focused reruns after two obsolete test assumptions were corrected. The final focused six-scenario run passes. OpenAI browser checks use simulated transport; these checks made no paid calls and do not establish semantic support or hosted acceptance. See [RELEASE_STATUS.md](RELEASE_STATUS.md) for the exact verification scope.
