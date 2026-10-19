# Final review, October 2, 2026

This review records application improvements, portfolio copy changes and their verification limits. It does not certify production acceptance. The work preserved existing workspace and operations changes and initiated no deployment or paid provider call.

The code changes listed below exist only on the unmerged branch `codex/portfolio-upgrade`. `main` received this document and the guide updates in `acb62ba` without that code. See [status on main](#status-on-main-october-19-2026) for what `main` actually contains and what its CI verifies.

## Changes

- Replay reviews inherit their source workspace and reject mixed-workspace input. Linked records fail closed when their parent cannot be found.
- Account/session changes remount operational forms, clear query state and discard delayed authenticated responses. Login ordering prevents an older request from replacing a newer sign-in. Logout clears local authority immediately and reports unconfirmed server revocation.
- Note drafts retain the exact submitted text when the note is edited during extraction. Draft and hybrid-search retries preserve their request identity. A new draft requires a definite rejection or recovered terminal result after interruption.
- Network requests have deadlines, typed errors and request receipt IDs. Unknown routes, invalid revisions and rendering failures offer recovery options. Downloads attach the bearer header, and searches debounce/cancel stale requests.
- The API caps JSON envelopes at 16 MiB and body delivery at 30 seconds. Source import byte/row limits remain tighter. API error responses carry security/CORS policy, and public failures omit exception details. nginx uses the matching envelope cap and static security headers; Vercel adds CSP, permissions and HSTS.
- Public limiter state is bounded and synchronized. Allowance totals aggregate the whole ledger in SQL while display entries are capped. Library review summaries use one aggregate query; capability requests avoid a duplicate corpus-readiness scan and batch embedding availability.
- Dependency installs use frozen locks, disabled frontend lifecycle scripts and wheel-only third-party Python installation. uv is pinned to 0.12.19 where release configuration selects it, and both native audits run in CI.
- Mobile form controls use larger text and touch targets, and archived report metadata uses stronger contrast.
- README and application copy describe a general manufacturing evidence workbench. Company-specific references and stale confidentiality statements were removed. Synthetic-data and human/factory-validation limits remain explicit.

## Verification evidence

| Check | Current result | Limit |
| --- | --- | --- |
| Python Ruff source lint | Passed | Static analysis only |
| Python mypy | Passed | Static types only |
| TypeScript application check | Passed | No production build or browser execution |
| New browser regression TypeScript | Passed | Tests were type-checked, not executed |
| Python source syntax / frontend JSON | Passed | Parsing only |
| Credential-signature source/history scan | No matches across 701 history blobs and 273 tracked files | Limited key/header signatures, not every credential form |
| pnpm native lockfile audit | Zero reported advisories, 583 dependencies | Known advisory database only |
| uv native frozen-lock audit | Zero vulnerabilities/adverse statuses, 61 packages | Known advisory database only |
| Independent source verification | Privacy fixes refuted the original candidate paths; middleware integration corrected | No runtime reproduction |
| Integration and browser regressions | Authored, not executed in this pass | Required execution sandbox unavailable |
| Production build and clean policy install | Pending | Not inferred from static checks |
| Current authenticated hosted acceptance | Pending | Historical public checks are for earlier source |

New regressions cover private replay-derived reviews, cross-workspace rejection, limiter capacity expiry, invalid cutoffs before paid work, full-ledger allowance accounting, streamed/declared body limits, exact-origin error responses, account form reset, invalid navigation and delayed note extraction. Existing suites remain the broader acceptance contract.

The security-audit workflow covered part of the source. Its external run retains metadata, coverage, independent dispositions and validated structured records. The final critic deferred import/parser internals, AI output/structured-note internals, rollback/release lifecycle paths and refreshed runtime/supply-chain coverage. The pass confirmed no findings within its coverage. It did not cover the full security surface.

## Before production sign-off

1. Run a clean frozen install, production build, database tests, migration checks, generated-contract checks and desktop/mobile browser acceptance in a fully isolated disposable environment. Preserve current source identity with the results.
2. Validate authenticated hosted workflows, exact CORS/TLS/proxy behavior, error headers, backup ownership, restore compatibility and an operational response owner. Vercel CSP currently allows HTTPS API connections; restrict it to the exact API origin for confidential deployment.
3. Measure large-library/retrieval/operations latency. Some retrieval and operations paths still perform per-record database work. The public replay limiter is process-local; replicated serving needs a shared limiter.
4. Establish confidential-data retention, export/deletion and backup policy before a real-data pilot. Obtain qualified human review of AI claims and practitioner validation before claiming factory benefit.

The audit skill requires OS-enforced execution isolation. This host has macOS toolchains and a cached PostgreSQL Docker image, but no verified complete sandbox for project/database/browser execution with every required resource and write boundary. The review therefore did not run the target code. Static analyzers and package-manager advisory checks do not substitute for those runtime gates.

Dependency controls follow [pnpm settings](https://pnpm.io/settings) and [uv installation controls](https://docs.astral.sh/uv/reference/cli/). Advisory checks do not establish package provenance or absence of unknown vulnerabilities.

## Status on main, October 19, 2026

The hardening above was committed to `codex/portfolio-upgrade` from `e610169`. That branch diverged at `e9eb3de` and was never merged. `main` then gained the production-board redesign (PR 4). At `main` commit `6325812`, these listed changes are absent:

- `http_security.py`: the 16 MiB JSON envelope cap, the 30-second body-delivery limit and security headers on API error responses
- Rejection of mixed-workspace replay review input
- The bounded, synchronized public replay limiter. The limiter on `main` keeps one entry per client key with no upper bound
- nginx body cap and static security headers; Vercel CSP, Permissions-Policy and HSTS
- The CI and Vercel install policy: CI on `main` uses uv 0.10.4, `uv sync --frozen` without `--no-build` and `pnpm install --frozen-lockfile` without `--ignore-scripts`, and runs only `pnpm audit`
- The regressions in `test_final_hardening.py`, `test_http_security.py` and `final-hardening.spec.ts`

The redesign separately added a not-found page and a rendering error boundary to `main`.

CI run `38723895367` passed on `6325812` on October 15, 2026. It ran Ruff, mypy, frontend lint, the Vercel-mode production build and `pnpm audit --audit-level high`; a fresh migration, two seeds and dataset verification; 241 backend tests; OpenAPI, generated-client and saved-report consistency; 62 Playwright scenarios against a real API with no provider key; and Compose configuration validation. This supersedes the "Pending" production build and the unexecuted existing suites in the table above for `main`.

Still open for `main`:

1. Port the `codex/portfolio-upgrade` hardening onto the redesigned frontend and run its regressions.
2. Exercise the clean policy install. CI does not use lifecycle-script or source-build restrictions.
3. Run mobile browser acceptance. The CI browser suite uses only a 1440×900 viewport.
4. Complete authenticated hosted acceptance. On October 19 the hosted API reported build `acb62ba` and schema `20261001_operations`, and no backend source has changed between that build and `6325812`.

Items 2 to 4 of "Before production sign-off" are unchanged.
