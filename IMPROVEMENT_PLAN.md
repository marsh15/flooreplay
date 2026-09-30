# FloorReplay improvement plan

Prepared September 30, 2026 from the supplied 36-item review. The intended workflow is a production supervisor importing imperfect records, investigating a sewing-line shortfall, assigning evidence checks, recording responses and measuring whether the investigation helped.

This is an ordered backlog, not a claim that all items are implemented. Synthetic tests establish bounded software behavior. Practitioner usefulness, confidential-data readiness and independent AI support need separate evidence. No interviews or pilot results are recorded yet.

## Delivery order

1. Correct the product story and make the existing example understandable. Keep engineering fixtures outside the default supervisor library.
2. Refine next checks, compare revisions and provide printable deterministic reports in this pass. Follow with assigned evidence checks and outcomes. Keep approval, completed action and resolved incident distinct.
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
| 6. Assign and complete actions | Next | Assignee, due time, status, comments and completion evidence | Authenticated user assigns, answers and closes a check; escalation is a subsequent requirement |
| 7. Request missing evidence | Next | Specific requested fields and finding reference; response creates evidence | New revision reflects response; prior report remains unchanged |
| 8. Record outcomes | Next | Action taken, completion time, observed output and supervisor assessment | Outcome preserves causal uncertainty and authorship |
| 9. Compare revisions | Now | Added/corrected sources, metric changes and stale proposals | User explains the change without mentally combining two reports |
| 10. Refine next checks | Now | Questions depend on supported and unresolved findings | Confirmed interval removes the redundant confirmation question |
| 11. Shift handover | Next | Printable summary with open checks, owners and latest evidence time | Next supervisor can continue from the report |
| 12. Spreadsheet ingestion | Next | Downloadable examples and explicit column mapping with previews | Unfamiliar CSV imports without code changes; saved mappings and XLSX follow practitioner need |
| 13. Cumulative output | Next | Explicit delta/cumulative interpretation and preserved readings | Resets, duplicates and gaps remain traceable or unresolved |
| 14. Identifier reconciliation | Next | Reviewed alias map with original identity and version | Ambiguous matches stop for review |
| 15. Source health | Next | Latest import/observation, expected frequency, gaps, rejections and conflicts | User distinguishes delayed records from actual production loss |
| 16. One integration | External | Permitted incremental connector or clearly labeled simulator | Checkpoints, deduplication and interruption recovery against an accessible source |
| 17. Working calendars | Next | Breaks, shifts and planned downtime in production-time calculation | Break changes available-time calculation with visible assumptions |
| 18. Revised baselines | External | Interview-driven effective-time plan revisions | Original and approved revised commitments remain comparable |
| 19. Independent claim review | External | Qualified reviewer labels exact new claims and citations | Denominators, rationale, disagreements and qualifications recorded |
| 20. Claim-review interface | Now | Claim and citation inspection with judgment and rationale | Authenticated annotation preserves run and output identity |
| 21. Numeric prose contract | Next | Typed quantity references without rejecting harmless phrases | Invented quantities rejected; fresh holdout follows development tuning |
| 22. Fresh evaluation cases | External | Independently authored multi-disruption and insufficient-evidence cases | Cases avoid exposed locked templates; authorized anonymized practitioner cases where possible |
| 23. Compare AI alternatives | External | Same-case deterministic, evidence-only, lexical and hybrid comparison | Claim support, useful checks, omissions, latency and measured cost |
| 24. Precedent relevance | Next | Operational similarities, differences, prerequisites and no-match result | Reviewer judges decision usefulness, not category overlap |
| 25. Hostile source text | Next | Source-instruction, blame, contradiction and leakage cases | Evidence boundary survives or failure is explicit |
| 26. Guided first visit | Now | Purpose statement, example entry and cutoff explanation | Visitor reaches and explains a useful finding without narration |
| 27. Separate status meanings | Now | Calculation, evidence and action labels | Completed arithmetic cannot imply confirmed cause or resolved incident |
| 28. Hide evaluation fixtures | Now | Curated library with explicit engineering view, filters and pagination | Default browsing excludes development/locked fixtures; filtering and pagination work in the current build |
| 29. Safe interactive demo | Next | Isolated workspace or clearly labeled local simulation | Visitor completes a flow without shared mutation or owner access |
| 30. Supervisor exports | Now | Printable deterministic report with facts, uncertainties, revision/report identity and existing reviewer roles | Report works outside the app; named action assignees await the task lifecycle; Tamil support follows terminology research |
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

The current pass implements guided entry, the curated library with filters and pagination, distinct status labels, revision comparisons, state-aware next checks, authenticated claim review and printable deterministic reports. Assigned operational tasks, responses, outcomes and spreadsheet column mapping remain follow-up work. Local verification results are recorded in [RELEASE_STATUS.md](RELEASE_STATUS.md).
