#!/usr/bin/env python3
"""Local PostgreSQL recovery drill. Refuses production names; makes no provider calls."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path


def validate_database(name: str) -> str:
    if not re.fullmatch(r"flooreplay_[a-z0-9_]+_test", name):
        raise ValueError("Only flooreplay_*_test database names are permitted")
    return name


def command(args: list[str], data: bytes | None = None) -> bytes:
    return subprocess.run(args, input=data, capture_output=True, check=True).stdout


def sql(container: str, database: str, statement: str) -> bytes:
    return command(["docker", "exec", "-i", container, "psql", "-X", "-v", "ON_ERROR_STOP=1", "-U", "flooreplay_test", "-d", database, "-At"], statement.encode())


def snapshot(container: str, database: str) -> dict[str, dict[str, object]]:
    tables = sql(container, database, "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename").decode().splitlines()
    result = {}
    for table in tables:
        # Only server-returned, quoted identifiers enter this query. Sort complete rows,
        # including vectors and JSON, so physical restoration order cannot affect proof.
        quoted = '"' + table.replace('"', '""') + '"'
        rows = sql(container, database, f"SELECT row_to_json(t)::text FROM public.{quoted} t ORDER BY row_to_json(t)::text")
        result[table] = {"rows": len(rows.splitlines()), "sha256": hashlib.sha256(rows).hexdigest()}
    return result


def seed_receipts(container: str, database: str) -> None:
    sql(container, database, """
INSERT INTO spend_entries (id,user_id,purpose,operation,status,reserved_inr,charged_inr,charged_usd,price_table,details,expires_at,created_at)
SELECT 'recovery-synthetic-spend',id,'evaluation','generation','SETTLED',0,0,0,'{}','{"synthetic":true,"provider_called":false}',now(),now() FROM accounts ORDER BY id LIMIT 1;
INSERT INTO ai_runs (id,user_id,request_key,analysis_id,identity,task,question,status,packet,configuration,attempts,result,reservation_id,created_at,completed_at)
SELECT 'recovery-synthetic-run',id,'recovery-fixture','recovery-fixture','recovery-fixture','summary','Synthetic recovery fixture','COMPLETE','{}','{"synthetic":true}','[]','{"synthetic":true}','recovery-synthetic-spend',now(),now() FROM accounts ORDER BY id LIMIT 1;
INSERT INTO ai_claim_reviews (id,user_id,request_key,run_id,claim_path,output_digest,supported,rationale,judgment,flags,reviewer_kind,qualifications,independent,created_at)
SELECT 'recovery-synthetic-review',id,'recovery-fixture','recovery-synthetic-run','claims.0','synthetic',false,'Synthetic persistence fixture, not a semantic assessment','insufficient_evidence','[]','unspecified','',false,now() FROM accounts ORDER BY id LIMIT 1;
INSERT INTO embedding_artifacts (id,model,dimensions,preprocessing_version,content,vector,provider_usage,created_at)
VALUES ('recovery-synthetic-vector','synthetic-no-provider',512,'recovery-fixture','Synthetic persistence vector', ('[' || array_to_string(array_fill(0.0::float8,ARRAY[512]),',') || ']')::vector,'{"synthetic":true,"provider_called":false}',now());
""")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container", default="flooreplay-test-db-1")
    parser.add_argument("--source", default="flooreplay_trust_test")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    validate_database(args.source)
    if args.container != "flooreplay-test-db-1":
        raise ValueError("This drill is restricted to the disposable local test container")
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    source = validate_database(f"flooreplay_recovery_source_{stamp}_test")
    restored = validate_database(f"flooreplay_recovery_restore_{stamp}_test")
    start = time.monotonic()
    origin_before = snapshot(args.container, args.source)
    for database in (source, restored):
        # Never drop or reuse an existing database.
        command(["docker", "exec", args.container, "createdb", "-U", "flooreplay_test", database])
    dump_args = ["docker", "exec", args.container, "pg_dump", "-U", "flooreplay_test", "--format=custom", "--no-owner", "--no-acl"]
    restore_args = ["docker", "exec", "-i", args.container, "pg_restore", "-U", "flooreplay_test", "--no-owner", "--no-acl", "--exit-on-error", "-d"]
    command(restore_args + [source], command(dump_args + [args.source]))
    seed_receipts(args.container, source)
    before = snapshot(args.container, source)
    t = time.monotonic()
    archive = command(dump_args + [source])
    dump_seconds = time.monotonic() - t
    # Backup contents include local account hashes; keep them temporary, never publish.
    with tempfile.TemporaryDirectory(prefix="flooreplay-recovery-") as directory:
        Path(directory, "backup.dump").write_bytes(archive)
        t = time.monotonic()
        command(restore_args + [restored], archive)
        restore_seconds = time.monotonic() - t
    t = time.monotonic()
    after = snapshot(args.container, restored)
    verification_seconds = time.monotonic() - t
    origin_after = snapshot(args.container, args.source)
    required = ("incident_revisions", "accounts", "incident_reviews", "ai_claim_reviews", "embedding_artifacts", "spend_entries")
    passed = before == after and origin_before == origin_after and all(int(after.get(table, {}).get("rows", 0)) > 0 for table in required)
    report = {
        "recorded_at": datetime.now(UTC).isoformat(),
        "commit": command(["git", "rev-parse", "HEAD"]).decode().strip(),
        "scope": "Local isolated recovery drill; not a production backup or hosted restart proof",
        "source_database": source, "restored_database": restored,
        "source_origin": args.source, "source_origin_modified": origin_before != origin_after,
        "source_origin_table_hashes_equal": origin_before == origin_after,
        "synthetic_fixtures": ["recovery-synthetic-spend", "recovery-synthetic-run", "recovery-synthetic-review", "recovery-synthetic-vector"],
        "provider_calls": 0, "archive_bytes": len(archive),
        "archive_sha256": hashlib.sha256(archive).hexdigest(),
        "dump_seconds": round(dump_seconds, 3), "restore_seconds": round(restore_seconds, 3),
        "verification_seconds": round(verification_seconds, 3),
        "total_drill_seconds": round(time.monotonic() - start, 3),
        "tables": after, "all_table_contents_equal": before == after,
        "required_nonempty_tables": list(required), "passed": passed,
        "rollback": {"status": "pending", "reason": "Run the compatible prior application against this restored database; schema downgrade is not a rollback drill"},
        "limitations": ["One local PostgreSQL instance", "No point-in-time recovery", "No production volume or load", "Synthetic paid receipts and vector; no real provider billing validation", "Backup encryption and remote retention are not tested"],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"passed": passed, "report": str(args.output), "restored_database": restored}))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
