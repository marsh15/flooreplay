# Architecture

The React/Vite frontend calls FastAPI. PostgreSQL stores immutable incident revisions, source bytes, deterministic analyses, append-only reviews, accounts and sessions, AI runs, spending reservations, frozen corpus releases and pgvector embedding artifacts.

## Evidence and calculation boundary

`incident_import.py` validates source rows and binds preview identity to bytes, interpretation, scope and normalized records. `incident_engine.py` filters by cutoff, validates correction relationships, unions explicit line blocks and accounts for complete 15-minute final-good buckets. It derives hypothesis support from visible typed links and contradictions. Metric descriptors preserve units, formulas, intervals and source references.

`incident_service.py` pins incident and corpus identities before storing a report. Proposal review holds revision/idempotency locks and records the authenticated account ID supplied by the API. The model cannot approve a proposal or modify measured production.

## Authentication

`auth.py` stores Argon2id password hashes and random bearer-session token hashes. The API applies the same owner/reviewer checks in local and hosted modes. Sessions expire in eight hours and disabled accounts lose access. Login and paid-operation limits persist in PostgreSQL. Browser tokens exist only in memory.

## Paid execution

`ai_runs.py` persists the request identity, task, configuration and evidence packet before executing. `spending.py` reserves the maximum cost and one of two global slots atomically under a transaction-level lock. The transaction commits before `openai_provider.py` contacts OpenAI. Calls use the official SDK, bounded timeouts, structured outputs, `store=false` and no implicit retries. A semantic repair shares the two-attempt limit.

`incident_ai.py` validates task contracts and reference membership. Generated numeric prose is rejected; metric IDs select values the frontend renders. Current and historical citations remain separate. Refusals, incomplete output, errors and uncertain calls are stored as terminal results. A restart never silently repeats a possibly billed operation. Lookup by request key supports browser recovery.

## Retrieval

`retrieval.py` publishes an immutable list of eligible historical revisions and content digests. Owner indexing is explicit and paid. Embedding cache identity includes normalized content, provider model, dimensions and preprocessing version. Hybrid queries search the pinned release and combine exact cosine with lexical candidates using reciprocal rank fusion. Current incident lineage, future observations and dev/locked cases are excluded.

## Delivery and evidence

Compose provides pgvector/PostgreSQL, an API and an nginx static frontend with SPA rewrites. Vercel serves the static frontend; Render runs the API with Neon storage. The frontend uses the absolute HTTPS API base, and the API allows exact frontend origins. CI uses a disposable database and mocked provider calls. Live model evaluation and actual hosted smoke evidence are separate release gates. `release_tools.py` exports canonical saved reports and a content-digest manifest; frontend types derive from exported OpenAPI.

Historical Qwen results remain archived evidence. Recorded OpenAI evidence-only smoke and pilot, and hybrid smoke, measure structure and retain provider receipts. The locked stage stopped at a validation failure. Independent human review of these outputs remains pending; historical Qwen support labels cannot establish current-provider quality.

## Workflow completion

Proposal submission and approval record a judgment against a pinned analysis. They do not record factory execution or prove incident resolution. `incident_workflow.py` stores assigned checks, append-only activities, outcome records, revision-bound resolution and actor-scoped idempotency receipts. Workflow mutations serialize under the same incident advisory lock as source publication. Task updates also use row locks and an expected-update timestamp. Identical request identities return their saved results; a changed payload conflicts.

Owners and reviewers can read the workflow, assign checks, comment and record resolution. The assignee or owner starts, responds to and completes a check. The creator or owner cancels, reassigns or changes its deadline. Terminal checks accept comments but reject other edits. A source response publishes an immutable revision and raw source artifact. Completion records an action and assessment; it does not establish causation or incident resolution. Resolution requires terminal checks and a completed outcome, pins the current revision and becomes effectively open when new evidence supersedes that revision.

Task metadata and assignee lists require authentication. Published source responses become evidence in the existing public synthetic incident reports. This is not a private customer workspace boundary. The frontend presents latest workflow state separately from the selected historical report and includes its cutoff, open checks and ownership in the printable handover. See [IMPROVEMENT_PLAN.md](IMPROVEMENT_PLAN.md) for the deliverables and external acceptance gates.

## Current investigation controls

Revision comparisons derive earlier metrics, newly available and corrected sources, hypothesis changes and proposal-review reminders from pinned reports. State-aware next checks refine questions when evidence already establishes a block. The frontend separates engineering fixtures from curated incidents and provides filters and pagination. Claim annotations support all four claim-bearing output structures and preserve the output digest, rationale, authenticated actor and durable receipt. The printable deterministic report includes revision and report identity and excludes the AI panel. Saved report bundles use engine incident-v4.

## CSV interpretation

The CSV mapping layer describes source headers and sample rows, validates explicit canonical-to-source column mappings and constant field defaults, and normalizes those selected values through the existing production, operation and note profiles. Mappings cannot reuse a source column, name unknown fields or combine a mapped field with a default. Original source bytes and interpretation remain bound to the preview digest and publication artifact. Canonical JSON/JSONL imports retain their existing path. The third pass is verified locally on October 1, 2026; it does not convert cumulative totals or accept XLSX.

## Semantic review and trust comparison

Completed AI drafts remain private until their requester or an owner deliberately publishes an exact output digest for review. `semantic_review.py` returns a sanitized packet, preserves append-only claim judgments and whole-draft assessments, and reports each actor’s latest judgments plus disagreement history. Qualifications and independence remain self-declared. Legacy annotations migrate as unspecified reviewers; they do not become verified human reviews. Private run lookup continues to require requester/owner access.

Grounding prompt v7/schema v2 allow narrow ordinary phrases while application references carry quantities and source values. Exact token checks, free-prose checks and explicit untrusted-source instructions enforce a bounded structural contract, not semantic truth. Lexical retrieval uses a pinned eligible corpus without query embedding. Precedent comparisons expose recorded operational conditions and explicitly missing mechanism/intervention/outcome evidence.

`trust_evaluation.py` verifies frozen release hashes and records same-case deterministic and imported AI receipts. `trust_live.py` dispatches only under an explicit persisted budget envelope, existing owner/corpus and configured shared allowance. It refuses test databases, never auto-indexes or tops up, and does not repeat uncertain operations. Held-out observations retain their frozen bytes while stored execution metadata excludes them from public browsing and future corpora. See [AI trust evaluation](docs/ai-trust-evaluation.md).
