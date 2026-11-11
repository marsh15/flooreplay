# FloorReplay 2.0: garment order decisions you can replay

Approved implementation plan. Every v2 task brief points here; treat this file as the contract.
Changes after approval are logged in `docs/v2/changelog.md`.

## Context

FloorReplay today is a mature incident-investigation workbench: 66 commits, about 12k backend lines, FastAPI, Postgres, React, CI, and Vercel/Render/Neon. It reconstructs a sewing-line shortfall from evidence known at a cutoff. Version 2.0 moves it into one concrete domain, Tiruppur and Coimbatore knit exporters, and one concrete decision: **should we accept this urgent order?** The aim is a lead portfolio project for forward-deployed and manufacturing-AI roles. It should show workflow understanding, imperfect data, LLMs kept away from rule-made decisions, and ownership of the outcome.

**Starting point found in the repo, which drives reuse:**
- **The incident stack already has true bitemporal records.**
  - Every record carries `available_at` (knowledge time) plus `start`/`end`/`occurred_at` (valid time).
  - Corrections use `supersedes_id`, checked by `incident_engine.validate_corrections` (`incident_engine.py:17`).
  - Visibility is computed by `_visible` (`:48`).
  - Imports go preview → publish, keyed by a preview digest (`incident_import.preview_identity:43`, `incident_service.publish_source:285`).
- **The archived operator-coverage stack has the closest shape to ContextGate, constraints and regression.**
  - A pure gate with a decision-time clock and inclusive freshness (`domain/gate.py:61`).
  - Latest-wins selection, UNKNOWN≠absent, and findings with evidence refs.
  - C01–C12 constraints that return PASS/FAIL with evidence.
  - A 32-case `Expectation` suite.
  - `service.run_comparison`/`_classify` (FIXED/REGRESSION).
  - It is hard-wired to operators, and its policies are code branches, not data.
- **Missing pieces:** the fabric/trims/capacity domain, an accept/decline decision, decision diffs, multilingual handling, typed extraction with spans, DB-level immutability, and a provider interface. Only OpenAI exists today.
- **A trap for extraction:** the v1 AI validator rejects any digit in model output (`incident_ai._numeric_prose`). Extraction needs its own schema and validator.

## Decisions (settled in grilling)

