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
