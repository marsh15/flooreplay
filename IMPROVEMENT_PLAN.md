# FloorReplay improvement plan

Prepared September 30, 2026 from the supplied 36-item review. The intended workflow is a production supervisor importing imperfect records, investigating a sewing-line shortfall, assigning evidence checks, recording responses and measuring whether the investigation helped.

This is an ordered backlog, not a claim that all items are implemented. Synthetic tests establish bounded software behavior. Practitioner usefulness, confidential-data readiness and independent AI support need separate evidence. No interviews or pilot results are recorded yet.

## Delivery order

1. Correct the product story and make the existing example understandable. Keep engineering fixtures outside the default supervisor library.
2. Refine next checks, compare revisions and provide printable deterministic reports in this pass. The second pass adds assigned evidence checks, responses, outcomes and shift handover, verified locally on October 1, 2026. Keep approval, completed action and resolved incident distinct.
3. Next, reduce import preparation through examples and explicit column interpretation. Preserve the raw input, preview digest and corrected revisions.
4. Enable claim annotation against the exact generated output. Repair any contract defect on development cases and use a fresh holdout for acceptance.
5. Obtain practitioner feedback before building broader integrations, calendars or plan revision behavior. Use the interview and pilot protocols below.
6. Record acceptance against the actual hosted release, then run a recovery drill and comparative pilot. Publish a case study after results exist.

## Deliverable ledger

The number maps to the original review. "Now" means a bounded deliverable in the current improvement pass; its implementation status belongs in release evidence. "Next" means a follow-up after the current pass. "External" needs people, credentials, systems or independent evidence unavailable from code alone.

| Idea | Order | Concrete deliverable | Acceptance evidence or gate |
|---|---|---|---|
| 1. Validate the problem | External | Practitioner interviews and anonymized decision log | Recurring problem identified independently; [interview protocol](docs/practitioner-interview.md) |
| 2. Pick a recurring job | Now | Supervisor shortfall investigation in product, entry flow and demo | First-time walkthrough with purpose and completion path |
| 3. Measure the existing process | External | Comparable spreadsheet/phone and FloorReplay cases | Actual timed observations, errors and assistance; [pilot template](docs/comparative-pilot.md) |
| 4. Correct documentation | Now | Product, demo, architecture, README and release evidence agree | No legacy workflow or unsupported release claims |
| 5. Explain the project | Now | Unscripted end-to-end explanation checklist in demo | Author traces and changes one real flow; demonstration still needs a person |
| 6. Assign and complete actions | Verified locally | Assignee, due time, status, comments and completion evidence | Authenticated user assigns, answers and closes a check; manual escalation records a reassignment reason; automated notifications remain follow-up work |
| 7. Request missing evidence | Verified locally | Specific requested fields and finding reference; response creates evidence | New revision reflects response; prior report remains unchanged |
| 8. Record outcomes | Verified locally | Action taken, completion time, observed output and supervisor assessment | Outcome preserves causal uncertainty and authorship |
| 9. Compare revisions | Now | Added/corrected sources, metric changes and stale proposals | User explains the change without mentally combining two reports |
| 10. Refine next checks | Now | Questions depend on supported and unresolved findings | Confirmed interval removes the redundant confirmation question |
| 11. Shift handover | Verified locally | Printable summary with open checks, owners and latest evidence time | Next supervisor can continue from the report |
| 12. Spreadsheet ingestion | Verified locally; overall browser runtime limitation recorded | Downloadable examples and explicit CSV column mapping/defaults with previews | Unfamiliar CSV imports without code changes; saved mappings, cumulative conversion and XLSX remain follow-up work |
| 13. Cumulative output | Next | Explicit delta/cumulative interpretation and preserved readings | Resets, duplicates and gaps remain traceable or unresolved |
| 14. Identifier reconciliation | Next | Reviewed alias map with original identity and version | Ambiguous matches stop for review |
| 15. Source health | Next | Latest import/observation, expected frequency, gaps, rejections and conflicts | User distinguishes delayed records from actual production loss |
| 16. One integration | External | Permitted incremental connector or clearly labeled simulator | Checkpoints, deduplication and interruption recovery against an accessible source |
| 17. Working calendars | Next | Breaks, shifts and planned downtime in production-time calculation | Break changes available-time calculation with visible assumptions |
| 18. Revised baselines | External | Interview-driven effective-time plan revisions | Original and approved revised commitments remain comparable |
| 19. Independent claim review | Human review pending | Actual five-run smoke packet and separate preliminary AI audit; shared review/report workflow | Four structured factual claims packaged, zero human-reviewed claims; qualifications, disagreements and limitations remain explicit |
| 20. Claim-review interface | Verified locally | Deliberately shared inbox, side-by-side citations, three judgments, flags, qualifications, whole-draft assessment and report export | Exact output identity, cross-user access controls, immutable retries and disagreement history |
| 21. Numeric prose contract | Implemented; live acceptance pending | Prompt v7/schema v2 allows narrow ordinary phrases and renders metric/source references | Development boundary tests pass; frozen offline candidates accepted 7/10 with original failures preserved; no fresh live-model acceptance claim |
| 22. Fresh evaluation cases | Frozen synthetic challenge; practitioner cases pending | Ten separately AI-authored varied cases, separate blind rubric and content hashes | Author did not read old templates/locked cases; no human authorship or generalization claim; exposed candidates cannot become an untouched future holdout |
| 23. Compare AI alternatives | Harness implemented; live/human measurements pending | Same-case four-mode ledger and explicitly budgeted live adapter using existing shared allowance | Ten measured deterministic slots, thirty AI slots pending; support/usefulness unavailable until actual generation and qualified review |
| 24. Precedent relevance | Implemented; practitioner usefulness pending | Observed scope/stage/block conditions, production totals, prerequisites and missing causal/intervention/outcome evidence | Cutoff/lineage/holdout exclusion and no useful matches tested; relevance still needs a qualified reviewer |
| 25. Hostile source text | Development boundary checks; live review pending | Untrusted-source prompt, preserved contradictions, secret exclusion and adversarial challenge cases | Structural failures are visible; citation validity is not treated as semantic support or proof of injection resistance |
| 26. Guided first visit | Implemented; visitor validation pending | Purpose statement, guided example, contextual cutoff explanation and safe practice completion path | Browser flow checks establish controls; unfamiliar visitor comprehension needs the [first-visit protocol](docs/first-visit-validation.md) |
| 27. Separate status meanings | Implemented | Separate calculation, reported source availability, investigation and action states | Authenticated workflow facts remain distinct from arithmetic; anonymous/offline state stays unavailable |
| 28. Hide evaluation fixtures | Implemented | Curated library, engineering view, pagination and line/date/evidence/assignee/open-action filters | Workflow filters require sign-in and do not expose private ownership in public browsing |
| 29. Safe interactive demo | Implemented; visitor validation pending | Explicit browser-only guided simulation with evidence inspection, assignment, outcome and reset | No account, shared mutation or provider request; unfamiliar human completion still needs observation |
| 30. Supervisor exports | Implemented; supervisor validation pending | Readable printable findings, evidence, uncertainty and authorized action ownership; pinned report and latest workflow separately identified | Print/mobile checks establish rendering; outside-app usefulness and Tamil terminology needs require supervisors |
| 31. Hosted acceptance | External | Dated commit/URL report for login, roles, import, review, export and recovery | Actual authenticated hosted observations, not configuration tests |
| 32. Monitoring | Next | Searchable operation IDs, failures, latency, import health and allowance | Injected failure can be traced; actionable alert destination configured |
| 33. Long-running operations | Next | Inspect current durable requests under interruption/concurrency | Add worker only if evidence warrants it; no duplicate possibly billed request |
| 34. Recovery drill | External | Restore isolated database and compatible rollback | Revisions, accounts, annotations, embeddings and ledger verified; elapsed recovery recorded |
| 35. Private factory data | Next, before pilot | Demo/private workspace separation with read/export/search enforcement | Cross-workspace denial tests pass before confidential data ingestion |
| 36. Technical case study | External | Problem, decisions, failures, outcomes and contribution with artifact links | Publish actual findings after interviews, acceptance and pilot |