| # | Decision |
|---|---|
| 1 | **Pivot in place.** Garment decisions become the home page (`decisions/` area, `/api/v1/decisions/*`). The v1 incident workbench stays reachable as "Shortfall investigations (v1)" at `/investigations` and gets no new features. The coverage archive is **deleted** after its patterns are ported; the `coverage-v1` tag preserves it. |
| 2 | **Week-1 discovery** with 2–3 garment practitioners. The output is `docs/v2/discovery.md` plus a "what changed" log. The constraint list freezes at the end of week 1. If nobody is reached, the docs say so. |
| 3 | **Narrow LLM extraction is in V1** with a 30-note pilot; the 100-note EN/TA/Tanglish benchmark is in week 4. |
| 4 | **Provider Protocol, with Claude for extraction.** `claude-haiku-5-5` is the default and `claude-sonnet-5-5` the comparison, via the official `anthropic` SDK. The OpenAI v1 path is untouched; it is wrapped by an adapter that satisfies the Protocol. Spending gets a per-model price table. |
| 5 | **First-class append-only `facts` table** with `valid_from`, `valid_to`, `known_at` and `supersedes_id`. A Postgres trigger rejects UPDATE, DELETE and TRUNCATE. |
| 6 | **Policy = immutable, digested parameter document.** Constraint logic lives in code, versioned by `ENGINE_VERSION`. Replay is the pure function `(snapshot, policy, engine_version) → decision`. |
| 7 | **The engine recommends ACCEPT, ACCEPT_WITH_CONDITIONS, DECLINE or NEEDS_REVIEW.** Auto-ACCEPT requires the gate to be READY, every constraint to pass, and the order to be under the approval threshold. The merchandiser always records the final decision and a reason; overrides are kept. The LLM never decides. |
| 8 | **Sources are file imports only:** ERP CSV, Google Sheet exported to CSV, shift CSV, supplier updates, and notes as CSV/JSONL. There are no live connectors and no XLSX. |
| 9 | **An incident is a past order-decision case** with a hindsight outcome and a hand-written expected recommendation per policy. V1 has 30 hand-authored synthetic cases, frozen with a digest manifest. |
| 10 | **Notes are drafted by an LLM other than the one being evaluated.** The owner, a Tamil speaker, corrects them and writes the gold fields. Real notes are used only with permission and anonymised. |
| 11 | **Orders are modelled at style × colour; sizes are ignored.** Consumption = BOM avg/piece × qty × (1+wastage). Capacity per line = SAM × qty / (efficiency × available minutes − commitments). |
| 12 | **Four UI screens:** order decision workbench, knowledge-time scrubber, replay lab, review queue. A small imports screen is added on top. |
| 13 | **Conflict rules are declarative and live in the policy.** A conflict clears only when a reviewed *resolution fact* arrives, and that fact has its own `known_at`. |
| 14 | **Extraction confidence uses deterministic checks only.** The span must be an exact substring, the value must re-parse from the span, the lot regex must match, the issue must be in the enum with a lexicon hit, and the entity must exist. A field that fails goes to review. An unreviewed signal that affects a constraint forces NEEDS_REVIEW. |
| 15 | **Policy adoption is owner-only.** It requires a stored, *complete* regression run for the exact policy digest and engine_version, plus a written acknowledgement for each REGRESSION case. |
| 16 | **Four-week sequence:** W1 is discovery, domain and gate. W2 is constraints and replay. W3 is imports, extraction, cases and UI. W4 is the benchmark, the demo, docs and deploy. The stretch items are only outlined. |
| 17 | **Explicit units (kg or m).** Units convert only when GSM and width are known facts. A mismatch makes the constraint NOT_EVALUATED and the gate INCOMPLETE. |
| 18 | **Gate precedence is CONFLICTING > INCOMPLETE > STALE > READY**, and all findings are kept. The freshness clock is the decision cutoff, never `now()`, and the boundary is inclusive. Times are stored in UTC and displayed in IST. Work happens on branch `feat/v2-order-decisions`. |

**Design clarifications added during review:**
- **Observation vs correction.** Each periodic export row is an *observation* with `valid_from` = the file's `as_of`. The current value is the latest-`valid_from` unsuperseded fact per `(kind, entity_key)`. A tie with different payloads is CONFLICTING. An entity missing from the newest export is UNKNOWN, never zero. Freshness is computed per required entity.
- **No backdating.** `known_at` is the server time at publish, and `as_of <= known_at` is enforced. Only seed and CLI may author `known_at` (needed for the frozen cases).
- **Decimal arithmetic.** Required quantities round up and available quantities round down, which makes the monotonicity properties hold. Decimal text is normalised before digesting. `domain/hashing._SORTED_COLLECTION_HINTS` must not change, because it would break frozen v1 digests. v2 builders sort explicitly.
- **Correction validation.** Validate the visible subset at read time and the full graph at write time, so a later bad fact can never break an older replay.
- **Extraction spans.** Spans are stored as code-point offsets plus their text, and Tamil is NFC-normalised before digesting. The extraction record stores its checks version and check results, so replay never recomputes them.
- **Public demo.** Reads and replay are open to anyone. Imports, extraction and adoption require a private workspace (`PRIVATE_IMPORT_REQUIRED` pattern). Decisions on demo cases can be recorded by a reviewer.
- **Purity guard test.** The pure decision modules never import `db`, `extraction`, `time` or `random`, and never call `datetime.now`.

## Domain contract (v1 defaults; T2 discovery may revise them before the week-1 freeze)

**Fact kinds.** Each kind has an `entity_key` and a typed payload. Quantities are `{value: Decimal, unit}`.

