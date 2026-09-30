# Local demonstration

The recording walks through a synthetic incident, switches the evidence revision, inspects a source record, and submits and approves a proposal using an authenticated disposable owner. The approval records a human decision and executes no factory action.

The final screens show OpenAI unavailable and the release dataset integrity report. No paid provider calls are made. The dataset has 120 historical episodes, 30 development investigations and 30 locked investigations; its 60 arithmetic and structure checks are distinct from a semantic leakage audit or independent claim-support review, which remain pending.

Artifacts produced by the recording:

- `flooreplay-local-demo.webm`: browser recording.
- `incident-workbench.png`: deterministic workbench screenshot.
- `evaluation.png`: release integrity and historical evaluation screenshot.
- `recording-manifest.json`: incident and analysis identity, cutoff and verification limits.

Historical Qwen output remains labeled as an archive. It does not establish OpenAI quality. This recording establishes the local browser workflow; actual OpenAI generation, embeddings, independent semantic review and a hosted smoke test require separate evidence.

To record against an isolated application database, set `E2E_BASE_URL`, `E2E_API_BASE`, `E2E_USERNAME` and `E2E_PASSWORD` in the shell, then run `node docs/demo/record-demo.mjs` from the repository root. Credentials should identify a disposable owner. The password field is masked, session tokens stay in browser memory, and the recorder refuses to generate a draft when provider generation is enabled. The recording creates a fresh deterministic analysis and appends its submission and approval records to the isolated database.
