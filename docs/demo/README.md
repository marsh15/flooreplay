# Local demonstration

The recording follows a synthetic incident through evidence revision changes, source inspection, proposal submission and approval. It uses an authenticated disposable owner. Approval records a human decision; it does not execute a factory action.

The final screens show that OpenAI is unavailable and display the release dataset integrity report. The recording makes no paid provider calls. The dataset has 120 historical episodes, 30 development investigations and 30 locked investigations. Its 60 arithmetic and structure checks do not cover semantic leakage or independent claim support; those reviews remain pending.

Artifacts produced by the recording:

- `flooreplay-local-demo.webm`: browser recording.
- `incident-workbench.png`: deterministic workbench screenshot.
- `evaluation.png`: release integrity and historical evaluation screenshot.
- `recording-manifest.json`: incident and analysis identity, cutoff and verification limits.

Historical Qwen output is labeled as an archive and does not establish OpenAI quality. This recording verifies the local browser workflow. Actual OpenAI generation, embeddings, independent semantic review and a hosted smoke test each require separate evidence.

To record against an isolated application database, set `E2E_BASE_URL`, `E2E_API_BASE`, `E2E_USERNAME` and `E2E_PASSWORD` in the shell, then run `node docs/demo/record-demo.mjs` from the repository root. Credentials should identify a disposable owner. The password field is masked, session tokens stay in browser memory, and the recorder refuses to generate a draft when provider generation is enabled. The recording creates a fresh deterministic analysis and appends its submission and approval records to the isolated database.