| Kind | entity_key | Payload (key fields) | Source profile |
|---|---|---|---|
| `order_request` | `order:{order_id}` | `buyer`, `style_id`, `colours[{colour, qty_pcs}]`, `ship_date`, `order_value_inr`, `partial_shipment_allowed` | order-requests |
| `bom` | `bom:{style_id}` | `fabric_quality`, `consumption_per_pc{value,unit}`, `trims[{trim_id, qty_per_pc}]`, `sam_minutes` | order-requests/BOM |
| `fabric_lot` | `lot:{lot_id}` | `fabric_quality`, `colour`, `qty`, `gsm?`, `width_m?` (an observation per export) | erp-fabric-stock |
| `fabric_qc` | `lot:{lot_id}` | `issue` (`shade_fail\|gsm_fail\|defect`), `qty`, `review_state`, `origin`, `extraction_id?` | notes (extraction) or supplier-updates |
| `fabric_inbound` | `inbound:{ref}` | `fabric_quality`, `colour`, `qty`, `eta`, `supplier` | supplier-updates |
| `fabric_allocation` | `alloc:{order_id}:{quality}:{colour}` | `qty` (allocated to an existing committed order) | erp-fabric-stock |
| `trim_status` | `trim:{style_id}:{trim_id}` | `on_hand`, `inbound_qty?`, `eta?`, `supplier` | sheet-trims-status |
| `line_capacity` | `line:{line_id}:{date}` | `available_minutes`, `efficiency_pct?` | shift-capacity |
| `line_commitment` | `commit:{order_id}:{line_id}:{date}` | `committed_minutes` | shift-capacity |
| `resolution` | the conflicted entity_key | `rule_id`, `left_fact_id`, `right_fact_id`, `resolved_payload` (e.g. `usable_qty`), `reviewer` | review queue |

**Artifact coverage.** An ERP export declares `coverage.fabric_qualities`. If a covered quality has no lot for a colour, that colour has 0 on hand (known). An uncovered quality is INCOMPLETE. This ports the old `coverage_complete` idea.

**Required facts (missing ⇒ INCOMPLETE):**
- the `order_request`, and the `bom` for its style;
- covered fabric stock for the BOM quality in every ordered colour;
- a `trim_status` for every BOM trim;
- a `line_capacity` for every eligible line on every working day in the sewing window;
- GSM and width when the units differ.

