# Investigate a production shortfall

FloorReplay compares planned output with recorded good output and helps you check possible explanations. The bundled examples are synthetic. A calculated shortfall does not establish its cause.

## Try an investigation without setup

Open the incident library and select **Delayed start on sewing line S4**. The **Follow the investigation** guide links to the calculation, source health, explanations, assigned checks, revision comparison and export. If you want to practise recording findings without an account, open **Practice investigation**. Resetting that practice clears only its browser simulation.

If the API is unavailable, the bundled S4 report remains readable. Saved examples cannot publish evidence, assign checks or establish the current investigation state.

## Complete an investigation

1. **Import the records.** An owner signs in and opens incident imports. Start in a private workspace. Download the synthetic CSV examples to see the required structure. A new incident needs its baseline plan; additional imports add output, observations or corrections to an existing incident.
2. **Review the column mapping.** Inspect the CSV and match each field to a source column. Enter a constant only when the value applies to every row. Check line, order, style, unit and timestamps. For output, declare whether the numbers are interval deltas or cumulative counter readings. A downloaded column mapping can be loaded for the next file, but constants and destination details must be checked again.
3. **Preview before publishing.** Fix every reported row problem. A blocked preview cannot be published. If the file, mapping, aliases or cutoff changes, generate another preview. A failed publication can be retried with **Retry same publication**; retain that request rather than creating another import while its result is uncertain.
4. **Inspect the discrepancy.** Select the incident and evidence revision. **Observed situation** shows the planned and recorded output for comparable intervals. Missing records stay missing; they are not zero output. **Source health** shows which intervals have arrived or conflict.
5. **Read the evidence and open questions.** Select a source reference to inspect its original record. Read supporting and contradicting observations. The knowledge cutoff is the time by which a record was available. A later-arriving record may describe an earlier event but must appear in a later revision.
6. **Assign follow-up checks.** Sign in with workspace access. Review the proposed check, choose its named assignee and deadline, then assign it. A proposal approval records a review decision. Assignment requests a check; neither records an operational action as executed.
7. **Record the findings and outcome.** The assignee or workspace owner records the source reference, observation time and requested details. Saving a source response creates another evidence revision. Record the action actually taken, completion time, outcome and remaining uncertainty separately. Completing a check leaves the incident open until someone explicitly resolves it.
8. **Compare revisions and review again.** Compare the current revision with an earlier one to see changed calculations, added sources and corrections. Earlier reports and review decisions keep their original inputs. A correction after resolution reopens the incident. Before resolving again, review the new evidence and explain the decision in the resolution rationale; existing completed checks remain in its history.
9. **Export and hand over.** **Print investigation report** produces a readable supervisor report that can be saved as a PDF. Sign-in enables the portable JSON export. A report's analysis is pinned to its evidence revision; any included current assignments and handover are separately labelled with their retrieval time and current revision.

## Understand workspace permissions

In a private workspace, its owners may override assigned checks. Other members can record their assigned checks, manage checks they created and add comments. Being an owner of another workspace does not grant these override permissions here.

Unpublished AI drafts are accessible to their requester and this workspace's owners. Publishing an exact draft makes its review packet available to workspace members. Citation and numeric checks do not establish that a claim is true; inspect the sources and record human review.

Usage totals describe the shared allowance. The operation list shows your own operations and omits private draft contents. The public synthetic example keeps its shared demonstration behavior.

## Recover from a problem

- **Wrong identifier or interval:** correct the source or explicitly review an identifier alias. FloorReplay does not infer that similar names mean the same line or order. Keep the original source file.
- **A record was corrected:** import a new record with a new ID and the original record's correction reference. Preserve the original record and compare the resulting revision.
- **A check or import changed while you were working:** reload the current revision and inspect the new state before submitting a new request. Historical reports stay available for reading.
- **Connection lost during a write:** use the provided retry for the same request. The server may already have saved it. For uncertain AI operations, inspect the operation receipt before making another potentially billed request.
- **Sign-in expired or access denied:** sign in again or ask the workspace owner to confirm membership. Do not move private records into the public synthetic demonstration.

## Check whether it helps your team

Use the [interview protocol](practitioner-interview.md) to learn the team's existing process before showing the app. Then use the [comparative pilot](comparative-pilot.md) and [blank measurement template](pilot/README.md) to record task times, errors, missing references, assistance and failures. No practitioner results or operational benefit are established by the software tests.
