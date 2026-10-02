# Isolated recovery and rollback drill

`scripts/recovery_drill.py` performs an actual PostgreSQL custom-format backup and restore. It accepts only `flooreplay_*_test` names and the dedicated local test container, creates new databases and never drops or rewrites the source. No provider call or production database is involved.

Run from the repository root:

```sh
python3 scripts/recovery_drill.py --source flooreplay_trust_test --output docs/evidence/recovery-final-2026-10-02.json
```

The source is cloned into a dedicated drill source. Only the clone receives explicitly synthetic fixtures: zero-charge spend receipt, AI run, non-human claim annotation and 512-dimensional zero vector. These test preservation, not billing, embedding quality or semantic support. Existing accounts, revisions and incident reviews are local test data. The original source remains unchanged.

Counts and SHA-256 digests of sorted complete rows verify every public table, including credentials, revisions, reviews, vectors and spending records. Only counts/digests enter the report. Raw backups contain account hashes and remain temporary, never published. Test clones remain available for inspection.

Dump, restore, verification and total drill timings describe one local instance with small test/synthetic data. They do not establish production RTO/RPO, encryption, offsite retention or point-in-time recovery.

## Compatible rollback

Run a prior compatible application against the restored current schema and verify deterministic reads, authentication, reviews and the private-data boundary, then return to current code. Do not destroy newer data through schema downgrade to make old code start.

Commit `04e0466` is incompatible once private workspaces exist: it retains prior public-data assumptions. It must not be presented as safe production rollback. The candidate must preserve the reviewed access boundary and understand the additive schema. The [recorded artifact](evidence/recovery-final-2026-10-02.json) states whether the application exercise completed; pending is not passing.

Hosted restart persistence and hosted acceptance remain separate gates.

## Recorded drill, October 2, 2026

The [final restore](evidence/recovery-final-2026-10-02.json) preserved all 36 table contents and verified that the source database remained unchanged. Dump/restore used local synthetic test data; restoring took 0.98 seconds and the full drill took 34.04 seconds. Revisions, accounts, reviews, vectors and spending records remained equal.

The [API rollback exercise](evidence/application-rollback-2026-10-02.json) started `61f64ef`, switched to the compatible API `ba91a26`, and returned to `61f64ef` on the same restored database. HTTP logins, private analysis/review/export, foreign-user denial and review persistence passed. The older API became ready in 1.66 seconds; return-to-current readiness and verification took 3.57 seconds. No schema downgrade or provider call occurred.

This is an API-component rollback, not a frontend asset rollback. Retain the current frontend authentication-boundary fix; frontend assets from `ba91a26` and `61f64ef` can retain private archive rows after logout and are not approved rollback targets. The first harness attempt omitted a required submission field and failed before recording success. The corrected harness passed on a fresh restore. Six guard tests also verify refusal of production databases, unsafe release refs and Python optimization that would disable assertions.
