# Fresh synthetic trust comparison

The manifest freezes ten hand-composed challenge cases and a separate blind review rubric. An independent Codex subagent wrote them without reading the existing generator templates or exposed development/locked cases. The author is an AI agent with no manufacturing expertise or independent human review role. This synthetic challenge set does not estimate generalization or validate the product with customers.

The inputs were frozen before deterministic execution or exposure to the validator. manifest.json records the frozen file hashes. Do not edit the cases or rubric after exposure. Put changes in a new release, and disclose any prompt/validator tuning informed by these cases. Keep blind-review-rubric.json out of generation packets.

Run these commands from backend:

```sh
uv run python -m flooreplay.trust_evaluation verify
uv run python -m flooreplay.trust_evaluation deterministic
uv run python -m flooreplay.trust_evaluation report
```

The checked-in results.jsonl records ten actual local deterministic executions. The remaining thirty AI case/mode comparisons stay PENDING until real stored generation receipts are imported. This release includes no paid calls or fabricated model results. Semantic review remains null.

## Import actual generation receipts

Use one run per frozen case and evidence_only, lexical or hybrid mode. Keep the source case digest, original provider response/run identity, exact output and observed timing/cost. The adapter imports stored receipts; it does not execute a provider or attest that a caller-supplied receipt came from one. Verify the underlying provider artifact separately.

The JSON receipt needs these fields:

```json
{
  "case_id": "FRESH-01",
  "case_digest": "COPY_THE_EXACT_MANIFEST_CASE_DIGEST",
  "mode": "evidence_only",
  "run_id": "ACTUAL_SAVED_RUN_ID",
  "provider": "ACTUAL_PROVIDER",
  "model": "ACTUAL_MODEL_ID",
  "source_receipt": {"provider_request_id": "ACTUAL_REQUEST_ID", "artifact": "ACTUAL_SAVED_ARTIFACT_PATH"},
  "output": {},
  "latency_ms": null,
  "cost_inr": null,
  "error": null,
  "semantic_review": null
}
```

Replace placeholders with actual receipts; never import this illustrative object as a result. Preserve null for unmeasured latency/cost. For a failed request, preserve its error and receipt identity instead of inserting a valid draft. Include packet digest, prompt/configuration identity, corpus release and retrieval candidates in the receipt when present. Run `uv run python -m flooreplay.trust_evaluation import --receipt ACTUAL_RECEIPT.json`. The adapter saves the source file digest, exact output digest and claim denominator in an append-only ledger. It rejects replacing a case/mode result; use a separate ledger for another experiment.

The report compares the same frozen cases under deterministic, evidence_only, lexical and hybrid modes. It includes pending slots, recorded errors, latency/cost and claim denominators. Citation membership and output validity are separate from semantic support. Deterministic output has no model claim denominator.

FRESH-03 includes an explicitly misleading historical candidate. A real retrieval comparison must record its actual candidate set and corpus identity; do not substitute this intended distractor and describe it as a retrieved result. The privacy lure uses synthetic text and cannot prove private workspace isolation.

Use `uv run python -m flooreplay.trust_evaluation review-packet` to prepare exact imported outputs, claim paths and current evidence for a qualified human reviewer. It excludes the blind rubric and leaves identity, qualifications and judgments null. Historical citation records must be supplied from the underlying saved retrieval packet before judging those claims. The [human review protocol](../../../docs/ai-claim-review-protocol.md) defines dimensions, denominators and disagreement policy.

## First offline contract check and live execution

The separately frozen offline candidates were authored by the same AI case author without inspecting the revised validator implementation. The first check accepts seven of ten candidates and preserves three original failures: one numeric-prose failure and two uncited claims. These results do not come from a live provider or independent human review. The validator digest in offline-contract-check.json remains unchanged after exposure; do not tune on this result and call it an untouched future holdout.

The optional flooreplay.trust_live command requires an explicit experiment limit, existing owner/corpus and configured shared allowance. It refuses test databases, creates no allowance or index, preserves a fixed checkpoint envelope and does not repeat uncertain provider calls. Generation and hybrid query-embedding charges are recorded. Stored execution metadata marks cases locked and records an effective-payload digest separately, preserving frozen observations while preventing their reuse in public browsing or historical retrieval. See docs/ai-trust-evaluation.md for invocation and remaining human/live acceptance gates.
