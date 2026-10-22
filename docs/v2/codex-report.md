# FloorReplay 2.0 outer layer handoff

Work branch: `codex/v2-outer-layer`, based on `origin/feat/v2-order-decisions` (`cd28b27`). No deployment, provider calls, shared-branch commits, or pull requests. The pre-existing, untracked `docs/v2/CODEX_HANDOFF.md` is preserved.

## Package A — CSV preview imports

Built:
- `backend/src/flooreplay/decisions/imports.py`
- `backend/src/flooreplay/decisions/samples/README.md` and six profile CSVs
- `backend/tests/decisions/test_imports_core.py`
- `backend/tests/decisions/test_imports_profiles.py`

The pure preview builds real validated facts with deterministic IDs and a digest that binds the bytes, mapping, filename, declared time/zone, units, and coverage. `known_at` is a placeholder equal to `as_of` and is excluded from the digest. BLOCKED previews report input problems. Notes are NFC-normalised, digested, and returned separately; no extraction runs.

Choices where the brief allowed alternatives:
- Mapping direction is canonical field name → exact CSV header. Nothing is auto-mapped.
- `order-requests` keeps the order and style BOM on one row, with explicit JSON arrays for colours and trims. JSON fractional numbers are parsed directly as Decimal.
- ERP allocation columns are optional `allocation_order_id` + `allocation_qty`. A supplier row emits QC only with explicit `qc_issue` + `qc_qty` and a lot ID. Partial pairs block the row. Supplier QC uses `origin="supplier_updates"`, `review_state="checks_passed"`.
- An optional blank means absent; nonempty `#N/A`, `N/A`, or `-` blocks. A naïve `as_of` produces BLOCKED without building facts; its text is used only to digest that invalid preview.
- Every CSV has its synthetic provenance in its companion README. Buyer/supplier names are explicitly synthetic.

Test-first evidence: the initial import tests ran before implementation; after the interrupted worker, the focused run exposed three failures (naïve-time digest and two profile mappings). Additional regression tests then exposed seven failures before their fixes. Final focused suite: 38 passed (exit 0). Targeted Ruff and full mypy: exit 0.

Full package verification (all after the last Package A code edit):

| Directory | Command | Exit |
|---|---|---|
| `backend` | `uv run --python 3.12 pytest -q` | 0 |
| `backend` | `uv run --python 3.12 ruff check src tests` | 0 |
| `backend` | `uv run --python 3.12 mypy` | 0 |
| `backend` | `uv run --python 3.12 python -m flooreplay dataset-verify` | 0 |
| `frontend` | `pnpm lint` | 0 |
| `frontend` | `pnpm build` | 0 |
| `frontend` | `pnpm exec playwright test 'e2e/decisions-.*.spec.ts' e2e/incident-navigation.spec.ts` | 0 |
| `backend` | `uv run --python 3.12 python -m flooreplay export-openapi` | 0 |
| `.` | `git diff --exit-code -- backend/openapi.json frontend/src/lib/generated-api.ts frontend/src/data` | 0 |

At this stage the Playwright selector runs the two existing mocked navigation tests; v2 specs are added in B. Nothing remains unfinished in A.

Needs from lead:
- Publisher must restamp `known_at` with server time, enforce no backdating, retain the raw bytes and all identity inputs, and publish only a matching READY preview.
- One row can yield two facts (lot + allocation, inbound + QC, capacity + commitment, order + BOM); IDs have a deterministic suffix in these cases.
- ERP coverage is `CoverageDecl(profile, as_of, qualities)` without an artifact ID until publish.
- Notes produce `notes` records, not Facts. Extraction/publishing must consume these separately.
- The preview profile uses the existing `SourceProfile` underscore value, while the request selector uses hyphenated profile names.

## Package B — mocked API frontend

Built:
- `frontend/src/lib/decisions-types.ts` and `decisions.ts` (all provisional endpoints behind one client).
- Pages `frontend/src/pages/decisions/{DecisionsHome,OrderDecision,Timeline,ReplayLab,ReviewQueue,DecisionImports}.tsx`.
- Components `frontend/src/components/decisions/{GateBanner,FreshnessBadge,ConstraintCard,FactDrawer,RecordDecisionForm,KnowledgeScrubber,PolicyDiff,RegressionTable,SpanHighlight}.tsx`.
- Specs `frontend/e2e/decisions-{workbench,timeline,lab,review,imports,transport}.spec.ts`.
- Fixtures `frontend/e2e/fixtures/decisions/{orders,ready-decision,conflicting-decision,overtime-decision,review-decision,timeline,lab,review,imports}.json`.
- Routing/navigation in `frontend/src/App.tsx`, `components/{AppShell,NavigationEffects,ErrorBoundary}.tsx`, and `pages/NotFound.tsx`; v1 return links in `pages/{IncidentWorkbench,IncidentImports,IncidentDemo}.tsx`.
- Repointed `frontend/e2e/{incident-library,incident-navigation,incident-inputs-offline,incident,incident-csv-mapping-live,ledger-features,final-hardening}.spec.ts` and `frontend/e2e-visual/capture.spec.ts`.
- `frontend/src/lib/http.ts`: let the browser set multipart boundaries; add `apiNoContent` for successful commands without a response document.

