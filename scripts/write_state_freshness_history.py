#!/usr/bin/env python3
"""
write_state_freshness_history.py

Permanent DB writer for Trade AI state freshness audits.

Reads current freshness status from refresh_agent_context.py --mode audit --json
and appends one row per tracked state file into Postgres
state_freshness_history.

JSON files remain the fast current-state layer.
Postgres becomes the trend/audit/history layer.

--dry-run (refactor wave 1, 2026-10-10): runs the same read-only audit and prints the rows it would
INSERT; never calls psql (no schema DDL, no INSERT, no SELECT), never writes the lane receipt.
A real run writes data/runtime/write-state-freshness-history_last.json (LaneRunReceipt@v1; ok_at only
on success) under the persistent-state root. The audit subprocess runs under the venv interpreter
(lib.live_project_root.venv_python), not whatever `python3` is first on PATH.
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = PROJECT_ROOT / ".env"
LANE_ID = "write-state-freshness-history"
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


def load_env():
    if not ENV_FILE.exists():
        raise FileNotFoundError(f".env not found: {ENV_FILE}")

    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key.startswith("DB_"):
            os.environ[key] = value


def require_db_env():
    required = ["DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD"]
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        raise RuntimeError(f"Missing DB env vars: {', '.join(missing)}")


def ensure_schema():
    sql = """
    CREATE TABLE IF NOT EXISTS state_freshness_history (
        id SERIAL PRIMARY KEY,
        checked_at TIMESTAMPTZ NOT NULL,
        run_mode TEXT,
        state_file TEXT NOT NULL,
        exists_flag BOOLEAN,
        ok BOOLEAN NOT NULL,
        age_hours NUMERIC,
        max_age_hours NUMERIC,
        source_script TEXT,
        agent_checked_at TIMESTAMPTZ,
        file_size_bytes BIGINT,
        metadata JSONB DEFAULT '{}'::jsonb,
        issues JSONB DEFAULT '[]'::jsonb,
        created_at TIMESTAMPTZ DEFAULT now()
    );

    ALTER TABLE state_freshness_history
      ADD COLUMN IF NOT EXISTS run_mode TEXT,
      ADD COLUMN IF NOT EXISTS exists_flag BOOLEAN,
      ADD COLUMN IF NOT EXISTS file_size_bytes BIGINT,
      ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}'::jsonb,
      ADD COLUMN IF NOT EXISTS issues JSONB DEFAULT '[]'::jsonb;

    CREATE INDEX IF NOT EXISTS idx_state_freshness_checked
      ON state_freshness_history (checked_at DESC);

    CREATE INDEX IF NOT EXISTS idx_state_freshness_file
      ON state_freshness_history (state_file);

    CREATE INDEX IF NOT EXISTS idx_state_freshness_ok
      ON state_freshness_history (ok);

    DROP VIEW IF EXISTS latest_state_freshness;

    CREATE OR REPLACE VIEW latest_state_freshness AS
    SELECT DISTINCT ON (state_file)
      state_file,
      ok,
      age_hours,
      max_age_hours,
      source_script,
      agent_checked_at,
      run_mode,
      checked_at
    FROM state_freshness_history
    ORDER BY state_file, checked_at DESC;
    """
    run_psql(sql)


def run_psql(sql_text):
    env = os.environ.copy()
    env["PGPASSWORD"] = os.environ["DB_PASSWORD"]

    proc = subprocess.run(
        [
            "psql",
            "-h", os.environ["DB_HOST"],
            "-p", os.environ["DB_PORT"],
            "-U", os.environ["DB_USER"],
            "-d", os.environ["DB_NAME"],
            "-v", "ON_ERROR_STOP=1",
        ],
        input=sql_text,
        text=True,
        env=env,
        capture_output=True,
    )

    if proc.returncode != 0:
        print(proc.stdout)
        print(proc.stderr, file=sys.stderr)
        raise RuntimeError("psql failed")

    return proc.stdout


def get_audit():
    from lib.live_project_root import venv_python

    proc = subprocess.run(
        [venv_python(PROJECT_ROOT), "scripts/refresh_agent_context.py", "--mode", "audit", "--json"],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        print(proc.stdout)
        print(proc.stderr, file=sys.stderr)
        raise RuntimeError("refresh_agent_context audit failed")

    return json.loads(proc.stdout)


def sql_quote(value):
    if value is None:
        return "NULL"
    return "'" + str(value).replace("'", "''") + "'"


def sql_bool(value):
    return "TRUE" if bool(value) else "FALSE"


def sql_num(value):
    if value is None:
        return "NULL"
    return str(value)


def build_insert_sql(audit):
    """Pure: (sql or None, row_count). The read-only half of insert_audit."""
    checked_at = audit.get("checked_at")
    run_mode = audit.get("mode", "audit")
    issues = audit.get("issues", [])
    files_checked = audit.get("files_checked", [])

    if not files_checked:
        return None, 0

    values = []
    for row in files_checked:
        metadata = json.dumps(row).replace("'", "''")
        issues_json = json.dumps(issues).replace("'", "''")

        values.append(
            "("
            f"{sql_quote(checked_at)}, "
            f"{sql_quote(run_mode)}, "
            f"{sql_quote(row.get('file'))}, "
            f"{sql_bool(row.get('exists'))}, "
            f"{sql_bool(row.get('ok'))}, "
            f"{sql_num(row.get('age_hours'))}, "
            f"{sql_num(row.get('max_age_hours'))}, "
            f"{sql_quote(row.get('source_script'))}, "
            f"{sql_quote(row.get('agent_checked_at'))}, "
            "NULL, "
            f"'{metadata}'::jsonb, "
            f"'{issues_json}'::jsonb"
            ")"
        )

    sql = """
    INSERT INTO state_freshness_history
    (checked_at, run_mode, state_file, exists_flag, ok, age_hours, max_age_hours,
     source_script, agent_checked_at, file_size_bytes, metadata, issues)
    VALUES
    """ + ",\n".join(values) + ";\n"
    return sql, len(values)


def insert_audit(audit):
    sql, n = build_insert_sql(audit)
    if sql is None:
        print("[state-db] No files_checked rows found.")
        return 0
    run_psql(sql)
    return n


def verify_latest():
    sql = """
    SELECT state_file, ok, age_hours, source_script, checked_at
    FROM latest_state_freshness
    ORDER BY state_file;
    """
    return run_psql(sql)


def dry_run_report(audit):
    """Print what a real run would write. Never reaches run_psql."""
    sql, n = build_insert_sql(audit)
    print(f"[state-db] DRY RUN: checked_at={audit.get('checked_at')} "
          f"freshness_ok={audit.get('freshness_ok')} issues={len(audit.get('issues') or [])}")
    for row in audit.get("files_checked") or []:
        print(f"[state-db] DRY RUN: would insert state_file={row.get('file')} ok={row.get('ok')} "
              f"age_hours={row.get('age_hours')} max_age_hours={row.get('max_age_hours')}")
    print(f"[state-db] DRY RUN: would run ensure_schema (DDL) + INSERT {n} rows into "
          f"state_freshness_history; nothing written, no receipt")
    return n


def main(argv=None):
    ap = argparse.ArgumentParser(description="Append state freshness audit rows to Postgres")
    ap.add_argument("--dry-run", action="store_true",
                    help="audit + print the rows; no psql call, no receipt")
    args = ap.parse_args(argv)
    if args.dry_run:
        # Returns BEFORE ensure_schema / insert_audit / verify_latest are reachable (AGENTS.md §6).
        dry_run_report(get_audit())
        return 0

    from lib.lane_last_receipt import write_lane_receipt

    started = datetime.now(timezone.utc)
    try:
        load_env()
        require_db_env()
        ensure_schema()
        audit = get_audit()
        inserted = insert_audit(audit)
        print(f"[state-db] Inserted {inserted} freshness rows.")
        print(verify_latest())
    except Exception as exc:
        write_lane_receipt(LANE_ID, ok=False, exit_code=1, started_at=started,
                           summary={"error_type": type(exc).__name__})
        raise
    write_lane_receipt(LANE_ID, ok=True, exit_code=0, started_at=started, summary={
        "inserted": inserted, "checked_at": audit.get("checked_at"),
        "freshness_ok": audit.get("freshness_ok"), "issues": len(audit.get("issues") or [])})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
