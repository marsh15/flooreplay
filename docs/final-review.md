# Final review, October 2, 2026

This review records application improvements, portfolio copy changes and their verification limits. It does not certify production acceptance. The work preserved existing workspace and operations changes and initiated no deployment or paid provider call.

The code changes listed below were first committed only to the unmerged branch `codex/portfolio-upgrade`. `main` received this document and the guide updates in `acb62ba` without that code. They were later ported onto the redesigned `main`; see [status on main](#status-on-main-october-19-2026) for what was ported, what was left out and how the port was verified.

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

The hardening above was committed to `codex/portfolio-upgrade` from `e610169`. That branch diverged at `e9eb3de` and was never merged. `main` then gained the production-board redesign (PR 4). At `main` commit `6325812` none of the listed code changes were present.

On October 19 the hardening was ported onto `6325812` without merging the branch. The branch's pages, lockfile, data bundles and documents predate the redesign and would have reverted it, so the port carries only the hardening:

- Backend, taken as written because `main` had not changed backend source since the merge-base: `http_security.py` (16 MiB JSON envelope cap, 30-second body-delivery limit, security and exact-origin CORS headers on early and unhandled error responses, no exception names in public errors), the bounded and synchronized limiter in `ratelimit.py`, mixed-workspace rejection and workspace inheritance for replay reviews, the timezone check on hybrid-search cutoffs, whole-ledger allowance totals, batched library-review and capability queries, and typed configuration limits
- Frontend, re-applied to the redesigned components: one request path in `src/lib/api.ts` with deadlines, typed network, timeout and invalid-response errors, used by the incident, workflow, workspace and operations clients; session expiry on 401, ordered sign-in with account validation and immediate local sign-out in `Auth.tsx`; retries that reuse the original idempotency key for AI drafts and hybrid search; note drafts bound to the submitted text; a recovery screen for invalid revision links; replay export through an authenticated download; debounced, cancellable searches; and 15-second query freshness with one retry for non-4xx failures
- Page recovery: the branch's `PageRecovery.tsx` was not added. The redesign's `ErrorBoundary` and `NotFoundPage` stay. The boundary now resets on navigation and on every sign-in, sign-out or session expiry, and a full-page instance covers failures in the shell. A small `NavigationEffects` component sets the page title and, after the first load, scrolls to the top and moves focus to the main content on route changes
- Delivery: nginx body cap and static security headers; Vercel CSP, Permissions-Policy, HSTS and `--ignore-scripts` install; `frontend/.npmrc` disables lifecycle scripts; CI, the backend Dockerfile and Render use uv 0.12.19 with `--no-build` syncs; CI runs `pnpm install --ignore-scripts` and `uv audit --frozen` and stops the browser API after the browser suite
- Regressions: `test_final_hardening.py`, `test_http_security.py` and `final-hardening.spec.ts`, the last adapted to the redesign's wording

Left out on purpose: the branch's copy and README rewrites, regenerated demo bundles, favicon set, `component-variants.css`, mobile control sizing and contrast class changes. The redesign replaced those screens and styles. The bundle regeneration and offline-fallback test updates in `65c73ae`, `e43b30f` and `9b5b73c` were not carried over; `main`'s own bundles and consistency check stay authoritative.

Local verification of the port, run after the final edit against a disposable PostgreSQL database ending in `_test`, with no provider key:

| Check | Result |
| --- | --- |
| Ruff and mypy | Passed |
| Fresh migration, seed and dataset verification | Passed |
| Backend tests | 249 passed (241 existing, 8 new) with `TZ=UTC`, as in CI |
| OpenAPI, generated client and saved-report exports | No diff |
| `uv audit --frozen` | No known vulnerabilities in 61 packages |
| Frontend lint, Prettier check, Vercel-mode production build | Passed, after a `--ignore-scripts` install |
| Playwright against a local API | 65 passed, including the 3 new scenarios |
| Backend image build with `--no-build`; Compose configuration | Passed |

One existing backend test, `test_recorded_provider_metrics_and_append_only_claim_review`, fails when the host timezone is not UTC because it compares timestamps rendered in different offsets. It passes under `TZ=UTC` and is not affected by the port. Repeated local Playwright runs within 15 minutes also hit the existing 10-per-client sign-in limit; a single run, as in CI, does not.

Still open for `main`:

1. Merge the port and confirm the CI run on the merge commit, including `uv audit` and the `--no-build` install on Linux runners.
2. Run mobile browser acceptance. The CI browser suite uses only a 1440×900 viewport.
3. Complete authenticated hosted acceptance with the ported build. Render will pick up the uv 0.12.19 `--no-build` build command on its next deploy.

Items 2 to 4 of "Before production sign-off" are unchanged.
