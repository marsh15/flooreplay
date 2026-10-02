# AI trust evaluation and review

FloorReplay provides semantic review controls, a grounding contract, precedent comparisons and a frozen comparison experiment. Independent human review and fresh live-provider comparisons remain pending, so these controls do not establish that AI improves supervisor decisions.

## Review an exact draft

The requester or an owner explicitly shares a completed draft from the investigation page. An authenticated reviewer opens it in the evaluation page's claim-support inbox. The review packet retains the output digest, deterministic analysis, evidence revision, cutoff, current citations and historical excerpts. Private questions, request keys, spending reservations and provider attempt details remain outside the shared packet. Only the requester or an owner can look up a private AI run through the ordinary lookup interface.

Record supported, unsupported or insufficient-evidence judgments with rationale and optional attribution, unsupported-conclusion, omitted-contradiction, appropriate-abstention and useful-next-check flags. Whole-draft assessments separately record omissions, abstention, usefulness, reviewer limitations and qualifications. These judgments assess factual support. They do not authorize a recovery action.

Annotations are append-only and bind the exact output digest. Interrupted retries reuse the same fields and request identity. Reports show denominators and disagreements using each actor's latest annotation per claim, while retaining earlier history. Consensus counts exclude disputed claims. Human identity, qualifications and independence are declarations, not independently verified credentials. The generation requester cannot declare an independent review of their own draft. Completion requires declared independent human claim coverage and a whole-draft assessment; it does not certify manufacturing expertise or operational value.

[Qualified human review protocol](ai-claim-review-protocol.md) defines the remaining external review. Five recorded OpenAI smoke runs are packaged in [the review export](../backend/evaluation/openai-smoke-review-packet-v1/README.md). The separate preliminary AI audit covers four structured factual claims, but human-reviewed cases and claims remain zero. Its judgments cannot replace a practitioner's review. Reviewer disagreements cannot be measured until independent annotations exist.

## Quantities and hostile records

Prompt `incident-grounding-v7` and schema contract `typed-tasks-v2` preserve quantities as metric IDs and exact source-field references rendered by the application. Narrow ordinary phrases such as "one source" are allowed. Invented measured quantities, times and numeric identifiers remain blocked. Exact-token checks prevent a cited identifier from masking a longer invented identifier; dotted source IDs remain addressable. Free prose in limitations, next checks, abstention and recovery prerequisites is also checked.

Source records are explicitly untrusted data in the prompt. Tests preserve contrary evidence, keep backend secrets outside the packet, and reject invented numeric or out-of-packet references. They also demonstrate that a citation-valid allegation can remain semantically unsupported. These checks do not prove that a live model always resists hostile instructions, attributes claims correctly or abstains appropriately.

## Frozen challenge and comparison

[The fresh release](../backend/evaluation/ai-trust-fresh-v1/README.md) contains ten manually composed synthetic cases authored by a separate AI agent without reading the old generator, development templates or exposed locked cases. Inputs and a separate blind rubric were hashed before revised-validator exposure. Cases include simultaneous disruptions, conflicting testimony, misleading history, incomplete intervals, harmless events, insufficient evidence, instructions embedded in notes, blame, copied text and disclosure attempts. No practitioner cases or independent human authorship are claimed.

The same case author prepared and separately froze ten offline candidate drafts without inspecting the revised validator implementation. Their first structural check accepts seven and rejects three: one for numeric prose and two for uncited claims. The original failures are retained in `offline-contract-check.json`; no validator or candidate tuning followed that check. This is an offline contract result, not OpenAI performance or human semantic support. These exposed candidates are not an untouched future holdout.

The comparison ledger contains ten measured deterministic runs. Thirty evidence-only, lexical and hybrid AI slots remain pending, with semantic support unavailable. The report preserves per-mode attempted/completed counts, claim denominators, measured latency, actual known cost, errors and missing observations. Missing AI measurements are null or pending, never zero-cost successful runs. Lexical AI uses an eligible pinned corpus without a query embedding. Hybrid AI uses an already indexed pinned corpus. Neither may use current lineage, future evidence or held-out challenge cases as precedent.

Run offline verification from `backend/`:

```sh
uv run python -m flooreplay.trust_evaluation verify
uv run python -m flooreplay.trust_evaluation report
```

Run live comparisons only after an owner, existing corpus and explicit permitted experiment limit have been selected:

```sh
uv run python -m flooreplay.trust_live \
  --release evaluation/ai-trust-fresh-v1 \
  --ledger evaluation/ai-trust-live/receipts.jsonl \
  --owner OWNER_USERNAME --corpus EXISTING_CORPUS_ID \
  --max-spend-inr PERMITTED_LIMIT
```

The live adapter refuses test databases and uses the configured shared allowance and existing accounts. It never tops up, publishes a corpus or indexes embeddings. Its persisted checkpoint bounds the resumed experiment and records identities before dispatch; uncertain operations are inspected rather than repeated. Generation and query-embedding reservations both count toward the experiment envelope and their existing allowance categories. Historical outputs are not reused as fresh-case results.

Execution metadata marks stored challenge incidents as locked evaluation data and records a separate effective-payload digest. Frozen observations remain unchanged. This prevents the challenge from entering ordinary browsing or future historical corpora. Receipt import records provenance and hashes; importing a JSON file alone does not independently authenticate provider execution.

## Precedent relevance

Comparisons show observed scope, stage, unit, established block categories, recorded production totals, differences, missing information and current/historical prerequisites. Comparisons report a window's output total without labeling it an intervention outcome. Confirmed causal mechanisms, actions actually taken and post-intervention causal effects are explicitly unavailable when absent from the pinned evidence. Private workflow outcomes are not leaked into public historical search. Empty eligible matches produce a visible no-useful-precedent result.

A qualified reviewer must still decide whether these comparisons help the current decision. Same-case support, useful next checks, omitted contradictions, latency and cost are needed before recommending an AI mode over the deterministic report.
