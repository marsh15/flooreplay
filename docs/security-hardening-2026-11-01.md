# Security hardening — 1 November 2026

This increment tightens private-workspace authority and limits sensitive output. It is not a completed security audit or evidence of operational benefit.

## Changes

- **Workspace authority:** an account owner invited as an ordinary member cannot override other people's assigned checks or unpublished AI drafts. The requester, named assignee, check creator and actual workspace owners retain their respective permissions. Published, exact-digest review packets remain available to authorized members. Offline administration and the public synthetic example retain their existing trust model.
- **Current permissions:** workflow responses compute action permissions for the current viewer. Stored idempotency receipts and historical exports do not retain those permissions. A membership downgrade or revocation affects subsequent requests.
- **Private usage entries:** the HTTP usage view returns only the current owner's operation entries and omits provider diagnostics and draft text. Shared allowance calculations and persisted accounting records remain intact. Capabilities reads no longer load unused ledger entries.
- **Bounded imports:** oversized JSONL row counts are rejected before decoding individual records, preserving the existing line-splitting behavior and byte cap.
- **AI quantity checks:** word-only source identifiers cannot erase quantity words before numeric-prose checks. These checks do not establish semantic truth; AI claims still require human review.
- **Acceptance credentials:** the operator acceptance helper refuses redirects before forwarding credentials. A refused redirect retains its HTTP status and a `REDIRECT_REFUSED` category, including when its body is HTML. Loopback regression tests run in CI and `make test`.
- **Key material:** additional common private-key and certificate-bundle filenames are ignored by Git.

## Verification

Validation used disposable synthetic PostgreSQL databases with provider keys empty. No paid provider call or hosted probe ran. The user authorized normal local validation because this host lacks the strict OS sandbox required by the audit skill.

- Backend: **368 passed**, no skips.
- Browser suite: **82 passed**, including live import, revision, workflow and workspace-privacy checks.
- Acceptance-helper unit tests: **8 passed**.
- Ruff, strict mypy over 51 source files, frontend lint and the hosted-mode production build passed.
- OpenAPI, generated TypeScript and saved demonstration bundles regenerated without drift.
- Backend advisory audit: no known vulnerabilities or adverse project statuses among 61 packages.
- Frontend advisory audit: no high or critical findings; three existing moderate minimatch tooling occurrences remain. They are inherited through ESLint, TypeScript ESLint and OpenAPI generation. No forced major dependency override was applied. Review by **30 November 2026**.

## Audit completion status

The broader all-main audit started from `00f1d1ef866c4c60687550823e72c392a9967cde`. Source reconnaissance and multiple hunting and coverage-review rounds ran. Claude Haiku then reached its API rate limit. Final coverage closure and independent candidate/record validation have not completed; unvalidated hypotheses are not findings, and no complete-audit claim is made. The separate audit checkpoint retains the remaining work and the requested reviewer-model choice.

Real-data deployment acceptance, proxy identity, practitioner validation and measured operational benefit remain separate evidence requirements.