**Freshness.** The age of an entity is `cutoff − valid_from` (the export's `as_of`). It must be `<= freshness_hours[source]`, inclusive. Anything older is STALE.

**Observation ties.** When two facts have the same `valid_from`, equality compares the canonical digest of the payload's *semantic* fields, excluding row numbers and raw text.

**Extraction signals.**
- If every field passes the checks, the signal is written with `review_state=checks_passed` and is trusted.
- If any field fails, it is written with `review_state=needs_review` and a review item is created.
- A human confirmation, correction or rejection is a superseding fact.
- A `needs_review` fact that feeds a constraint forces NEEDS_REVIEW.

**Units and rounding.** Use Decimal quantized to 0.001. Required amounts round up (CEILING) and available amounts round down (FLOOR). `metres = kg × 1000 / (gsm × width_m)`.

**Constraints.** Each returns PASS, FAIL or NOT_EVALUATED, together with the fact ids used and the arithmetic as an ordered list of `{label, expression, value}` steps.
- **FABRIC** (per colour):
  - `req = qty × consumption × (1 + fabric.wastage_pct)`.
  - `usable_onhand = Σ lot.qty − Σ fabric_qc.qty (review_state ∈ {checks_passed, confirmed})`. A resolution's `usable_qty` replaces this for its lot.
  - `inbound = Σ fabric_inbound.qty where eta <= cut_date − inbound_buffer_days`.
  - `committed = Σ fabric_allocation.qty` for other orders.
  - `free = usable_onhand + inbound − committed`. PASS if `free >= req`.
- **SAFETY** (per colour): PASS if `free − req >= safety_floor_pct × (usable_onhand + inbound)`. A FAIL names the allocations that consumed the stock.
- **TRIMS** (per trim): `need = Σqty × qty_per_pc × (1 + trims.wastage_pct)`. PASS if `on_hand >= need`, or if `on_hand + inbound_qty (eta <= cut_date − trims.buffer_days) >= need`.
- **CAPACITY**: `required = Σ qty × sam / efficiency`, where efficiency is taken from the line fact or falls back to `default_efficiency_pct`. `available = Σ over eligible lines × working days in [cut_date+1, ship_date − finishing_days] of (available_minutes − committed_minutes)`. PASS if `available >= required`. `cut_date = ship_date − cut_to_ship_days`.
- **OVERTIME** is evaluated only when CAPACITY fails. `ot_available = lines × days × ot_cap_hours_per_line_day × 60`. It PASSes (making the shortfall curable) if `shortfall <= ot_available`. The condition is `ceil(shortfall / (lines × days × 60))` hours per line per day.
- **APPROVAL**: PASS if `order_value_inr <= max_value_inr` and `Σqty <= max_qty_pcs`.
- **Monotonicity properties:**
  - More stock, more inbound or more minutes never turns PASS into FAIL.
  - More qty never turns FAIL into PASS (for FABRIC, SAFETY, TRIMS and CAPACITY).

**Recommendation.** The rules are applied in order:
1. The gate is not READY, or a `needs_review` signal feeds a constraint ⇒ NEEDS_REVIEW.
2. CAPACITY fails but OVERTIME passes ⇒ add the condition `{type: overtime, lines, hours_per_line_per_day, days}`.
3. FABRIC or TRIMS fails for some colours, `partial_shipment_allowed` is true, and the remainder date can be computed from inbound ETAs plus `cut_to_ship_days` ⇒ add the condition `{type: split_shipment, colour, covered_qty, remainder_qty, remainder_ship_date}`.
4. Any other FAIL ⇒ DECLINE.
5. Conditions were added ⇒ ACCEPT_WITH_CONDITIONS. Otherwise ⇒ ACCEPT.
6. The result is ACCEPT or ACCEPT_WITH_CONDITIONS but APPROVAL fails ⇒ NEEDS_REVIEW, and the reason keeps the candidate outcome.

**Policy document** (canonical JSON; its digest identifies it):
`{label, engine_version, freshness_hours{erp_fabric_stock, sheet_trims_status, shift_capacity, supplier_updates, notes, order_requests}, fabric{wastage_pct, inbound_buffer_days, safety_floor_pct}, trims{wastage_pct, buffer_days}, capacity{eligible_lines[], default_efficiency_pct, cut_to_ship_days, finishing_days, ot_cap_hours_per_line_day}, approval{max_value_inr, max_qty_pcs}, conflict_rules[{id, left_kind, right_kind, join: "entity_key", valid_time: "overlap", predicate}], enabled_constraints[]}`.
- `predicate` names a function from a closed registry versioned by `ENGINE_VERSION`, for example `qc_claims_against_lot` or `inbound_eta_disagrees`. It is not a DSL.
- A `resolution` fact clears a conflict only for its `(rule_id, left_fact_id, right_fact_id)` and only from its own `known_at` onward.
- The policy diff is a list of `{path, before, after}` entries, plus the outcome changes per case.

**Cases and classification.**
- Each case has one hand-authored `correct` recommendation, with a rationale informed by evidence and hindsight. This is "the right call".
- It may also carry optional `required_findings`.
- A policy's verdict on a case is PASS if `outcome == correct` and the required findings are present.
- Comparing the baseline and candidate verdicts gives: (PASS, PASS) ⇒ UNCHANGED_PASS; (FAIL, FAIL) ⇒ UNCHANGED_FAIL; (FAIL, PASS) ⇒ FIXED; (PASS, FAIL) ⇒ REGRESSION; missing case, engine error, or a different suite digest ⇒ NOT_COMPARABLE.
- A v1 mistake is a v1 verdict of FAIL against `correct`.

## Architecture

**Backend `backend/src/flooreplay/decisions/`**
- **Pure:** `types.py` (frozen models, Decimal quantity with unit, enums), `facts.py` (kind registry and payload schemas; ports `validate_corrections`/`_visible`), `snapshot.py`, `policy.py` (document, digest, parameter diff), `gate.py` (ports `_fresh`, latest-wins and precedence), `constraints.py`, `recommend.py`, `replay.py` (`ENGINE_VERSION="decision-v1"`), `expectations.py`, `compare.py` (ports `_classify` with a NOT_EVALUATED branch fix, and `_changed_paths`).
- **Effectful:** `models.py`, `service.py` (fact store, `snapshot_at`, evaluate, record), `imports.py`, `publish.py`, `adoption.py`, `review.py`, `cases.py`, `api.py` (an `APIRouter` included from `create_app`, which inherits `request_scope`).
- **Extraction (`decisions/extraction/`):** `schema.py`, `lexicon.py`, `checks.py`, `provider.py` (Protocol + mock), `anthropic_provider.py`, `openai_adapter.py`, `service.py`, `benchmark.py`.

**Tables.** New migrations follow the `YYYYMMDD_name.py` convention; the head before v2 is `20261001_operations`.
`facts`, `decision_source_artifacts`, `policies`, `policy_adoptions`, `decision_cases` (hindsight is kept out of facts), `case_expectations`, `decision_evaluations` (unique on order, cutoff, policy_digest, engine_version and snapshot_digest), `decision_records` (append-only), `regression_runs`, `note_extractions` (unique on note_digest, model, prompt_version and schema_version), `review_items` and `review_events`.
Every workspace-bearing table must be registered in the scope tuple (`workspaces.py:132`) and `scope_new_rows` (`workspaces.py:140`), and in `alembic/env.py`.

**Frontend.**
- Pages in `pages/decisions/`: `DecisionsHome`, `OrderDecision`, `Timeline`, `ReplayLab`, `ReviewQueue`, `DecisionImports`.
- Components in `components/decisions/`: `GateBanner`, `FreshnessBadge`, `ConstraintCard`, `FactDrawer`, `KnowledgeScrubber`, `PolicyDiff`, `RegressionTable`, `SpanHighlight`.
- Data layer: `lib/decisions.ts`, typed from `generated-api.ts`.
- Reused from v1: `board.tsx` (`EvidenceLink`, `StatusTag`), `lib/status.ts` (`formatInstant`) and the DESIGN.md tokens.

## Invariants (each one has a test)

| Invariant | Test |
|---|---|
| Same snapshot, policy and engine_version always give an identical decision digest, even with facts shuffled | Hypothesis property (T9) |
| No snapshot contains a fact with `known_at > cutoff` | Hypothesis property (T5) |
| Corrections never overwrite; the original can be reconstructed; the DB rejects UPDATE, DELETE and TRUNCATE | property (T5) + integration (T6) |
| CONFLICTING or INCOMPLETE never produces ACCEPT | Hypothesis property over generated snapshots (T9) |
| Monotonicity: more fabric never turns PASS into FAIL; more quantity never turns FAIL into PASS | Hypothesis property (T8) |
| Replay never calls a provider | provider that raises + purity guard (T9, T19) |

Shared Hypothesis composite strategies live in `backend/tests/decisions/strategies.py`. They use a small entity-key alphabet to force collisions, and supersession points only to facts with an earlier `known_at`.

## Shared rules for every task

- **Owner gates (🔒).** A subagent never decides an owner gate. It stops and returns what it needs. Gates: T1 branch/worktree deletions, T2 calls and the constraint freeze, T22 case review, T34 gold labels, T37 deploy and keys. If the freeze has not happened when T8 starts, T8 uses the drafted list and logs every later change in `docs/v2/changelog.md`.
- **Migration lane.** Strictly T6 → T11 → T19 → T32; each `down_revision` is the previous one. Each bumps the schema head. T6 first replaces the literals in `api.py` and `tests/test_hosted_deployment.py` with one `SCHEMA_HEAD` constant.
- **GEN lane.** Strictly T13 → T16 → T20 → T31 → T33. Any other task that changes API shapes joins this lane. CI fails on drift in `openapi.json`, `generated-api.ts` and `src/data`.
- **Test isolation.** Tests use uuid workspaces and uuid keys, because the facts trigger forbids cleanup.
- **E2E specs.** T25–T29 use `page.route` mocks only (follow `incident-navigation.spec.ts`). T30 is the single live spec with one sign-in (limit: 10 sign-ins per 15 minutes).
- **References:** `scope_new_rows` is `workspaces.py:140`; scope tuple `:132`; publish advisory lock `incident_service.py:297`. `ServiceError` has 10 importers in `src`; `test_reliability.py` also imports `recover_interrupted`.
- **Purity guard (T9).** AST scan of `decisions/{snapshot,gate,constraints,recommend,replay,policy,compare}.py`: never import `db`, `models`, `extraction`, `time`, `random`, or call `datetime.now`.

### Commands

DB-backed commands need the test Postgres: `make test-db` once, then
`export FLOORREPLAY_TEST_DATABASE_URL=postgresql+psycopg://flooreplay_test@localhost:5435/flooreplay_release_test`
(and the same value for `FLOORREPLAY_DATABASE_URL`; `conftest.py` refuses any name not ending in `_test`).
- `BE(f)`: `cd backend && uv run pytest tests/f && uv run ruff check src tests && uv run mypy`
- `MIG`: `cd backend && uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head`
- `GEN`: `make generate-api && git diff --stat`; commit the regenerated files.
- `FE`: `cd frontend && pnpm lint && pnpm build`
- `GATE`: `make verify && make dataset-verify && (cd backend && uv audit --frozen)`

## Task list

### Week 0–1: housekeeping, discovery, domain, gate

| ID | Task | Deps | Acceptance |
|---|---|---|---|
| T1 | Git housekeeping: fast-forward `main`, tag `incident-v1-final`, create `feat/v2-order-decisions`, owner-approved branch/worktree deletions. | none | `git branch -vv`; `git worktree list`; CI green |
| T2 ∥ | Discovery pack: `docs/v2/discovery.md` (interview guide, notes template, current workflow and pain points, "not reached" status) and `docs/v2/changelog.md`. Draft the constraint list with a freeze date. The owner runs the calls. | none | Owner review; no invented findings |
| T3 ∥ | Decouple shared code from coverage: `ServiceError` → `errors.py` (re-exported from `service.py`; repoint importers and tests). Split shared transport (`apiRequest`, `apiDownload`, `ApiError`, `API_BASE`) out of `frontend/src/lib/api.ts` into `lib/http.ts`. | T1 | GATE; FE; `e2e/incident-navigation.spec.ts` |
| T4 ∥ | Types, units and strategies: `decisions/types.py` and `tests/decisions/strategies.py`. | T1 | BE(decisions/test_canonical.py); v1 digests pinned unchanged |
| T5 | Facts and snapshot (pure): port `incident_engine.py:17-61` with visible-subset validation, observation semantics and `intervals.overlaps`. | T4 | BE(decisions/test_snapshot.py): cutoff, shuffle, reconstruction, competing-replacement properties |
| T6 ∥T7 | Facts table and store (M1): migration `20261021_decisions_facts` (`facts`, `decision_source_artifacts`, append-only triggers), workspace scope, `service.append_fact` with advisory lock, `snapshot_at`, `SCHEMA_HEAD`. | T5 | MIG; trigger, workspace isolation and DB-vs-pure snapshot equality tests; `test_hosted_deployment.py` |
| T7 ∥T6 | Policy document and ContextGate: per-source freshness, declarative conflict rules and resolution facts, units, precedence; port `gate._fresh`. | T5 | BE(decisions/test_gate.py, test_policy.py) |

### Week 2: constraints, recommendation, replay, policies

| ID | Task | Deps | Acceptance |
|---|---|---|---|
| T8 | Constraints: fabric (wastage, kg↔m via GSM/width), trims before cut, line capacity, overtime cap, safety stock, approval threshold; PASS/FAIL/NOT_EVALUATED with fact ids and arithmetic. | T7, constraint list (T2) | BE(decisions/test_constraints.py) with monotonicity properties |
| T9 | Recommend and replay: pure `replay()`, outcome rules and conditions, purity guard test. | T8 | BE(decisions/test_replay.py): determinism and never-auto-accept |
| T10 | Expectations, classification, diff, policy v2 document: port `domain/evaluation.py`, `service._classify` (fix NOT_EVALUATED fall-through) and `_changed_paths`. | T9 | BE(decisions/test_compare.py) |
| T11 | Evaluations and records (M2): migration `20261022_decisions_records`; idempotent evaluation; record decision and override reason; `reconstruct`. | T6, T9 | BE(decisions/test_service.py); MIG |
| T12 | Regression runs and adoption: full-suite coverage, interrupted runs never pass, owner-only adoption with per-REGRESSION acknowledgement. | T10, T11 | BE(decisions/test_adoption.py); reviewer gets 403 |
| T13 | Decisions API: orders, `snapshot?cutoff=`, evaluate (rate-limited via `limit_public_execution`), record, policies, diff, regression, adopt. | T11, T12 | BE(decisions/test_api.py); GEN no drift |

### Week 3: imports, extraction, review, cases, UI

| ID | Task | Deps | Acceptance |
|---|---|---|---|
| T14 ∥ | Import core + `erp-fabric-stock` and `sheet-trims-status` profiles (reuse `incident_import._csv_records`, `_time`, `_alias_map`, preview identity). Explicit mapping, declared `as_of`, units column; `#N/A`, ambiguous dates and thousands separators block. | T6 | BE(decisions/test_imports_core.py) |
| T15 | Remaining profiles: `shift-capacity`, `supplier-updates`, `order-requests`/BOM/styles, `notes`, with sample CSVs. | T14 | BE(decisions/test_imports_profiles.py); every sample READY |
| T16 | Publish service and import API (`PREVIEW_MISMATCH`, `PRIVATE_IMPORT_REQUIRED`, raw bytes, server `known_at`). | T13, T15 | BE(decisions/test_publish.py); GEN |
| T17 ∥ | Extraction core (pure): signal schema with code-point spans, validator, versioned EN/TA/Tanglish lexicon, deterministic checks, `GenerationProvider` Protocol + mock. | T4 | BE(decisions/test_extraction_checks.py) |
| T18 ∥ | Per-model spending and providers: `spending.cost(..., model=)`, `anthropic_provider.py` (official SDK, `max_retries=0`, forced structured output), `openai_adapter.py`, `FLOORREPLAY_ANTHROPIC_API_KEY` in config/render.yaml/CI (empty). Prices from official docs with version and effective date. | T3 | BE(test_paid_release.py, decisions/test_providers.py); `uv audit --frozen`; v1 OpenAI tests unchanged |
| T19 | Extraction store and service (M3): migration `20261023_decisions_extraction`; reserve budget → call → persist → signal facts; 30-note pilot. | T6, T17, T18 | BE(decisions/test_extraction_service.py) incl. replay with a raising provider; MIG |
| T20 | Review queue backend: items from failed fields and NEEDS_REVIEW decisions; assignment pattern from `incident_workflow`; resolution as superseding fact. | T13, T19 | BE(decisions/test_review.py); GEN |
| T21 | Case harness and first 6 cases (every gate state); manifest pattern from `trust_evaluation.verify_release`/`incident_dataset`; hand-written expectations; synthetic label; `decision-cases-verify` in `dataset-verify`. | T9 | BE(decisions/test_cases.py) |
| T22 ∥×3 | Remaining 24 cases in three disjoint batch files; owner review before freeze. | T21 | Manifest verifies; zero unexplained mismatches |
| T23 | Seeding: v2 additively into the demo workspace as "Tiruppur Knits (synthetic)"; CLI commands; second run `created=0`. | T11, T22 | seed twice → 0; `dataset-verify` |
| T24 | Frontend foundation: routes, v1 library → `/investigations`, nav, `lib/decisions.ts`, repoint v1 specs and visual capture. | T13, T3 | FE; repointed v1 specs |
| T25 ∥ | Order decision workbench: `GateBanner`, `FreshnessBadge`, `ConstraintCard`, `FactDrawer`, record form; written labels, no confidence percentages. | T24 | FE; `e2e/decisions-workbench.spec.ts`; axe |
| T26 ∥ | Knowledge-time scrubber (keyboard-accessible, IST). | T24 | FE; `e2e/decisions-timeline.spec.ts` |
| T27 ∥ | Replay lab: `PolicyDiff`, `RegressionTable`, acknowledgements; adopt disabled until a stored run exists. | T24 | FE; `e2e/decisions-lab.spec.ts` |
| T28 ∥ | Review queue UI: `SpanHighlight` by code point; port "sign-out clears private rows" test. | T24, T20 | FE; `e2e/decisions-review.spec.ts` |
| T29 ∥ | Decisions imports UI. | T24, T16 | FE; `e2e/decisions-imports.spec.ts` |
| T30 | One live E2E spec (single sign-in) plus visual capture of new routes. | T25–T29, T23 | full Playwright; `pnpm visual`; GATE |

### Week 4: retire coverage, benchmark, demo, docs, deploy

| ID | Task | Deps | Acceptance |
|---|---|---|---|
| T31 | Delete the backend coverage stack (conftest first; domain `gate/validator/policies/engine/types/evaluation`, `service.py`, `fixtures*.py`, `importing.py`, `parsing.py`, `eval_notes.py`, legacy routes, `recover_interrupted` lifespan, coverage keys/models/seeding, Makefile `eval-notes`, coverage tests). Keep `hashing.py`, `intervals.py`. Enumerate removed model classes in the PR description. | T10, T23 | GATE; GEN; grep returns nothing |
| T32 | Drop legacy tables (M4) `20261101_drop_coverage` in FK order; downgrade recreates empty tables; `pg_dump` first. | T31 | MIG; fresh `upgrade head` |
| T33 | Delete the frontend coverage stack (pages, `EvidenceDrawer`, `status.tsx`, coverage halves of `lib/*`, nav, specs, ui-baseline entries). | T31, T32, T24 | FE; GEN; full Playwright |
| T34 | 100-note benchmark (`backend/evaluation/note-benchmark-v1/`): notes, gold labels, frozen manifest; EN/TA/Tanglish; staged runs; field accuracy, missing-field recall, span validity with denominators; Haiku vs Sonnet; CI uses mock only. | T19, owner gold labels | offline BE(decisions/test_benchmark.py) |
| T35 | Regression demo: policy v2 fixes one past mistake and breaks another; stored run catches both; adoption refused until acknowledged. | T12, T22 | BE(decisions/test_regression_demo.py); lab E2E |
| T36 | Docs: v1 docs → `docs/v1/`; rewrite README, PRODUCT, ARCHITECTURE, RELEASE_STATUS, case study; numbers with denominators and synthetic label; stretch items outlined. | T33–T35 | GATE; every claim links to a test or artifact |
| T37 | Deploy and FDE walkthrough: Anthropic key on Render, Neon `pg_dump`, deploy, authenticated hosted acceptance, walkthrough. | T36 | dated hosted acceptance artifact in `docs/evidence/` |

**Critical path:** T1 → T4 → T5 → T6/T7 → T8 → T9 → T11 → T12 → T13 → T24 → T25–T29 → T30 → T31–T33 → T36 → T37.

## Risks to watch

- The constraint freeze depends on discovery calls the owner has to book. If they slip, T8 starts from the drafted list and logs the later changes.
- The Tamil gold labels and the notes drafted by a second LLM are owner work in week 3–4, so they sit on T34's critical path.
- Render's free tier cold starts and Neon's destructive migration (T32) need a backup first.
- Committed `frontend/src/data` bundles and the drift check mean v1 report bundles must not change; `_SORTED_COLLECTION_HINTS` stays untouched.

## Verification (end to end)

1. `make verify`, `make dataset-verify` (v1 manifests plus the decision-case manifest), `cd backend && uv audit --frozen`.
2. `cd frontend && pnpm lint && pnpm build && pnpm audit --audit-level high`, then `make e2e` and `pnpm visual` (axe).
3. `make generate-api` then `git diff --exit-code -- backend/openapi.json frontend/src/lib/generated-api.ts frontend/src/data`.
4. Manual demo with `docker compose up --build --wait` at http://localhost:5174: workbench (seeded urgent polo order: CONFLICTING at the 11:00 cutoff — ERP L-221 4,000 m vs dyeing note 1,200 m failed; scrub past the QA resolution and the gate turns READY), replay lab (one FIXED, one REGRESSION, adoption blocked until acknowledged), review queue (Tamil/Tanglish spans that failed a check).
5. Hosted acceptance (`scripts/hosted_acceptance.py`) against the deployed commit; receipt in `docs/evidence/`.
