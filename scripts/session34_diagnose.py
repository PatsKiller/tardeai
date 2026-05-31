#!/usr/bin/env python3
"""
session34_diagnose.py
======================
Runs READ-ONLY queries and greps to discover the exact state of the system
before any patches are applied. Outputs a markdown report.

Discovers:
  1. The covered_call_scoring INSERT path and target column types
  2. The rag_content_curation source table and column list
  3. Where the 180s timeout is set in run_deep_overnight_llm_queue.py
  4. The job_type registry location and current contents
  5. Current state of llm_overnight_queue (running/pending/failed counts)
  6. Whether the watch query is reading the same table as the writers
  7. The stuck 'running' job's full row contents

NO writes. NO ALTER TABLE. NO UPDATE. Pure diagnostic.

Usage:
    cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
    python3 scripts/session34_diagnose.py --output backups/session34_diagnose.md
"""

import argparse
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    print("ERROR: psycopg2 not installed. Run: pip install psycopg2-binary --break-system-packages")
    sys.exit(1)


# -----------------------------------------------------------------------------
# DB connection
# -----------------------------------------------------------------------------
def get_db_conn():
    """Connect using same env vars the rest of the system uses."""
    return psycopg2.connect(
        host=os.environ.get("PGHOST", os.environ.get("DB_HOST", "localhost")),
        port=int(os.environ.get("PGPORT", os.environ.get("DB_PORT", "5432"))),
        dbname=os.environ.get("PGDATABASE", os.environ.get("DB_NAME", "tradeai")),
        user=os.environ.get("PGUSER", os.environ.get("DB_USER", "johnclaw")),
        password=os.environ.get("PGPASSWORD", os.environ.get("DB_PASSWORD", "")),
    )


