# FloorReplay

FloorReplay is a synthetic manufacturing incident workbench. A production lead can open a delayed sewing line, see recorded output against its pinned baseline, inspect a cutoff-aware timeline, review qualified explanations, find older cases, and record a human review of a proposed next check. It never executes a factory change.

The previous operator-coverage application remains available under **Coverage archive** and in the `coverage-v1` Git tag. Its detailed documentation is in [COVERAGE_ARCHIVE.md](COVERAGE_ARCHIVE.md).

> All incidents are authored synthetic examples. This is an engineering project, not a factory-validated decision system or a Genorai product.

## Five-minute investigation

1. Open the featured incident, **Delayed start on sewing line S4**.
2. At revision 1 (11:00 cutoff), inspect 160 planned versus 87 recorded good units, a 73-unit observed shortfall, and the source-linked material and line-block events. The maintenance note was entered at 11:20 and is absent from this view.
3. Switch to revision 2 (11:30 cutoff). The note and corrected machine event appear. The original report remains available by its analysis URL and export.
4. Open a source chip and a historical precedent. Precedents explain lexical matches and operational differences; a match is not proof of cause.
5. Submit and review a proposal in local mode. Approval records a person's review of that revision and evidence. Revision 1 proposals are stale and cannot be newly approved.

See [INCIDENT_DEMO.md](INCIDENT_DEMO.md) for the short presentation script.

The **Evaluation lab** reports measured deterministic arithmetic, observable category coverage, lexical retrieval, and a recorded local-model run on authored synthetic cases. It shows the denominators, failed cases, and review limitations.

## Run locally

Prerequisites: Python 3.12+, [uv](https://docs.astral.sh/uv/), Node with pnpm, and PostgreSQL. No API key is required.

```bash
docker compose up -d db
cd backend
cp .env.example .env
uv sync
uv run alembic upgrade head
uv run python -m flooreplay seed
uv run uvicorn flooreplay.api:app --port 8000
```

In another shell:

```bash
cd frontend
pnpm install
pnpm dev
```

Open `http://localhost:5173`. Run `make verify` for backend tests, lint, type checking, and the frontend build. With the servers running, `make e2e` exercises the browser workflows.

## Optional local AI

The operational report works without Ollama. To try evidence-grounded draft claims on your own machine, install Ollama, pull `qwen3:1.7b`, start `ollama serve`, then run `cd backend && uv run python -m flooreplay worker`. The 4B model exceeded the 120-second draft budget on the development Mac, so the local default is the smaller fallback; it can be changed with `FLOORREPLAY_LOCAL_MODEL`. The workbench queues a local draft; the worker stores its exact bounded packet, model identity, usage, validation result, or explicit failure. Numeric claims must cite a calculated metric and evidence IDs must belong to the packet. Citation validity does not prove that prose is semantically supported, so drafts remain marked for human review. No paid fallback exists.

The older coverage note parser is a rule baseline by default. A paid parser requires both a key and the explicit `FLOORREPLAY_ALLOW_PAID_PARSER=true` switch; do not set that switch for the zero-spend workflow. Public mode has no local drafting or authoring routes.

The recorded ten-packet run on an Apple M1 Mac with 8 GiB RAM produced 4 structurally valid drafts out of 10. Project-author review found direct support for 8 of 16 claims in those drafts; p50/p95 elapsed times were 40.0/53.9 seconds. The saved hero draft and all six invalid cases remain inspectable. This is a small synthetic experiment, so the model stays labeled **experimental**. The 4B candidate timed out at 120 seconds and is not the default.

With the same three pinned retrieval queries and relevance labels, title-only PostgreSQL search retrieved 3 of 6 relevant cases in the top five; cutoff-visible evidence-card search retrieved 6 of 6. This small comparison shows why the evidence card is useful in the authored corpus, not a general retrieval-quality claim.

## Incident API and data rules

- `GET /api/v1/incidents`, `GET /api/v1/incidents/{id}/revisions/{revision}`
- `POST /api/v1/incidents/{id}/analyses`, `GET /api/v1/analyses/{id}`
- `GET /api/v1/analyses/{id}/evidence/{evidence_id}`, `GET /api/v1/analyses/{id}/export`
- `GET /api/v1/incidents/search?q=...` for live PostgreSQL lexical search
- `GET /api/v1/evaluation-reports/incident-core-v1` for the authored synthetic regression report
- `GET /api/v1/incidents/INC-001/saved-draft` for the clearly labeled saved local-model result
- Local-only import preview/publication, draft queue, and proposal review routes are included in OpenAPI at `/docs`.

Imports accept bounded UTF-8 `.csv`, `.json`, or `.jsonl` source records under the `production-v1`, `operations-v1`, and `notes-v1` profiles. Preview returns row diagnostics; publication reruns validation against the original bytes and creates an immutable new revision or rejects the whole file. Baseline plans are pinned and cannot be replaced by a later import. Source bytes and the preview audit are retained in PostgreSQL.

Production calculations use matching 15-minute final-good delta buckets. Missing buckets are unknown, not zero; unfinished buckets are excluded; explicit line blocks are unioned before duration is reported. The report separates measured shortfall from any hypothesis about its cause. An event appears only after its source availability time and corrections supersede old records without rewriting prior reports.

## Current scope and limits

The running application includes ten authored historical cases and one two-revision hero incident, deterministic analysis, PostgreSQL lexical retrieval, human review, local-only Ollama drafting, import publication, an offline saved report, and a live evaluation report. The larger 180-episode locked benchmark and pgvector hybrid retrieval in the project plan are not yet implemented. The ten-packet model result is separate from the deterministic evaluation and too small for a general quality claim. Public deployment is configured in `render.yaml` but must be deployed and checked separately.

The legacy coverage workflow and its tests are preserved in [COVERAGE_ARCHIVE.md](COVERAGE_ARCHIVE.md) and [DEMO.md](DEMO.md).
