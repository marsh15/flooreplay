# Security hardening — 1 November 2026

This increment tightens private-workspace authority and limits sensitive output, and records the result of a source audit of the pre-hardening baseline. It is not evidence of operational benefit, a pilot, or a proof that no vulnerability remains.

## Changes

- **Workspace authority:** an account owner invited as an ordinary member cannot override other people's assigned checks or unpublished AI drafts. The requester, named assignee, check creator and actual workspace owners retain their respective permissions. Published, exact-digest review packets remain available to authorized members. Offline administration and the public synthetic example retain their existing trust model.
- **Current permissions:** workflow responses compute action permissions for the current viewer. Stored idempotency receipts and historical exports do not retain those permissions. A membership downgrade or revocation affects subsequent requests.
- **Private usage entries:** the HTTP usage view returns only the current owner's operation entries and omits provider diagnostics and draft text. Shared allowance calculations and persisted accounting records remain intact. Capabilities reads no longer load unused ledger entries.
- **Bounded imports:** oversized JSONL row counts are rejected before decoding individual records, preserving the existing line-splitting behavior and byte cap.
- **AI quantity checks:** word-only source identifiers cannot erase quantity words before numeric-prose checks. These checks do not establish semantic truth; AI claims still require human review.
- **Acceptance credentials:** the operator acceptance helper refuses redirects before forwarding credentials. A refused redirect retains its HTTP status and a `REDIRECT_REFUSED` category, including when its body is HTML. Loopback regression tests run in CI and `make test`.
- **Analysis cost:** contradiction references are matched with set lookups and line-block segments are computed with an active-interval sweep, so a revision with many repeated references no longer costs time proportional to references times supporting events on every incident-list read. Behavior is unchanged; a randomized comparison against a brute-force overlap scan and a repeated-reference timing guard cover it.
- **Key material:** additional common private-key and certificate-bundle filenames are ignored by Git.

## Verification

Validation used disposable synthetic PostgreSQL databases with provider keys empty. No paid provider call or hosted probe ran. The user authorized normal local validation because this host lacks the strict OS sandbox required by the audit skill.

- Backend: **371 passed**, no skips (368 at the earlier commit, plus three analysis-cost regression tests).
- Browser suite: **82 passed**, including live import, revision, workflow and workspace-privacy checks.
- Acceptance-helper unit tests: **8 passed**.
- Ruff, strict mypy over 51 source files, frontend lint and the hosted-mode production build passed.
- OpenAPI, generated TypeScript and saved demonstration bundles regenerated without drift.
- Backend advisory audit: no known vulnerabilities or adverse project statuses among 61 packages.
- Frontend advisory audit: no high or critical findings; three existing moderate minimatch tooling occurrences remain. They are inherited through ESLint, TypeScript ESLint and OpenAPI generation. No forced major dependency override was applied. Review by **30 November 2026**.

## Audit completion status

The all-main source audit of `00f1d1ef866c4c60687550823e72c392a9967cde` (standard profile) is complete. Every coverage unit and candidate has an independent disposition, and each retained record had a fresh final review. Material replacements were re-verified by further fresh reviewers. Runtime checks used disposable synthetic data with provider calls disabled; the strict OS sandbox was unavailable and is not claimed. No deployment was probed.

Baseline results (20 candidates):

- **Confirmed, 4.** Two medium findings on global account-owner overrides (other members' unpublished AI drafts, and assigned checks) and one medium on usage-ledger output reaching other workspaces. These are fixed on main by `79e02cf` and `8f97145`. One low finding, repeated superlinear incident analysis on list reads, is fixed by the analysis-cost change above.
- **Needs validation, 2.** Password sign-in throttling is keyed on the connecting peer address, so it would be one shared bucket if the hosted forwarding hop presents a single address; and local-owner note-confirmation rows written before the workspace migration may have kept the public-demo default, which would matter only if such rows exist and hold private text. Each needs owner-side evidence from the hosted platform or the deployed database. No attack traffic is needed or authorized, and neither is claimed as a vulnerability.
- **Rejected, 14.** Including speculative resource, tenancy and best-practice concerns that source and bounded local checks refuted, or that are intentional documented behavior such as the shared spending allowance and the public synthetic demo.

The retained reasoning, proofs and per-record verification live in the separate audit run directory, which is not part of this repository. The reopened-resolution policy remains a deferred product decision and is not treated as a vulnerability.

Real-data deployment acceptance, proxy identity, practitioner validation and measured operational benefit remain separate evidence requirements. No factory pilot has run.