## Evidence rules

Keep deployment availability, authenticated acceptance, deterministic correctness, structural AI validity, semantic support and customer benefit separate. The supplied review reports a public deployment observation; it does not document a complete hosted acceptance run. Existing provider receipts are evidence of actual calls, not independent claim correctness.

The exposed locked evaluation cannot become a fresh holdout after prompt or validator tuning. Preserve the stopped result and obtain independently authored acceptance cases. Do not make paid calls just to fill this ledger.

Do not import confidential factory records before access boundaries are verified. Interviews can start with verbal reconstructions and anonymized records. Use a simulator only when it is labeled as such; a simulated connector is not a real ERP integration.

Record each implementation gate with the commit, commands or steps, actual result, environment and limitation. Link the evidence from RELEASE_STATUS.md after verification. Do not mark external gates complete because a template or interface exists.

## Current pass implementation

The current pass implements guided entry, the curated library with filters and pagination, distinct status labels, revision comparisons, state-aware next checks, authenticated claim review and printable deterministic reports. The second pass implements assigned checks, evidence responses, completion outcomes and shift handover, verified locally on October 1, 2026. The third pass implements downloadable CSV examples and explicit mapping, verified locally on October 1, 2026. It does not add cumulative conversion, XLSX or saved presets. See [CSV import mapping](docs/csv-import-mapping.md). See [incident workflow](docs/incident-workflow.md) for status, permission and revision rules. Local verification results are recorded in [RELEASE_STATUS.md](RELEASE_STATUS.md).

## Fresh trust challenge

A fourth pass freezes ten independently AI-authored cases before validator exposure and executes the deterministic comparison. The receipt adapter prepares same-case evidence-only, lexical and hybrid comparisons without making provider calls. AI results remain pending until actual receipts arrive; human semantic labels remain null. The review interface, numeric contract and precedent explanations also implement ideas 20, 21 and 24. Independent human support review, fresh live comparisons, practitioner usefulness and private workspace isolation remain incomplete. See [AI trust evaluation](docs/ai-trust-evaluation.md) for exact implemented controls and remaining evidence. See [fresh release](backend/evaluation/ai-trust-fresh-v1/README.md) and [qualified human review protocol](docs/ai-claim-review-protocol.md).

## Fifth-priority usability

The fifth pass completes the safe first-visit simulation, work filters, explicit investigation/action states and supervisor print summary. The simulation uses synthetic practice data and cannot modify a shared incident. It is not private factory workspace isolation. Authenticated workflow details remain separate from public source evidence and from immutable report revisions. No Tamil translation is added without evidence of language needs and agreed terminology. Use the [first-visit protocol](docs/first-visit-validation.md) to establish human comprehension and report usefulness; implementation and automated navigation alone do not satisfy those human gates.
