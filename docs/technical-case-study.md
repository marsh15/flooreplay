# FloorReplay: production investigations with inspectable evidence

FloorReplay helps investigate production shortfalls. It shows what the records establish, what remains uncertain and what someone should check next. Current demonstrations use synthetic records. No factory pilot, reduced downtime or financial benefit has been measured.

## Problem, integration and architecture

Production logs, stoppage records and notes can disagree, arrive late or describe overlapping disruptions. FloorReplay preserves source revisions, explicit CSV mappings, original and normalized previews, a knowledge cutoff and the deterministic calculation. The cutoff means the latest time a record could have been known when the investigation was saved. Corrected imports create new revisions rather than replacing the original evidence.

Calculation coverage, reported evidence availability, investigation state, assigned checks and incident resolution are separate. Completing arithmetic does not establish causality. Assigned actions have ownership and recorded outcomes; closure is a separate decision. Deep links retain saved report identities after subsequent edits. The supervisor print report carries findings, evidence, uncertainty, actions and ownership outside the application.

AI drafts reference permitted evidence and typed metrics. Numeric and citation checks protect the output contract but cannot establish semantic support. Reviewers inspect the exact output alongside cited and uncited pinned records. Their judgments and rationales are append-only, and the review shows disagreements. Factual support and operational approval remain separate. Historical retrieval pins its corpus/cutoff, excludes current lineage and held-out cases, and compares observed conditions and missing intervention/outcome evidence. An empty useful-match result is acceptable.

In the browser-only safe demo, visitors can inspect evidence, assign a check and record an outcome. The demo requires no account and makes no shared mutations or paid requests. See the [architecture](../ARCHITECTURE.md), [workflow](incident-workflow.md), [CSV contract](csv-import-mapping.md) and [product scope](../PRODUCT.md).

## Measured results and limits

The production-ownership release passes 241 backend tests and 62 browser scenarios, plus lint, type checks and build. Six rollback-harness guard tests pass. The code and verification boundaries are recorded in [release evidence](../RELEASE_STATUS.md). These results describe the reviewed release snapshot; parallel uncommitted edits are excluded.

The fifth-priority code release `a3b7c23`, documented in `04e0466`, passed 225 backend tests and 58 browser scenarios, plus lint, type checks and build. These are local software checks. The production-ownership pass has separate acceptance/recovery artifacts; only their completed entries establish measurements.

The [AI trust report](ai-trust-evaluation.md) records ten frozen synthetic challenge cases and four comparison modes. Ten deterministic receipts exist; thirty fresh AI comparisons remain pending. The first frozen offline contract check accepted seven of ten candidate drafts, rejected one for numeric prose and two for uncited claims. Failures and hashes remain preserved, with no validator tuning after exposure. These are offline contract results, not live-provider accuracy.

Five historical OpenAI smoke outputs have preserved packets and receipts. The preliminary independent AI audit is explicitly AI review. Zero claims have qualified independent human review. Semantic support, omissions, useful next checks and practitioner precedent usefulness remain unproven. See [review protocol](ai-claim-review-protocol.md) and [frozen challenge](../backend/evaluation/ai-trust-fresh-v1/README.md).

## Learning from failures

Inspection found confusing completion labels, test fixtures in the main experience, generic precedent explanations and a numeric restriction that rejected "one source." The implementation separates status dimensions and fixture browsing, presents concrete precedent conditions, permits narrow ordinary phrases and retains strict quantity checks. The stopped historical locked evaluation remains preserved under its original identity. It was not relabeled as fresh acceptance.

Browser verification exposed a report-identity navigation race, fixed by pinning the saved report before navigation. Interrupted annotation retries preserve request identity and exact output. Guidance and the account-free practice flow address observed initial confusion, but human first-visit comprehension and supervisor report usefulness still require the [validation protocol](first-visit-validation.md).

## Production ownership

The [recovery drill](recovery-drill.md) documents isolated restore verification, every-table content digests, synthetic fixtures, measured timings and rollback compatibility. The old public-data release cannot be a compatible rollback after introducing confidential workspaces: removing authorization would expose private data. An additive schema alone is insufficient.

Private records now use member-scoped workspaces. HTTP reads, search, evidence, exports, saved reports, retrieval and review packets share that boundary. Factory-local IDs and retry keys are namespaced; original external IDs and source bytes remain preserved. Legacy records with uncertain ownership are quarantined rather than guessed public. Administrative CLI access is a trusted boundary, not an ordinary customer interface.

The actor-scoped Operations view links request IDs, provider runs/receipts, latency, failures and retained spending reservations. It provides alerts in the application and a runbook. External pager delivery and fleet monitoring are unconfigured. Durable provider state and the bounded request deadline remain in the request path; a queue would not resolve ambiguous billing.

The [hosted HTTP receipt](evidence/hosted-2026-10-01.json) and [browser observations](evidence/hosted-browser-2026-10-01.json) identify the actual public URLs and deployed commit `f5bab391`. Public reads, deterministic analysis, permission denials, deep links and simulated browser fallback passed. That deployment predates the private-workspace release. Authenticated hosted acceptance and hosted restart persistence remain pending a designated account/environment. Do not treat these observations as acceptance of the new release.

The [restore receipt](evidence/recovery-final-2026-10-02.json) verified all 36 tables and unchanged source data in 34.04 seconds; restore itself took 0.98 seconds. The [API rollback](evidence/application-rollback-2026-10-02.json) verified the previous compatible API, private access denials and persisted review/export. These are local synthetic measurements, not production RTO/RPO.

Further review found global identifier collisions between factories and a stale private archive view after logout. Workspace namespaces and an authentication-boundary remount corrected those defects, with explicit regressions. A legacy-backend compatibility check pauses private imports until workspace support is available.

Hosted acceptance, monitoring and private-workspace protections should be assessed through actual reports/tests. A public read-only smoke or local restore does not establish the authenticated hosted workflow. Real deployment also requires operational owners, confidential-data boundaries, qualified review and measured user outcomes.

## Contribution and evidence

This repository records AI-assisted implementation directed by the project owner. The documented work spans evidence/revision contracts, deterministic calculations, imports, workflow, AI grounding/review, evaluation, demo guidance and operational controls. Commit history and artifacts establish the implementation; they do not establish which lines the human personally wrote. The owner should describe their actual role in requirements, coding, review and decisions when presenting the project. This account makes no unsupported claim about personal contribution, customer benefit or practitioner qualifications.

A hiring reviewer can examine the saved example, safe demo, architecture, tests and linked evidence without a narrated tour. The software and its documented limits are available for review. Whether AI improves real factory decisions remains an open experiment.
