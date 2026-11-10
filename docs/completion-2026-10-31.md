# Shortfall workflow implementation and verification — October 31, 2026

This pass implements the useful remaining changes from the production-shortfall plan on `main`, starting at `bd4052e`. The application code through `935deee` is covered by the checks below. It does not establish factory adoption, model accuracy or operational benefit.

The existing dirty `codex/v2-outer-layer` checkout was preserved. Its unfinished order-decision work was not merged into the shortfall workflow. Work on `main` used a separate checkout.

## What changed

- **Simpler investigation guidance:** five linked steps show the discrepancy, missing evidence, findings, comparison and export. The guide distinguishes pinned evidence from current assignments and handover. Deep links use the incident's revision inventory when the library has no summary. Conflicting review submissions refresh the card from the server.
- **Reusable CSV mappings:** owners can explicitly download and load column-name mappings. Loading validates the profile, fields, headers and one-column-per-field rule, clears constants and requires a fresh preview. Source rows, constants, aliases and destination values are excluded from the download. A stale asynchronous load cannot replace newer form state.
- **Historical correctness:** database regressions preserve the report, evidence links, correction history and precedent-corpus identity across corrections, follow-up responses, completion, resolution and reopening. A duplicate pending review with a new request identity is rejected; an exact retry retains its receipt.
- **Stable review history:** claim reviews, shared publications, run assessments, incident analyses and workflow timestamps serialize in UTC. A PostgreSQL session in `Asia/Kolkata` exposed changing response strings between the original write and a reload; regressions now cover this, including queue and review-packet consistency. Original source payload timestamps remain intact.
- **Practical measurement:** the offline [pilot tool](pilot/README.md) validates baseline/FloorReplay pairs, separates synthetic and practitioner cohorts, preserves failures in success-rate counts, reports missing metric denominators, and computes descriptive paired times only when both attempts succeed. Same-incident comparisons are supported and explicitly flagged for possible learning effects. Method order is reported. The blank template contains no results.
- **Operator documentation:** the [operator guide](operator-guide.md) explains import, investigation, assignment, findings, revision comparison, export and recovery in one place.
- **Dependency patches:** the locked certificate bundle, Vite and Zod were updated after actual audit failures. The certificate-bundle [maintainer advisory](https://github.com/certifi/python-certifi/security/advisories/GHSA-6q48-6c7w-9gw2), [Vite advisory](https://github.com/advisories/GHSA-587h-7wmj-h5pm), and [Zod advisory](https://github.com/advisories/GHSA-mrhx-c7xc-m3w5) document the patched releases.

## Verification

Environment: macOS arm64; Python 3.12.12; PostgreSQL 17.11 with pgvector; Node 26.10.0; pnpm 10.30.0; uv 0.12.19. Database and browser data were disposable synthetic test data. Provider calls were mocked or disabled.

A new PostgreSQL cluster bound to loopback port 5435 used `flooreplay_completion_test`. Fresh migrations reached `20261001_operations`. Seeding twice created no duplicate artifacts on the second run. The database's default timezone was `Asia/Kolkata`, so verification did not depend on a UTC database default.

Commands ran from the corresponding `backend` or `frontend` directory. Database commands set `FLOORREPLAY_DATABASE_URL` and tests set `FLOORREPLAY_TEST_DATABASE_URL` to the isolated test database. Provider keys were empty outside deliberately mocked tests.

- `uv run --python 3.12 pytest`: **336 passed**, exit 0.
- `uv run --python 3.12 ruff check src tests`: passed, exit 0.
- `uv run --python 3.12 mypy`: passed for 51 source files, exit 0.
- `uv run --python 3.12 alembic upgrade head`: fresh-database migration passed, exit 0.
- `uv run --python 3.12 python -m flooreplay seed`: initial and repeat seed passed, exit 0.
- `uv run --python 3.12 python -m flooreplay dataset-verify`: passed; 120 historical, 30 development and 30 locked synthetic episodes, 60 arithmetic/structure checks, exit 0. This is not practitioner validation.
- `pnpm lint` and `pnpm build`: passed, exit 0.
- Full `pnpm exec playwright test --workers=2`: **81 passed**, exit 0, against the final frontend and a restarted API running the final backend changes. This includes live CSV import/correction and assigned-check flows, offline recovery, workspace privacy, exports and the new guide regressions. The guide also passed its focused axe and phone-layout checks.
- `python -m flooreplay export-openapi`, `python -m flooreplay export-demo`, `pnpm generate:api`, then `git diff --exit-code -- backend/openapi.json frontend/src/lib/generated-api.ts frontend/src/data`: no drift, exit 0.
- `uv audit --frozen`: no known vulnerabilities or adverse statuses in 61 packages, exit 0.
- `pnpm audit --audit-level high`: exit 0; **three moderate development-tool advisories remain**, all for inherited minimatch versions. The [maintainer advisory](https://github.com/isaacs/minimatch/security/advisories/GHSA-g3hv-75wg-m249) requires version 11.0.1 or later. This pass did not force that major API change into callers of older minimatch versions.
- `docker compose --profile test config --quiet` and `git diff --check`: passed, exit 0. The Docker daemon was unavailable, so container startup was not reverified.

Intermediate failures were retained as development evidence: the new timezone and guide regressions first failed, then passed after their fixes. A repeated live-browser run hit the configured persistent login limiter; only the disposable test database's limiter rows were reset before rerunning. One custom test-server URL used an IPv4 address while Vite bound to `localhost`; correcting the test URL fixed startup. Neither security rate limits nor test assertions were weakened.

Claude Haiku 5.5 at high effort implemented the delegated slices and reviewed the combined change. Review findings led to the historical-deep-link, stale-card, elapsed-time and timestamp fixes above. Same-case comparisons remain supported to match the requested exercise, with their limitations exposed instead of being silently treated as independent cases.

## Remaining completion evidence

1. Interview three to five relevant practitioners using the [existing protocol](practitioner-interview.md). Record their real workflow and contrary feedback before assuming the application fits it.
2. Observe consenting practitioners completing an investigation. Use the [comparison protocol](comparative-pilot.md), retain raw observations and failures, and publish measured findings only after they exist.
3. Run authenticated acceptance against the actual hosted release and verify deployment, recovery and ownership for that environment. Local database and browser success is not hosted acceptance.
4. Keep independent human review of AI claims separate from deterministic correctness. This pass made no paid FloorReplay provider requests and produced no new model-accuracy claim.

The workflow permits a supervisor to resolve a new revision explicitly with a written rationale after an older completed check. New evidence reopens the incident, and old outcomes remain historical; a new completed check is not required automatically for every correction. XLSX imports, saved server-side mappings and automatic notifications are not needed for this demonstrated workflow and remain separate scope decisions.
