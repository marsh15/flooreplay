# Assigned evidence checks and incident outcomes

Use assigned checks to collect evidence for a proposal, record what happened after an action and prepare a shift handover. Local acceptance checks passed on October 1, 2026. Hosted acceptance and practitioner validation remain pending separately. All factory examples are synthetic.

## Assign a check

Sign in as an owner or reviewer and open the latest analysis. Create a check from a proposal, select an active account as its assignee and set a future due time. For a private incident, the assignee must belong to its workspace. The server derives the question and required response fields from the proposal. It rejects another open check for the same proposal in that incident.

The check records the analysis and revision that motivated it. A check is separate from proposal approval. Approval records a judgment; a check records who must supply the missing evidence and what happens afterward.

## Check status

| Status | Meaning | Next step |
|---|---|---|
| OPEN | Someone has been assigned the check. No response is recorded. | The assignee or owner starts or answers it. |
| IN_PROGRESS | The assignee or owner has started the check. | Supply a response with the required evidence fields. |
| ANSWERED | A response has published a new incident revision. | The assignee or owner records the action and outcome. |
| COMPLETED | The action, actual completion time and assessment are recorded. | Include the outcome in handover and consider incident resolution separately. |
| CANCELLED | The creator or owner cancelled the check with an explanation. | The audit history remains available. |

An overdue label identifies a check that has passed its due time and has not been completed or cancelled. It does not change the check's status. Escalation is manual: the creator or owner reassigns the check or changes its deadline with a reason. The application does not send an automatic escalation message.

The assignee or owner can start, respond to and complete a check. The creator or owner can cancel or reassign it. An authenticated reviewer can add comments, including after completion or cancellation. Completed or cancelled checks cannot change status, assignee or deadline. The server checks each permission and preserves the authenticated actor in append-only activity history.

## Respond with evidence

A response requires a summary, occurrence time, source reference and each requested detail. Submit it against the latest incident revision. If another publication changed the revision, reload and inspect the new evidence before submitting again.

The response creates structured evidence and publishes an immutable new revision. The occurrence time must fall inside the incident window and cannot be in the future. A claimed line-block interval requires explicit start and end times inside that window. Do not infer a block from a note that merely mentions a disruption.

After publication, the check becomes ANSWERED and links to the new evidence and revision. The earlier report remains unchanged. The new report can use the response only according to its cutoff and evidence rules. Publishing a response does not complete the action or resolve the incident.

## Record completion and outcome

The assignee or owner completes an ANSWERED check by recording the action actually taken, actual completion time, supervisor assessment and remaining uncertainty. Completion time must be after check creation and no later than now. Enter an explicit statement such as "None identified" when no remaining uncertainty is known.

Observed good units and observation time are optional but must be supplied together. The observation cannot precede completion or occur in the future. These fields describe an observation, not an attribution. "Output improved afterward" does not establish that the action caused the improvement.

A completed check remains in the activity history with its response and outcome. It does not imply that the production shortfall disappeared or that the incident's cause is confirmed.

## Resolve the incident separately

Resolution is an explicit decision by an authenticated owner or reviewer with a rationale. The application does not certify that this account has factory supervisor authority. To mark the incident RESOLVED, every check must be COMPLETED or CANCELLED and at least one check must have a completed outcome. The decision pins the current revision. It does not change source records or production metrics.

New evidence makes a resolution against an older revision stale. The current workflow then shows the incident as effectively open until someone assesses the new revision and records a fresh decision. Reopening also requires a rationale. Inspect both the evidence and the previous resolution before deciding again.

## Shift handover

The handover shows the current situation, evidence cutoff, remaining uncertainties and outstanding checks. Each check has an owner, due time, status, overdue indication and activity history. Use it to identify what the next supervisor needs to do, then inspect the linked report and response records for detail.

Do not describe the handover as complete if an unresolved question has no assigned check. The workflow records tasks inside FloorReplay; it does not demonstrate factory-system execution or external notifications.

## Access and interrupted requests

Workflow reads, assignee lists and writes require an authenticated owner or reviewer. Anonymous visitors can read synthetic incident reports in the public demo workspace. Private incident records are restricted to workspace members, and linked checks, responses and activity inherit the incident's workspace.

Record factory source responses in a private workspace. The HTTP API rejects responses to public demo incidents with PRIVATE_RESPONSE_REQUIRED, so a submitted observation cannot become public demo evidence through this workflow. These access controls still require authenticated hosted acceptance before a real-data pilot.

Keep an interrupted mutation's request identity and exact submitted fields when retrying. An identical retry returns the recorded result without repeating the work. Use a new identity when deliberately changing a submission. Inspect the saved state before creating replacement work after an uncertain response.
