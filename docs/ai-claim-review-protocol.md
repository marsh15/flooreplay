# Independent claim-support review

No qualified human review is recorded for the fresh AI-authored challenge set. Its blind rubric lists expected review questions. It contains no measured claim-support labels. An AI preliminary review, if performed, must be labeled AI and reported separately. It cannot satisfy the requirement for human review.

## Prepare the review packet

Freeze the case release, generation run, provider/model and prompt/configuration identities, exact output digest, evidence packet digest and retrieval corpus/candidates. For every claim, provide its canonical path and text beside every cited record with scope, occurrence time, availability time and revision. Include contradictions and missing evidence. Include the deterministic report for comparison. Do not treat it as an answer key. Exclude the blind rubric from generation inputs.

Recruit a reviewer with relevant manufacturing or operational experience. Record the person's qualifications and independence from the project author. Obtain permission to retain anonymized assessments. Let the reviewer work without seeing the model's proposed evaluation labels or another reviewer's judgments.

## Assess each actual claim

| Dimension | Record |
|---|---|
| Attribution | Do the citations refer to the right incident, source, time and scope? Record each error. |
| Factual support | Supported, unsupported, contradicted or insufficient evidence, with rationale and exact references. |
| Omitted contradictions | Relevant conflicting observations the answer missed, with references. |
| Abstention | Whether the answer should abstain or ask a check, and whether it does so. |
| Useful next check | Whether a proposed check can answer a remaining uncertainty; assess usefulness separately from factual correctness. |

Use explicit denominators: claims reviewed/claims available, supported/claims reviewed, contradictory or unsupported/claims reviewed, useful checks/checks reviewed. Record missing assessments instead of dropping them. Count each claim once in a dimension; multiple citations are not multiple claims. Review actions, summaries and note assertions as well as investigation findings. Use each output's exact structure.

For failures and refusals, record whether the abstention was appropriate. Keep schema failure, provider error and semantic unsupported output separate. Report latency and actual cost beside quality, without filling unknown values with zero.

## Handle disagreement

Have reviewers label independently where possible. Preserve original judgments and rationales. Record agreement denominators before an adjudicator reviews disagreements. The adjudicator records a separate decision and qualifications; adjudication must not overwrite the original labels. With one reviewer, say that no inter-reviewer agreement was measured.

Any output or case modification creates a new identity. Do not reuse labels after an output changes. Once exposed cases drive a prompt or validator change, describe the experiment as development on an exposed set and obtain a new independently authored holdout for acceptance. Ten AI-authored synthetic cases cannot establish factory usefulness, broad generalization or safe handling of private customer records.

The [actual smoke packet](../backend/evaluation/openai-smoke-review-packet-v1/README.md) is ready for review. It contains five recorded runs, four structured claim objects, 28 text units and six next checks. Its preliminary AI assessment is separate and should not be shown as an answer key to human reviewers. Zero cases and claims have qualified human labels.