V2 is the home page; v1 is at `/investigations`. Existing incident, demo, evaluation, and coverage route definitions remain. Every v2 network operation goes through `decisions.ts`. The UI shows every gate finding, ordered arithmetic, connected supersession history (including competing branches), saved human records and overrides, IST knowledge cutoffs, policy differences and regression classifications. It uses the existing board tokens and primitives.

Choices and boundaries:
- No freshness thresholds are invented: `DecisionView` has no per-source policy ages, so freshness shows observation age at the cutoff, source/fact ID, and the server's gate state.
- `total_qty` is provisionally typed as a string, with `pcs` added for display. Upload profile names are hyphenated; returned source-profile values follow the existing backend underscore enum.
- A run is adoptable only after GET loads its stored result, with complete=true, matching candidate/baseline/engine, and every regression acknowledged. Incomplete runs can be refreshed without starting a new run. The backend remains responsible for owner authorization and proving full-suite coverage.
- Review correction sends only changed fields and supports null clears. A span is highlighted only when its integer code-point bounds reproduce its stored text exactly. Auth epoch/cache clearing removes private rows and drafts on sign-out.
- Import mappings match Package A, including optional allocation, commitment and QC columns. Headers support quotes and commas, with no preselected mappings. All profiles use CSV; the broader plan's JSONL option is not exposed by this CSV-only package. One declared unit applies to each profile's quantity fields; files needing different units in those fields should be split into separate imports. As-of input is IST and sent as UTC. Any edit invalidates preview; retrying publish keeps its idempotency key.
- UTC-Z cutoffs and optional policy digests survive timeline navigation. Invalid cutoff links get an explanation and fall back to latest.

Test-first evidence:
- Core mocked specs initially failed before routes/pages existed (exit 1, four assertions).
- Lab/review/import specs initially failed at the missing page/form selectors (exit 1).
- Transport regression reproduced JSON headers on FormData (exit 1); the fix passed (exit 0). Empty-200/204 command tests failed before `apiNoContent` (exit 1), then passed (exit 0).
- Focused core suite: 6 passed, exit 0. Focused flows suite: 19 passed, exit 0. Combined decisions/navigation suite: 30 passed, exit 0.
- Related mocked v1 suite: `cd frontend && pnpm exec playwright test e2e/incident-library.spec.ts e2e/incident-navigation.spec.ts e2e/incident-inputs-offline.spec.ts e2e/final-hardening.spec.ts` — 12 passed, exit 0.
- Decision fixture facts were also passed through the real `Fact` and `validate_fact` models (exit 0).
- Axe checks cover all six page types. Captures under ignored `frontend/test-results/core/` were inspected at 1440 and 390px. Workbench overflow is checked at 320, 768, 1024 and 1440px. New specs intercept all API requests; no live backend or live sign-in is used.

Full verification after the final B edits and formatting:

| Directory | Command | Exit |
|---|---|---|
| `backend` | `uv run --python 3.12 pytest -q` | 0 |
| `backend` | `uv run --python 3.12 ruff check src tests` | 0 |
| `backend` | `uv run --python 3.12 mypy` | 0 |
| `backend` | `uv run --python 3.12 python -m flooreplay dataset-verify` | 0 |
| `frontend` | `pnpm lint` | 0 |
| `frontend` | `pnpm build` | 0 |
| `frontend` | `pnpm exec playwright test 'e2e/decisions-.*.spec.ts' e2e/incident-navigation.spec.ts` | 0 |
| `backend` | `uv run --python 3.12 python -m flooreplay export-openapi` | 0 |
| `.` | `git diff --exit-code -- backend/openapi.json frontend/src/lib/generated-api.ts frontend/src/data` | 0 |

All requested B work is complete against mocked responses. Live API integration is intentionally deferred to the lead-owned tasks.

Needs from lead:
- Implement the §5 API routes and replace the handwritten types with generated types when ready. The live v2 API and live E2E remain outside this package.
- Serialize every timestamp as canonical UTC-Z, including `ImportPreview.as_of` (the Python preview can retain an aware non-UTC offset).
- Confirm `total_qty` serialization; keep quantities in fact payloads as `{value: decimal-string, unit}`.
- Adopt/review-resolve tolerate successful bodyless 200 or 204. Publish must enforce private workspace access, bind all preview identity inputs and remain idempotent on retry.
- Owner-only adoption, complete-suite verification, and correction/supersession persistence stay authoritative on the backend.
- Tamil/Tanglish examples and labels remain synthetic and need the owner's language review.
