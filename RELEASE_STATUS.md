# Release evidence, September 30, 2026

The implementation has completed offline software verification. The whole release is not accepted yet. Actual OpenAI generation and embedding indexing now have provider receipts. Smoke and pilot passed; locked evaluation stopped at a validation failure. Human semantic review is still pending. Hosting remains local by the user's choice.

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
| OpenAI | Live pinned-model responses: evidence-only smoke 5/5 and pilot 10/10; locked stopped at 24 valid of 25 attempted, 30 planned | Live verified; locked gate blocked |
| Hybrid quality | Live embeddings indexed 131 pinned historical cards; hybrid smoke 5/5 structurally valid | Live smoke verified; quality review pending |
| Fresh deployment database | Full pgvector migrations on a new isolated PostgreSQL database, seed twice, second run creates zero artifacts | Verified |
| Saved bundles | Fresh-database export has exactly the same content-digest manifest as the working test-database export | Verified |
| Packaging | Backend/frontend images built with frozen installs before final review fixes; Compose configuration validates | Build approach verified; final runtime pending |
| Container startup | Docker failed creating containers with containerd metadata input/output errors while host storage had approximately 4.4 GiB available | Blocked by local Docker storage |
| Hosted release | Render/Neon configuration, secrets, repository remote and deployment URLs are not connected | Pending, retained locally |

## Remaining acceptance work

The backend key is configured locally and has not been committed. Recorded usage is ₹7.0519068 of ₹500, including failed prompt-development runs. Create the real owner/reviewer accounts through the prompted CLI. Evidence-only smoke and pilot are complete under prompt incident-grounding-v6. The locked stage stopped on a response containing the numerical phrase “one source,” rejected by the unchanged validator after both attempts. Do not tune against these exposed locked outputs and claim the original set remains untouched; document any subsequent development and use a fresh holdout for an independent acceptance result. Publish and index a cutoff-bound corpus explicitly, then repeat on the same frozen labels with hybrid retrieval. All calls share the ₹500 allowance.

Review actual new claims separately and record support labels attached to their response/run identities. Qwen support labels cannot be reused. Structural checks alone do not establish causal or semantic correctness.

Restore Docker storage health and run the documented complete-stack smoke checks. No other project's containers, images or volumes were deleted to repair the runtime. Both FloorReplay image builds finished before startup failed. The native API/frontend workflow is verified independently.

Public deployment requires the user to change the local-only hosting preference and provide the Render/Neon configuration. Run final authenticated and read-only smoke tests using the actual URLs before claiming hosted readiness.

## Acceptance criteria

AC-01, AC-03, AC-04, AC-06 through AC-11 and AC-13 have implementation plus offline proof. AC-05 has pinned-corpus and exclusion proof with mock embeddings; its actual retrieval-quality gate is pending. AC-02 and AC-12 require real OpenAI calls and review. AC-14 remains pending container-start and hosted smoke evidence. Paid smoke and pilot measurements are recorded; locked acceptance and independent claim support are incomplete. No public OpenAI example is presented as completed.

## Live provider artifacts

See `backend/evaluation/openai-live-evidence-v4/` for the frozen smoke, pilot and stopped locked stage; `backend/evaluation/openai-live-hybrid-v1/` for hybrid smoke; and `backend/evaluation/openai-live-usage.json` for settled usage. Earlier evidence-v1 through v3 runs retain the failed prompt iterations. Every successful attempt records provider request/response identities, actual token usage and model identity. These are structural results, not independently reviewed support labels.
