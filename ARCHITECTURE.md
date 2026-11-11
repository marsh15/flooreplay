# Architecture

FloorReplay is a FastAPI and PostgreSQL backend with a React single-page frontend. Version 2 (order decisions) lives beside the earlier incident-investigation workbench, which is described in [docs/v1/ARCHITECTURE.md](docs/v1/ARCHITECTURE.md).

## The shape of a decision

```
CSV imports ──► preview ──► publish ──► facts (append-only, two clocks)
                                              │
                         snapshot as known at a cutoff
                                              │
        policy document ─────────────────────►├──► gate ──► constraints ──► recommendation
        engine version ──────────────────────►│                                  │
                                              ▼                                  ▼
                                      decision digest                 human final decision + reason
```

Replay is a pure function: `(snapshot, policy, engine_version) → decision`. The pure modules do not import the database, a clock or a random source; tests enforce that for the gate, policy and constraint modules.

## Backend modules (`backend/src/flooreplay/decisions/`)

| Module | Role |
| --- | --- |
| `types.py`, `facts.py` | Frozen models, decimal quantities with explicit units, the ten fact kinds, entity-key formats and payload schemas, canonical JSON and the decision digest |
| `snapshot.py` | The facts known at a cutoff, the latest observation per entity, ties and competing replacements |
| `policy.py` | The immutable, digested parameter document, the closed registry of conflict predicates, the parameter diff and the default policy |
| `gate.py` | Per-source freshness (inclusive, judged at the cutoff, never the wall clock), missing evidence, conflicts and reviewed resolutions |
| `constraints.py` | Fabric, safety, trims, capacity, overtime and approval, each with its ordered arithmetic and the fact ids it used |
| `recommend.py`, `replay.py` | The outcome rules and the pure replay |
| `expectations.py`, `compare.py` | Hand-labelled past cases and the fixed, regressed, unchanged and not-comparable classification |
| `imports.py`, `publish.py` | Explicit-mapping CSV preview (no guessing columns, dates or units) and the publish step that stamps `known_at` from the database clock |
| `service.py`, `models.py` | The fact store, stored evaluations, human records, policies, regression runs and owner-only adoption |
| `views.py` | Read models for the screens: order summaries, the replayed decision with the facts it cites, the knowledge timeline |
| `extraction/`, `extraction_service.py`, `review_service.py` | Note extraction with deterministic checks, provider protocol (Anthropic and an OpenAI adapter), spending ledger and the review queue. Not reachable from the web app |
| `demo.py` | The synthetic Tiruppur demo, its nine frozen cases and the idempotent seeder |

HTTP lives in `decisions_api.py`, `decisions_imports_api.py` and `decisions_review_api.py`, all under `/api/v1/decisions` and scoped by a required `workspace_id` query parameter.

## Guarantees and where they are enforced

| Guarantee | Enforced by |
| --- | --- |
| Facts are never edited or deleted | PostgreSQL triggers reject UPDATE, DELETE and TRUNCATE on `facts` and the other ledger tables |
| No backdating | A check constraint `valid_from <= known_at`; `known_at` comes from the database clock. Authoring `known_at` is refused on every HTTP path and allowed only for seeding and the command line |
| Same inputs, same decision | The decision digest is a hash of canonical JSON; replay property tests shuffle the facts |
| A stock conflict cannot be auto-accepted | The gate returns CONFLICTING and the recommendation rules turn any non-READY gate into NEEDS_REVIEW |
| A model never decides | Replay imports no provider and no decision route calls one (a test fails if one does); extraction output is verified by deterministic checks and goes to review if any check fails |
| Policy adoption is deliberate | Adoption needs the workspace owner role from the membership row, a stored and complete regression run, an unchanged suite, and a written acknowledgement for each regressed case |
| Workspaces do not leak | Every read is scoped by membership; an unreadable workspace answers 404. Only the public demo is readable without signing in, and it accepts no writes |

## Frontend (`frontend/src/`)

- `pages/decisions/`: the order list, the order workbench, the knowledge timeline, the replay lab, the review queue and imports.
- `components/decisions/`: gate banner, freshness badge, constraint card, fact drawer, record form, knowledge scrubber, policy diff, regression table, span highlight and the workspace picker.
- `lib/decisions.ts` is the only module that calls the decisions API. It speaks the backend's generated contract (`lib/generated-api.ts`) and hands the pages the shapes they render.
- Times are stored and sent in UTC and shown in India Standard Time.

## Tests

- `backend/tests/decisions/`: unit, property (Hypothesis), database and HTTP tests. Tests use fresh workspaces because the ledger cannot be cleaned up.
- `frontend/e2e/decisions-*.spec.ts`: browser specs with mocked API responses in the real wire shapes, including an accessibility check on every page.
- `frontend/e2e/decisions-live.spec.ts`: one spec against the real API and the seeded demo.
- CI also checks that the committed OpenAPI file and generated types match the code, and that the case labels, the engine and the declared comparison agree (`decision-cases-verify`).

See [PRODUCT.md](PRODUCT.md) for scope, [the plan](docs/v2/PLAN.md) for the approved design and [RELEASE_STATUS.md](RELEASE_STATUS.md) for what has and has not been verified.
