# Codex handoff: FloorReplay 2.0, the "outer layer" work

You are joining a project halfway through. Read this whole brief before touching anything. It tells you what the product is, what already exists, exactly which parts are yours, which parts you must not touch, and how to prove your work.

## 1. What the product is

FloorReplay is a portfolio project (FastAPI + PostgreSQL backend, React + Vite + TypeScript frontend, Playwright end-to-end tests, GitHub Actions CI, deployed to Render and Vercel). Version 1 is an "incident investigation workbench" for sewing-line shortfalls. It stays in the app as a legacy section and gets no new features.

Version 2 (what we are building) answers one question for knit-garment exporters in Tiruppur and Coimbatore, India: **"Should we accept this urgent order?"**

- Evidence arrives as **file imports only**: ERP fabric-stock CSV exports, a trims-status sheet exported to CSV, a shift-capacity CSV, supplier updates, order/BOM CSVs, and free-text notes (English, Tamil, and "Tanglish" = Tamil written in Latin letters).
- Every piece of evidence becomes an immutable **fact** with two clocks: `valid_from` (when it was true, e.g. the export's `as_of`) and `known_at` (when the system learned it). Corrections never overwrite; they are new facts that `supersede` old ones.
- A pure engine replays a decision **as known at a cutoff time**: `(snapshot of facts known by the cutoff, policy document, engine version) → decision`. Same inputs always give the same digest.
- A **gate** first says whether the evidence is usable: `READY`, `STALE`, `INCOMPLETE` or `CONFLICTING` (precedence CONFLICTING > INCOMPLETE > STALE > READY).
- Six **constraints** then return PASS / FAIL / NOT_EVALUATED with the exact arithmetic: FABRIC (per colour), SAFETY (safety stock), TRIMS (per trim), CAPACITY (sewing minutes), OVERTIME (only when capacity fails), APPROVAL (value/quantity thresholds).
- The engine **recommends** `ACCEPT`, `ACCEPT_WITH_CONDITIONS` (overtime or split shipment), `DECLINE` or `NEEDS_REVIEW`. An LLM is never allowed to decide; it only extracts structured signals from notes, and those are checked by deterministic code. A human merchandiser always records the final decision and reason.
- A **replay lab** compares a candidate policy against the current one over a frozen suite of past order cases (FIXED / REGRESSION / UNCHANGED / NOT_COMPARABLE). Adopting a policy requires a complete regression run and a written acknowledgement per regression.

The full approved plan is `docs/v2/PLAN.md`. Read it. Treat it as the contract. Also skim `docs/v2/discovery.md` (draft parameter defaults) and `docs/v2/changelog.md` (plan changes made since approval).

## 2. Where the code is

- Repo: `https://github.com/marsh15/flooreplay`. Work from branch **`feat/v2-order-decisions`** (pushed; head at the time of writing is `cd28b27`).
- Create your own branch from it: `git switch -c codex/v2-outer-layer origin/feat/v2-order-decisions`. Commit there. Do not commit to `feat/v2-order-decisions` or `main`, do not rebase or force-push shared branches, and do not open or merge PRs unless the owner asks.
- Backend: `backend/` (Python 3.12, `uv`). Frontend: `frontend/` (pnpm). Design tokens and UI rules: `DESIGN.md` at the repo root.

### What is already built (do not rewrite)

All under `backend/src/flooreplay/decisions/` with tests in `backend/tests/decisions/`:

| Module | What it does |
|---|---|
| `types.py` | Frozen pydantic models, `Fact`, `Quantity` (Decimal value + unit kg/m/pcs/minutes, max 3 dp, floats rejected), all enums (`FactKind`, `SourceProfile`, `GateState`, `ConstraintId`, `ConstraintStatus`, `Recommendation`, `ReviewState`, …), `canonical()` and `decision_digest()` (sha256 over canonical JSON). |
| `facts.py` | Registry of the 10 fact kinds: entity-key formats (e.g. `lot:{lot_id}`, `trim:{style_id}:{trim_id}`, `line:{line_id}:{YYYY-MM-DD}`) and typed payload schemas; `validate_fact`, `validate_corrections`, `EVENT_KINDS`. |
| `snapshot.py` | `snapshot_at(facts, cutoff)`, `current()` (latest observation per entity: FOUND / TIE_CONFLICT / COMPETING / UNKNOWN), `events()`. |
| `policy.py` | `PolicyDocument`, `policy_digest`, `parameter_diff`, `DEFAULT_POLICY_V1`, conflict-rule predicates, `cut_date()`, `sewing_days()`. |
| `gate.py` | `evaluate_gate(snapshot, order_id, policy, coverage) -> GateResult{state, findings[GateFinding{code, state, entity_key, fact_ids, detail, rule_id}], coverage_used}`; `CoverageDecl(profile, as_of, qualities)`. |
| `constraints.py` | `evaluate_constraints(...) -> ConstraintResult{constraint, subject, status, fact_ids, steps[Step{label, expression, value}], detail, consumed_by, pending_review_fact_ids, required, available, overtime}` (being revised right now — see §4). |
| `models.py`, `service.py` | Postgres tables `facts` and `decision_source_artifacts` (append-only: DB triggers reject UPDATE/DELETE/TRUNCATE; identity is `(workspace_id, id)`), `append_facts(session, facts, *, workspace_id)`, `load_facts`, `snapshot_at(session, workspace_id, cutoff)`, `is_settled`. |
| `extraction/` | `schema.py` (`note-signal-v2`: per field `{value, evidence}`; `normalize_note`, `note_digest`), `lexicon.py` (EN/TA/Tanglish issue cues), `checks.py` (`run_checks(note, signal, known_lots) -> ChecksOutcome`), `provider.py` (`GenerationProvider` Protocol, `MockProvider`, `RaisingProvider`), `anthropic_provider.py`, `openai_adapter.py`. |

Test helpers you should reuse: `backend/tests/decisions/worlds.py` (`ready_world()` builds a coherent, fully READY order world plus fact builders), `backend/tests/decisions/strategies.py` (Hypothesis strategies).

v1 code you will borrow patterns from: `backend/src/flooreplay/incident_import.py` (`_csv_records`, `_time`, `_alias_map`, `preview_identity`, preview → publish flow), `frontend/src/components/board.tsx` (`EvidenceLink`, `StatusTag`), `frontend/src/lib/status.ts` (`formatInstant`), `frontend/src/lib/http.ts` (`apiRequest`, `ApiError`), `frontend/e2e/incident-navigation.spec.ts` (mocked-API Playwright pattern), `frontend/e2e/archive-private-cache.spec.ts` (sign-out clears private rows).

## 3. Your assignments

There are three independent work packages. Do them in this order, one commit (or a few) per package. Each must leave every check green.

### Package A — CSV import parsing (plan tasks T14 + T15, preview layer only)

Goal: turn an uploaded file plus an explicit column mapping into a **preview** of decision facts. You do NOT write to the database and you do NOT add API routes (publishing and the API are owned elsewhere — §4).

Create `backend/src/flooreplay/decisions/imports.py` (pure; no DB, no clock, no network) with:

- `PROFILES`: `erp-fabric-stock`, `sheet-trims-status`, `shift-capacity`, `supplier-updates`, `order-requests` (orders + BOM + styles; may be two or three files/profiles if cleaner — document your choice), `notes`. Map each to its `SourceProfile` enum value in `types.py`.
- `preview_import(raw: bytes, *, filename: str, profile: str, column_mapping: dict[str, str], as_of: datetime, timezone: str = "Asia/Kolkata", units: dict[str, str] | None = None, coverage_qualities: list[str] | None = None) -> ImportPreview`.
  - `ImportPreview` (frozen model): `profile`, `filename`, `raw_digest`, `as_of`, `facts: tuple[Fact, ...]` (built through the real `Fact` model; `known_at` set to `as_of` as a placeholder — the publisher restamps it), `problems: tuple[ImportProblem(row, field, code, message), ...]`, `coverage: CoverageDecl | None` (ERP only), `status: "READY" | "BLOCKED"`, `preview_digest` (`decision_digest` of everything except `known_at`, so the same file + mapping + as_of always gives the same digest).
  - `valid_from` of every observation = `as_of`. Entity keys and payloads must pass `facts.validate_fact`; a row that fails becomes a problem, never a silently dropped row.
- Rules from the plan (each needs a test): an **explicit mapping** is required (no guessing columns); a declared **`as_of`** is required and must be timezone-aware; quantity columns need an explicit **unit** (column or `units` argument) of kg/m/pcs/minutes; cells like `#N/A`, `N/A`, `-`, empty required cells, **ambiguous dates** (e.g. `03/04/2026` — accept ISO `YYYY-MM-DD` only, or `DD-MMM-YYYY` like `03-Apr-2026`), and **thousands separators** (`1,200`) **block** the import with a problem instead of being guessed; floats are never created (parse to `Decimal` from text); file size and row caps like v1 (`MAX_BYTES`, `MAX_ROWS`); UTF-8 with BOM handling; Tamil text is NFC-normalised.
  - `erp-fabric-stock` rows produce `fabric_lot` facts (and `fabric_allocation` rows if the file has an allocation section/column — document); the call declares `coverage_qualities` → `CoverageDecl`.
  - `sheet-trims-status` → `trim_status`; `shift-capacity` → `line_capacity` and `line_commitment`; `supplier-updates` → `fabric_inbound` (and supplier QC lines → `fabric_qc` with `origin="supplier_updates"`, `review_state="checks_passed"` only if the row is an explicit QC result — otherwise skip and document); `order-requests` → `order_request` and `bom`.
  - `notes` → do NOT extract anything. Produce note records `{note_id, lot_hint?, text (NFC), note_digest}` in a separate `notes` field of the preview; extraction is owned elsewhere.
  - Fact ids: deterministic, e.g. `"{profile}:{raw_digest[:12]}:{row}"`, so re-previewing the same file gives the same ids.
- Sample files: `backend/src/flooreplay/decisions/samples/*.csv` (one or more per profile) for a synthetic factory "Tiruppur Knits (synthetic)", lines `L1`–`L4`, styles like `POLO-221`, lots like `L-221`, colours like `NAVY`, `WHITE`, quality like `SJ180`. Mark every sample file with a first-line comment or companion README stating the data is synthetic. Include a few Tamil/Tanglish notes.
- Tests: `backend/tests/decisions/test_imports_core.py` (rules above, each blocking case, determinism of ids and digest) and `backend/tests/decisions/test_imports_profiles.py` with a **parametrized test asserting every sample file previews `READY`**, and that every produced fact passes `validate_fact`. Write tests first and watch them fail.

### Package B — The v2 frontend against a mocked API (plan tasks T24–T29)

The backend API for v2 does not exist yet. Build the UI against the **provisional contract in §5**, with every network call going through one module, `frontend/src/lib/decisions.ts`, so it can be rewired to generated types later. Put the TypeScript types for the contract in `frontend/src/lib/decisions-types.ts` (hand-written, mirroring §5 exactly). Do not edit `frontend/src/lib/generated-api.ts`, `backend/openapi.json` or `frontend/src/data/*` (CI fails on drift).

1. **Routing (T24):** v2 becomes the home page. Move the v1 incident library from `/` to `/investigations` (keep `/incidents/:id`, `/incidents/imports`, `/demo`, `/evaluation` working) and label it "Shortfall investigations (v1)" in the nav. Leave the `/coverage/*` archive routes exactly as they are (another task deletes them later). Update the v1 Playwright specs that navigate to `/` so they go to `/investigations`, and the visual-capture config if it lists `/`.
2. **Pages** in `frontend/src/pages/decisions/`: `DecisionsHome` (order list with latest outcome and gate state), `OrderDecision` (the workbench), `Timeline` (knowledge-time scrubber), `ReplayLab`, `ReviewQueue`, `DecisionImports`. Routes: `/` (home), `/orders/:orderId`, `/orders/:orderId/timeline`, `/lab`, `/review`, `/imports`.
3. **Components** in `frontend/src/components/decisions/`:
   - `GateBanner` (state + every finding, written labels — never confidence percentages), `FreshnessBadge`, `ConstraintCard` (status, subject, the ordered arithmetic steps as a readable table, `EvidenceLink`s to fact ids), `FactDrawer` (fact payload, valid_from, known_at, source, supersession chain), and a **record-decision form** (final outcome select + required reason; shows when the human overrides the engine).
   - `KnowledgeScrubber` (T26): slider/stepper over knowledge times; fully keyboard-operable (arrow keys, Home/End), shows times in **IST** (`Asia/Kolkata`, reuse `formatInstant` style), updates the URL `?cutoff=`.
   - `PolicyDiff` (list of `{path, before, after}`) and `RegressionTable` (per case: baseline verdict, candidate verdict, classification) for the lab (T27). The **Adopt** button is disabled until a stored, complete regression run exists for the candidate, and requires a written acknowledgement for every REGRESSION row.
   - `SpanHighlight` (T28): highlights evidence spans in a note using **code-point offsets** (`Array.from(text)` indexing, not UTF-16 `slice`) — test it with Tamil text containing combining marks.
   - Review queue (T28): list items, show the note with highlighted spans and the failed checks, actions confirm / correct / reject (POST per §5).
   - Imports page (T29): pick profile, upload file, map columns, declare `as_of` (IST input, sent as UTC ISO), preview table with problems, publish button (disabled when BLOCKED).
4. Follow `DESIGN.md` tokens and the existing look (Archivo + JetBrains Mono, existing `ui/` primitives). Accessible names on all controls, visible focus, no colour-only status.
5. **Tests:** Playwright specs using `page.route` mocks only (copy the `incident-navigation.spec.ts` pattern; no live backend, no sign-in): `e2e/decisions-workbench.spec.ts`, `e2e/decisions-timeline.spec.ts`, `e2e/decisions-lab.spec.ts`, `e2e/decisions-review.spec.ts` (including a port of "sign-out clears private rows"), `e2e/decisions-imports.spec.ts`. Include an axe check per page if the repo already uses axe (check `playwright.visual.config.ts` / existing specs). Put mock fixtures in `frontend/e2e/fixtures/decisions/*.json`, shaped exactly like §5, including: a READY+ACCEPT order, a CONFLICTING order (ERP says lot L-221 has 4,000 m, a dyeing note says 1,200 m failed), an ACCEPT_WITH_CONDITIONS order (overtime), a NEEDS_REVIEW order with Tamil and Tanglish note spans.

### Package C — Note corpus and benchmark scoring (prep for plan task T34)

The plan requires notes to be **drafted by an LLM other than the one being evaluated** (the evaluated models are Anthropic Claude Haiku/Sonnet). You are that other LLM.

1. Draft `backend/evaluation/note-benchmark-v1/notes.jsonl`: **100 synthetic notes** — about 40 English, 30 Tamil script, 30 Tanglish — written the way dyeing-house, fabric-store and QC staff in Tiruppur actually message (short, mixed units, lot numbers like `L-221`, quantities in kg or m, colour names, shade/GSM/hole/stain issues, some notes with no issue at all, some negations like "no holes", some with two lots, some with lakh/k multipliers). Each line: `{note_id, language: "en"|"ta"|"tanglish", text, synthetic: true, drafted_by: "codex"}`. Also a 30-note `pilot.jsonl` subset (ids only, stratified by language).
2. Draft `gold.jsonl` with **proposed** gold fields per note in the `note-signal-v2` shape (`lot_id, issue, qty, unit, colour, fabric_quality`, each `{value, evidence}` or null; evidence copied exactly from the text) and `"gold_status": "draft_unreviewed"`. The owner (a Tamil speaker) will correct these; never mark them reviewed.
3. A manifest `manifest.json` with per-file sha256, counts by language, and a `frozen: false` flag; plus a small verifier function.
4. Pure scoring module `backend/src/flooreplay/decisions/extraction/benchmark.py`: given gold and predictions (NoteSignal-shaped dicts) plus `ChecksOutcome`s, compute **field accuracy**, **missing-field recall** (gold null → predicted null), **span validity rate** (evidence located exactly once), and **checks_passed precision** (of fields the checks trusted, how many match gold) — each reported **with numerator and denominator**, overall and per language. Tests in `backend/tests/decisions/test_benchmark.py` using `MockProvider` only. **No real API calls, no API keys, ever.**

## 4. Do NOT touch (owned by the lead engineer, in progress or next)

Do not edit these files or implement these tasks, even if they look unfinished. If your work needs something from them, write it down in your final report instead.

- `backend/src/flooreplay/decisions/{types,facts,snapshot,policy,gate,constraints,models,service}.py` and their tests (`test_canonical, test_snapshot, test_policy, test_gate, test_constraints, test_store`), `worlds.py`, `strategies.py` (you may *import* them; if you need a new world helper, put it in your own test file).
- `backend/src/flooreplay/decisions/extraction/{schema,lexicon,checks,provider,anthropic_provider,openai_adapter}.py` and their tests.
- `backend/alembic/**` (no migrations), `backend/src/flooreplay/api.py`, `workspaces.py`, `schema_head.py`, `spending.py`, `config.py`, `backend/openapi.json`, `frontend/src/lib/generated-api.ts`, `frontend/src/data/**`, `.github/workflows/**`, `render.yaml`.
- Plan tasks owned elsewhere: T8 fix (constraints, in progress), T9 recommend/replay, T10 compare, T11 evaluations/records, T12 regression/adoption, T13 decisions API, T16 publish + import API, T19 extraction service, T20 review backend, T21/T22 decision cases, T23 seeding, T30 live E2E, T31–T33 deleting the coverage stack, T35 regression demo, T36 docs rewrite, T37 deploy.
- Never set or use real API keys, never deploy, never touch Render/Vercel/Neon.

## 5. Provisional v2 API contract (frontend mocks must match this)

All under `/api/v1/decisions`. Times are UTC ISO strings with `Z`; display in IST. Decimals are strings. This is provisional: keep all access in `lib/decisions.ts`.

```ts
type GateState = 'READY' | 'STALE' | 'INCOMPLETE' | 'CONFLICTING'
type ConstraintStatus = 'PASS' | 'FAIL' | 'NOT_EVALUATED'
type Outcome = 'ACCEPT' | 'ACCEPT_WITH_CONDITIONS' | 'DECLINE' | 'NEEDS_REVIEW'

type GateFinding = { code: string; state: GateState; entity_key: string; fact_ids: string[]; detail: string; rule_id: string | null }
type GateResult = { state: GateState; findings: GateFinding[]; coverage_used: { artifact_id: string; as_of: string; qualities: string[] } | null }
type Step = { label: string; expression: string; value: string }   // value like "220.5 kg"
type ConstraintResult = {
  constraint: 'FABRIC' | 'SAFETY' | 'TRIMS' | 'CAPACITY' | 'OVERTIME' | 'APPROVAL'
  subject: string; status: ConstraintStatus; fact_ids: string[]; steps: Step[]; detail: string
  consumed_by: string[]; pending_review_fact_ids: string[]
}
type Condition =
  | { type: 'overtime'; lines: number; hours_per_line_per_day: number; days: number }
  | { type: 'split_shipment'; colour: string; covered_qty: number; remainder_qty: number; remainder_ship_date: string }
type RecommendationView = { outcome: Outcome; candidate_outcome: Outcome | null; conditions: Condition[]; reasons: string[] }
type FactView = { id: string; kind: string; entity_key: string; payload: Record<string, unknown>; valid_from: string; valid_to: string | null; known_at: string; supersedes_id: string | null; source: string; artifact_id: string | null }
type DecisionRecord = { id: string; recorded_at: string; reviewer: string; engine_outcome: Outcome; final_outcome: Outcome; reason: string; override: boolean }
type DecisionView = {
  order_id: string; cutoff: string; settled: boolean
  policy: { digest: string; label: string; engine_version: string }
  snapshot_digest: string; decision_digest: string
  gate: GateResult; constraints: ConstraintResult[]; recommendation: RecommendationView
  facts: FactView[]; records: DecisionRecord[]
}
```

Endpoints:
- `GET /orders` → `{ orders: { order_id, buyer, style_id, ship_date, total_qty, latest: { outcome, gate_state, cutoff } | null }[] }`
- `GET /orders/{orderId}?cutoff=ISO&policy=digest` → `DecisionView` (no cutoff = latest settled time)
- `GET /orders/{orderId}/timeline` → `{ knowledge_times: string[], events: { known_at, fact_id, kind, entity_key, source, summary }[] }`
- `POST /orders/{orderId}/records` body `{ cutoff, policy_digest, final_outcome, reason }` → `DecisionRecord`
- `GET /policies` → `{ adopted: digest, policies: { digest, label, engine_version, created_at }[] }`
- `GET /policies/diff?base=digest&candidate=digest` → `{ changes: { path, before, after }[] }`
- `POST /regression-runs` body `{ policy_digest }` → `RegressionRun`; `GET /regression-runs/{id}` → `RegressionRun = { id, policy_digest, baseline_digest, suite_digest, engine_version, complete: boolean, cases: { case_id, title, baseline: 'PASS'|'FAIL', candidate: 'PASS'|'FAIL'|null, classification: 'UNCHANGED_PASS'|'UNCHANGED_FAIL'|'FIXED'|'REGRESSION'|'NOT_COMPARABLE' }[] }`
- `POST /policies/{digest}/adopt` body `{ run_id, acknowledgements: Record<case_id, string> }` → 200, or 403 for non-owners, 409 if the run is incomplete or an acknowledgement is missing
- `GET /review-items` → `{ items: { id, kind: 'extraction'|'decision', note_id?, note_text?, fields?: { name, value, evidence, span: {start,end,text}|null, status, failed_checks: string[] }[], order_id?, created_at, assignee: string|null }[] }`; `POST /review-items/{id}/resolve` body `{ action: 'confirm'|'correct'|'reject', corrected?: Record<string, {value, evidence}>, reason }`
- `POST /imports/preview` (multipart: file, profile, column_mapping JSON, as_of, units?, coverage_qualities?) → preview (same fields as `ImportPreview` in Package A, facts as `FactView`); `POST /imports/publish` body `{ preview_digest, idempotency_key }` → `{ artifact_id, facts_created }`; both require a private workspace (403 `PRIVATE_IMPORT_REQUIRED` on the public demo).

## 6. Environment and commands

```bash
# one-time
make test-db                      # starts Postgres (pgvector/pg17) on localhost:5435 via docker compose
docker exec flooreplay-test-db-1 createdb -U flooreplay_test flooreplay_codex_test
export FLOORREPLAY_DATABASE_URL=postgresql+psycopg://flooreplay_test@localhost:5435/flooreplay_codex_test
export FLOORREPLAY_TEST_DATABASE_URL=$FLOORREPLAY_DATABASE_URL   # conftest refuses names not ending in _test
export FLOORREPLAY_OPENAI_API_KEY='' FLOORREPLAY_ANTHROPIC_API_KEY=''
cd backend && uv run --python 3.12 alembic upgrade head && uv run --python 3.12 python -m flooreplay seed
cd ../frontend && pnpm install --frozen-lockfile && pnpm exec playwright install chromium
```

Checks (run after your last edit of each package; all must exit 0 — check exit codes directly, do not pipe pytest into `tail`):
- Backend: `cd backend && uv run --python 3.12 pytest -q && uv run --python 3.12 ruff check src tests && uv run --python 3.12 mypy && uv run --python 3.12 python -m flooreplay dataset-verify`
- Frontend: `cd frontend && pnpm lint && pnpm build && pnpm exec playwright test e2e/decisions-*.spec.ts e2e/incident-navigation.spec.ts`
- Drift: `cd backend && uv run --python 3.12 python -m flooreplay export-openapi && cd .. && git diff --exit-code -- backend/openapi.json frontend/src/lib/generated-api.ts frontend/src/data` (must be clean: you should not change the API)
- Python must be 3.12 (`uv run --python 3.12`), Decimals only (no floats in facts), Hypothesis tests use `deadline=None` if slow.

## 7. Working rules

- Test first: write the failing test, run it, see it fail, then implement. Never weaken, skip or delete an existing test to get green.
- Small commits with conventional messages (`feat(decisions): …`, `test: …`). **No AI attribution lines** in commits (no `Co-Authored-By`, no "Generated with").
- Match the surrounding code style (look at `decisions/gate.py`, `incident_import.py`, existing pages). No speculative abstractions.
- Never invent facts about real companies or people. All data is synthetic and labelled so.
- If something in the plan is ambiguous, pick the simplest reading, note it in your report, and keep going. If a needed backend piece is missing, mock it in tests and list it under "needs from lead".

## 8. Final report (write it to `docs/v2/codex-report.md` and commit it)

For each package: what you built (file list), decisions you made where the plan was ambiguous, every check command with its exit code, anything you could not finish, and a **"needs from lead"** list (API fields the UI assumed, import outputs the publisher must handle, gold labels the owner must review).
