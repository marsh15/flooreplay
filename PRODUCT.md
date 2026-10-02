# Product

FloorReplay helps a production supervisor investigate a sewing-line shortfall and coordinate the next checks. The supervisor starts when observed output falls behind a plan or records disagree. The investigation ends when the supervisor has a defensible account of what is known, an owner for each remaining check, and recorded follow-up evidence and outcomes.

## Current scope

The application reconstructs an incident from records available at a selected evidence cutoff. It calculates production shortfall, separates supported hypotheses from unanswered questions, retrieves historical precedents, and records proposal review against immutable revisions. Imports preserve their source bytes and interpretation. Corrections create a new revision. AI drafts require human assessment.

All factory records are synthetic. Factory validation and measured operational benefit remain pending. Proposal approval currently records a review decision; it does not establish that someone performed the action or resolved the incident. Assigned checks, evidence responses, completion outcomes and shift handover were verified locally on October 1, 2026. Incident resolution remains a separate decision tied to a revision. The application includes guided entry, library filters and pagination, revision comparisons, state-aware next checks, claim annotations and printable deterministic reports.

The primary user is a production supervisor. Maintenance staff, planners and industrial engineers may supply evidence or complete checks. Engineers and hiring reviewers are secondary users of the evaluation lab and implementation evidence. The older operator-coverage workbench remains an archived engineering demonstration.

## What a supervisor needs to decide

- Which production intervals and source records support the reported shortfall?
- Which explanations have evidence, which have contradictions, and which need a check?
- Who should answer each unresolved question and by when?
- What changed after a correction or response?
- What action happened, and what uncertainty remains afterward?

A first-time walkthrough should let a user answer these questions without the author narrating the application. Practitioner interviews and a comparative pilot will test whether this is the right recurring job. [IMPROVEMENT_PLAN.md](IMPROVEMENT_PLAN.md) defines those gates.

## Design requirements

1. Show the result and its evidence together. Every metric and finding must lead to its input records.
2. Keep calculation coverage, evidence completeness, investigation progress and action completion distinct.
3. Say when evidence entered the system. Explain the cutoff as the latest information this report may use.
4. Label live deterministic results, saved reports and generated drafts separately.
5. Preserve the previous report when new evidence creates a revision.
6. Keep source inspection usable on narrow screens and through keyboard navigation.
7. Use written status labels and visible focus. Color alone must not carry meaning.
8. Provide loading, empty, interrupted, unavailable and error states.

Avoid confidence percentages without a defensible measurement, unsupported causal claims, decorative gauges and claims of factory readiness based only on synthetic software tests.

The [incident workflow](docs/incident-workflow.md) defines task states, assignment permissions, immutable evidence responses and outcome limitations. Task metadata requires authentication, but source responses become evidence in public synthetic demo reports. Private workspace membership now scopes evidence and task access. Public-demo source responses remain visible in synthetic reports; real deployment confidentiality still requires current acceptance evidence.

Synthetic downloadable CSV examples, explicit source-column mappings and defaults were verified locally on October 1, 2026. Users preview dates, units and scope before publication. Cumulative totals, XLSX and saved mapping presets remain follow-up work.

Reviewers can inspect a deliberately shared AI draft beside its pinned citations, annotate support and assess omissions, abstention and usefulness. Exact output identities and disagreements remain in the report. Qualifications and independence are declarations, not verified expertise. The grounding contract and comparison harness do not establish that AI improves factory decisions; independent human review and live same-case measurements remain pending. See [AI trust evaluation](docs/ai-trust-evaluation.md).

Visitors without an account can use a guided browser-only action simulation. It is separate from shared investigations and cannot issue provider requests or update their records. The library exposes workflow states and ownership only to authenticated users; anonymous and offline views report unavailable workflow state. A supervisor print summary combines the pinned deterministic report with a separately identified latest workflow snapshot when authorized. First-visit comprehension, supervisor usefulness and language needs still require the [visitor protocol](docs/first-visit-validation.md).