def q(conn, sql, params=None):
    """Run a SELECT and return list-of-dicts."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params or ())
        try:
            return [dict(r) for r in cur.fetchall()]
        except psycopg2.ProgrammingError:
            return []


# -----------------------------------------------------------------------------
# Section 1: covered_call_scoring schema
# -----------------------------------------------------------------------------
def section_covered_call(conn, out):
    out.append("\n## 1. covered_call_scoring schema\n")

    # Find tables that look related
    tables = q(conn, """
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'public'
          AND (table_name ILIKE '%covered_call%' OR table_name ILIKE '%cc_score%')
        ORDER BY table_name
    """)
    out.append(f"**Candidate tables:** {[t['table_name'] for t in tables]}\n")
    if not tables:
        out.append("**NO tables matched 'covered_call' pattern.** The job may write into a generic results table.\n")
        # Check llm_overnight_results
        gen = q(conn, """
            SELECT column_name, data_type, character_maximum_length
            FROM information_schema.columns
            WHERE table_name = 'llm_overnight_results'
            ORDER BY ordinal_position
        """)
        if gen:
            out.append(f"\n**Falling back to `llm_overnight_results`** ({len(gen)} columns):\n\n| column | type | maxlen |\n|---|---|---|\n")
            for c in gen:
                out.append(f"| `{c['column_name']}` | `{c['data_type']}` | {c['character_maximum_length'] or ''} |\n")

    for t in tables:
        cols = q(conn, """
            SELECT column_name, data_type, character_maximum_length, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_name = %s
            ORDER BY ordinal_position
        """, (t['table_name'],))
        out.append(f"\n### Table `{t['table_name']}` ({len(cols)} columns)\n\n| column | type | maxlen | nullable | default |\n|---|---|---|---|---|\n")
        for c in cols:
            out.append(f"| `{c['column_name']}` | `{c['data_type']}` | {c['character_maximum_length'] or ''} | {c['is_nullable']} | {c['column_default'] or ''} |\n")
        # Sample any existing rows
        sample = q(conn, f"SELECT * FROM {t['table_name']} ORDER BY 1 DESC LIMIT 3")
        if sample:
            out.append(f"\n**Latest 3 rows:**\n```\n")
            for r in sample:
                out.append(f"{dict(r)}\n")
            out.append("```\n")

    # Search the codebase for the INSERT path
    out.append("\n### Code that writes covered_call_scoring results\n")
    try:
        result = subprocess.run(
            ["grep", "-rn", "-l", "covered_call_scoring", "scripts/", "agents/", "core/"],
            capture_output=True, text=True, timeout=10,
        )
        files = sorted(set(result.stdout.strip().split("\n"))) if result.stdout.strip() else []
        out.append(f"**Files touching `covered_call_scoring`:** {len(files)}\n\n")
        for f in files[:20]:
            out.append(f"- `{f}`\n")
    except Exception as e:
        out.append(f"grep failed: {e}\n")

    # Look for the actual INSERT/range field
    try:
        result = subprocess.run(
            ["grep", "-rn", "-E", r"(1\.5-3\.0|strike_range|premium_range|target_range)", "scripts/", "agents/", "core/"],
            capture_output=True, text=True, timeout=10,
        )
        out.append(f"\n**Range-style writes in code:**\n```\n{result.stdout[:2000]}\n```\n")
    except Exception:
        pass


# -----------------------------------------------------------------------------
# Section 2: rag_content_curation source table
# -----------------------------------------------------------------------------
def section_rag(conn, out):
    out.append("\n## 2. rag_content_curation source\n")

    # Find the SQL with ORDER BY created_at DESC LIMIT 8
    out.append("\n### Code searching for `created_at` in rag context\n")
    try:
        result = subprocess.run(
            ["grep", "-rn", "-B2", "-A4", "ORDER BY created_at DESC LIMIT 8", "scripts/", "agents/", "core/"],
            capture_output=True, text=True, timeout=10,
        )
        out.append(f"```\n{result.stdout[:3000]}\n```\n")
    except Exception as e:
        out.append(f"grep failed: {e}\n")

    # Find tables that might be the RAG source
    rag_tables = q(conn, """
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'public'
          AND (table_name ILIKE '%rag%' OR table_name ILIKE '%knowledge%'
               OR table_name ILIKE '%curated%' OR table_name ILIKE '%research_notes%'
               OR table_name ILIKE '%embedding%' OR table_name ILIKE '%youtube%')
        ORDER BY table_name
    """)
    out.append(f"\n**Candidate RAG tables:** {[t['table_name'] for t in rag_tables]}\n")

    for t in rag_tables:
        cols = q(conn, """
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_name = %s
            ORDER BY ordinal_position
        """, (t['table_name'],))
        timestamp_cols = [c for c in cols if 'timestamp' in c['data_type'].lower() or 'date' in c['data_type'].lower()]
        out.append(f"\n### `{t['table_name']}` ({len(cols)} cols, timestamps: {[c['column_name'] for c in timestamp_cols]})\n")


# -----------------------------------------------------------------------------
# Section 3: Timeout config
# -----------------------------------------------------------------------------
def section_timeouts(out):
    out.append("\n## 3. Timeout configuration\n")

    # Search for 180s timeout in the queue runner
    queue_script = Path("scripts/run_deep_overnight_llm_queue.py")
    if not queue_script.exists():
        out.append(f"**ERROR:** {queue_script} not found\n")
        return

    out.append(f"\n### Timeout references in {queue_script}\n```\n")
    with open(queue_script) as f:
        for i, line in enumerate(f, 1):
            if re.search(r"timeout\s*=\s*1\d{2}", line) or "180" in line and "timeout" in line.lower():
                out.append(f"{i}: {line}")
            elif "TIMEOUT" in line and "=" in line:
                out.append(f"{i}: {line}")
            elif re.search(r"timed out", line):
                out.append(f"{i}: {line}")
    out.append("```\n")

    # Also scan local_llm.py / local_llm_config.py
    for path_candidate in ["scripts/local_llm.py", "scripts/local_llm_config.py", "core/local_llm.py"]:
        p = Path(path_candidate)
        if p.exists():
            out.append(f"\n### Timeout in {p}\n```\n")
            with open(p) as f:
                for i, line in enumerate(f, 1):
                    if re.search(r"timeout\s*=", line, re.IGNORECASE) or "TIMEOUT" in line:
                        out.append(f"{i}: {line}")
            out.append("```\n")


# -----------------------------------------------------------------------------
# Section 4: Job type registry
# -----------------------------------------------------------------------------
def section_job_types(out):
    out.append("\n## 4. Job type registry\n")

    # Find where "Unknown job type" comes from
    try:
        result = subprocess.run(
            ["grep", "-rn", "-B2", "-A2", "Unknown job type", "scripts/", "agents/", "core/"],
            capture_output=True, text=True, timeout=10,
        )
        out.append(f"\n### Where 'Unknown job type' is logged\n```\n{result.stdout[:2000]}\n```\n")
    except Exception:
        pass

    # Find the registry dict / list
    try:
        result = subprocess.run(
            ["grep", "-rn", "-E", r"(JOB_TYPE_HANDLERS|JOB_TYPES|job_type_registry|VALID_JOB_TYPES)", "scripts/", "agents/", "core/"],
            capture_output=True, text=True, timeout=10,
        )
        out.append(f"\n### Job type registry references\n```\n{result.stdout[:2000]}\n```\n")
    except Exception:
        pass


# -----------------------------------------------------------------------------
# Section 5: Queue state right now
# -----------------------------------------------------------------------------
def section_queue_state(conn, out):
    out.append("\n## 5. llm_overnight_queue current state\n")

    schema = q(conn, """
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_name = 'llm_overnight_queue'
        ORDER BY ordinal_position
    """)
    out.append(f"\n### Schema ({len(schema)} columns)\n\n| column | type |\n|---|---|\n")
    for c in schema:
        out.append(f"| `{c['column_name']}` | `{c['data_type']}` |\n")

    state = q(conn, """
        SELECT job_type, status, COUNT(*) AS cnt
        FROM llm_overnight_queue
        GROUP BY job_type, status
        ORDER BY status, job_type
    """)
    out.append(f"\n### Current rows by (job_type, status)\n\n| job_type | status | count |\n|---|---|---|\n")
    for r in state:
        out.append(f"| {r['job_type']} | {r['status']} | {r['cnt']} |\n")

    # The stuck running job
    out.append("\n### Currently 'running' jobs (need reset)\n")
    running = q(conn, """
        SELECT * FROM llm_overnight_queue
        WHERE status = 'running'
        ORDER BY id
    """)
    out.append(f"\nFound {len(running)} running.\n\n```\n")
    for r in running:
        out.append(f"{dict(r)}\n")
    out.append("```\n")

    # Recent failures
    out.append("\n### Last 10 failed jobs\n")
    failed = q(conn, """
        SELECT id, job_type, symbol, status, started_at, finished_at,
               COALESCE(error_message, '') AS error_message
        FROM llm_overnight_queue
        WHERE status = 'failed'
        ORDER BY finished_at DESC NULLS LAST, id DESC
        LIMIT 10
    """)
    if failed:
        out.append("\n| id | job_type | symbol | error |\n|---|---|---|---|\n")
        for r in failed:
            err = (r.get('error_message') or '')[:80].replace('|', '\\|').replace('\n', ' ')
            out.append(f"| {r['id']} | {r['job_type']} | {r.get('symbol','')} | {err} |\n")
    else:
        out.append("(none)\n")


# -----------------------------------------------------------------------------
# Section 6: Done counts (writer vs. queue mismatch)
# -----------------------------------------------------------------------------
def section_writer_mismatch(conn, out):
    out.append("\n## 6. Watch query vs. log mismatch investigation\n")

    out.append("Log shows ~30 strategy_classification completions today, but watch query shows only 2 done.\n")
    out.append("Possible explanations: (a) writer files results in `llm_overnight_results` but never updates `llm_overnight_queue.status`, or (b) the queue has duplicate rows for the same symbol.\n")

    # Check llm_overnight_results
    results_exists = q(conn, """
        SELECT 1 FROM information_schema.tables
        WHERE table_schema='public' AND table_name='llm_overnight_results'
    """)
    if results_exists:
        cnt = q(conn, """
            SELECT job_type, COUNT(*) AS cnt
            FROM llm_overnight_results
            WHERE created_at::date = CURRENT_DATE OR (created_at IS NULL AND id > (SELECT COALESCE(MAX(id),0)-200 FROM llm_overnight_results))
            GROUP BY job_type
            ORDER BY job_type
        """)
        out.append("\n### llm_overnight_results filed today (or last 200 ids)\n\n| job_type | count |\n|---|---|\n")
        for r in cnt:
            out.append(f"| {r['job_type']} | {r['cnt']} |\n")

    # Same for queue
    today_done = q(conn, """
        SELECT job_type, COUNT(*) AS cnt
        FROM llm_overnight_queue
        WHERE status = 'done'
          AND (finished_at::date = CURRENT_DATE OR finished_at IS NULL)
        GROUP BY job_type
        ORDER BY job_type
    """)
    out.append("\n### llm_overnight_queue marked done today\n\n| job_type | count |\n|---|---|\n")
    for r in today_done:
        out.append(f"| {r['job_type']} | {r['cnt']} |\n")


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=None, help="Write report to this file (default: stdout)")
    args = parser.parse_args()

    out = []
    out.append(f"# Session 34 Diagnostic Report\n")
    out.append(f"Generated: {datetime.now().isoformat(timespec='seconds')}\n")
    out.append(f"Project root: {Path.cwd()}\n")

    try:
        conn = get_db_conn()
    except Exception as e:
        out.append(f"\n**FATAL: DB connection failed: {e}**\n")
        text = "".join(out)
        if args.output:
            Path(args.output).parent.mkdir(parents=True, exist_ok=True)
            Path(args.output).write_text(text)
        else:
            print(text)
        sys.exit(1)

    try:
        section_covered_call(conn, out)
    except Exception as e:
        out.append(f"\n**Section 1 failed: {e}**\n")
    try:
        section_rag(conn, out)
    except Exception as e:
        out.append(f"\n**Section 2 failed: {e}**\n")
    try:
        section_timeouts(out)
    except Exception as e:
        out.append(f"\n**Section 3 failed: {e}**\n")
    try:
        section_job_types(out)
    except Exception as e:
        out.append(f"\n**Section 4 failed: {e}**\n")
    try:
        section_queue_state(conn, out)
    except Exception as e:
        out.append(f"\n**Section 5 failed: {e}**\n")
    try:
        section_writer_mismatch(conn, out)
    except Exception as e:
        out.append(f"\n**Section 6 failed: {e}**\n")

    conn.close()

    text = "".join(out)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(text)
        print(f"Wrote diagnostic report: {args.output}")
        print(f"Size: {len(text):,} chars")
    else:
        print(text)


if __name__ == "__main__":
    main()
