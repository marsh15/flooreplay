# Release evidence, September 30, 2026

The implementation has completed offline software verification. The whole release is not accepted yet. Actual OpenAI generation/embeddings, model evaluation and human semantic review require the backend key and new measurements. Hosting remains local by the user's choice.

| Gate | Evidence | Status |
|---|---|---|
| Incident accounting/imports | Cutoff, correction graph, conflicting replacements, scope, watermark, coverage, metric provenance and bound previews have focused tests | Verified offline |
| Authorization | Direct HTTP checks cover anonymous denial, owner/reviewer separation, Argon2id hashes, token hashes, expiry, logout and disabling in local/public modes | Verified |
| Spending/reliability | Mocked provider calls test repair/idempotency, uncertain reservations, two-slot concurrency, category ceilings, immutable corpus/cache and private run lookup | Verified offline |
| Backend | 169 pytest tests, Ruff and mypy pass | Verified |
| Frontend | Full 21-test browser suite, lint/build, memory sessions and interrupted request recovery pass | Verified |
| Dataset | 180 episodes, exact 120/30/30 split, 24 evidence structures, 60 frozen arithmetic/structure cases pass | Verified structurally |
| Independent semantic labels | Manufacturing-expert annotation, semantic paraphrase leakage review and new-response claim support | Pending |
| Historical provider artifacts | Original Qwen identity, packets, results and review records are preserved | Verified |
| OpenAI | Official SDK adapters and typed contracts tested with mocks; no configured server key, no real calls | Pending live verification |
| Hybrid quality | Exact cosine/lexical fusion and cache/pinning tested with mock embeddings | Pending real indexing/evaluation |
| Fresh deployment database | Full pgvector migrations on a new isolated PostgreSQL database, seed twice, second run creates zero artifacts | Verified |
| Saved bundles | Fresh-database export has exactly the same content-digest manifest as the working test-database export | Verified |
| Packaging | Backend/frontend images built with frozen installs before final review fixes; Compose configuration validates | Build approach verified; final runtime pending |
| Container startup | Docker failed creating containers with containerd metadata input/output errors while host storage had approximately 4.4 GiB available | Blocked by local Docker storage |
| Hosted release | Render/Neon configuration, secrets, repository remote and deployment URLs are not connected | Pending, retained locally |

## Remaining acceptance work

Configure `FLOORREPLAY_OPENAI_API_KEY` only in the backend environment. Create the real owner/reviewer accounts through the prompted CLI. Run the five-case smoke stage, correct any blocking defects, then run the ten-case pilot and thirty-case locked evaluation. Publish and index a cutoff-bound corpus explicitly, then repeat on the same frozen labels with hybrid retrieval. All calls share the ₹500 allowance.

Review actual new claims separately and record support labels attached to their response/run identities. Qwen support labels cannot be reused. Structural checks alone do not establish causal or semantic correctness.

Restore Docker storage health and run the documented complete-stack smoke checks. No other project's containers, images or volumes were deleted to repair the runtime. Both FloorReplay image builds finished before startup failed. The native API/frontend workflow is verified independently.

Public deployment requires the user to change the local-only hosting preference and provide the Render/Neon configuration. Run final authenticated and read-only smoke tests using the actual URLs before claiming hosted readiness.

## Acceptance criteria

AC-01, AC-03, AC-04, AC-06 through AC-11 and AC-13 have implementation plus offline proof. AC-05 has pinned-corpus and exclusion proof with mock embeddings; its actual retrieval-quality gate is pending. AC-02 and AC-12 require real OpenAI calls and review. AC-14 remains pending container-start and hosted smoke evidence. No paid evaluation or public OpenAI example is presented as completed.
