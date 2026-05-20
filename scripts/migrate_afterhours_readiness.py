#!/usr/bin/env python3
"""migrate_afterhours_readiness.py — Idempotent migration for afterhours readiness tables.

Read-only by default (--dry-run). Use --apply to execute DDL.
No trades. No orders.
"""
import argparse, json, sys
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))

TABLES = {
    "afterhours_candidate_snapshot": """\
CREATE TABLE IF NOT EXISTS afterhours_candidate_snapshot (
    id SERIAL PRIMARY KEY,
    snapshot_id VARCHAR(64),
    run_date DATE,
    session VARCHAR(20),
    symbol VARCHAR(10) NOT NULL,
    source_screeners TEXT,
    catalog_status VARCHAR(20),
    membership_status VARCHAR(20),
    strategy_fit_status VARCHAR(20),
    top_strategy VARCHAR(64),
    top_strategy_score INTEGER,
    quote_status VARCHAR(20),
    readiness_status VARCHAR(40),
    blockers TEXT,
    next_required_action TEXT,
    proposal_candidate_allowed BOOLEAN DEFAULT FALSE,
    executable_now BOOLEAN DEFAULT FALSE,
    human_review_only BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(snapshot_id, symbol)
);""",
    "afterhours_readiness_run": """\
CREATE TABLE IF NOT EXISTS afterhours_readiness_run (
    id SERIAL PRIMARY KEY,
    run_id VARCHAR(64),
    run_date DATE,
    session VARCHAR(20),
    started_at TIMESTAMPTZ DEFAULT NOW(),
    symbols_considered INTEGER DEFAULT 0,
    strategy_fit_evaluated INTEGER DEFAULT 0,
    ready_for_review INTEGER DEFAULT 0,
    proposal_candidate_pending INTEGER DEFAULT 0,
    needs_data INTEGER DEFAULT 0,
    blocked INTEGER DEFAULT 0,
    no_fit INTEGER DEFAULT 0,
    run_status VARCHAR(20),
    underfilled_reason TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(run_id)
);""",
}

INDEX_DEFS = [
    ("idx_acs_symbol",           "afterhours_candidate_snapshot", "symbol"),
    ("idx_acs_readiness_status", "afterhours_candidate_snapshot", "readiness_status"),
    ("idx_acs_run_date",         "afterhours_candidate_snapshot", "run_date"),
    ("idx_acs_top_strategy",     "afterhours_candidate_snapshot", "top_strategy"),
]


def _table_exists(conn, table_name):
    cur = conn.cursor()
    cur.execute(
        "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = %s)",
        [table_name],
    )
    return cur.fetchone()[0]


def _index_exists(conn, idx_name):
    cur = conn.cursor()
    cur.execute(
        "SELECT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = %s)",
        [idx_name],
    )
    return cur.fetchone()[0]


def main():
    p = argparse.ArgumentParser(description="Migrate: create afterhours readiness tables")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", default=True,
                       help="Report what would be created (default)")
    mode.add_argument("--apply", action="store_true",
                       help="Execute DDL statements")
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    dry_run = not args.apply

    from db_adapter import _get_conn
    conn = _get_conn()
    if not conn:
        print("ERROR: no DB connection"); sys.exit(1)

    actions = []

    # Check tables
    table_status = {}
    for tname, ddl in TABLES.items():
        already = _table_exists(conn, tname)
        table_status[tname] = already
        if not already:
            actions.append({"type": "create_table", "table": tname, "sql": ddl})
        else:
            actions.append({"type": "skip_table", "table": tname, "reason": "already exists"})

    # Check indexes
    for idx_name, tname, col in INDEX_DEFS:
        already = _index_exists(conn, idx_name)
        sql = f"CREATE INDEX IF NOT EXISTS {idx_name} ON {tname} ({col});"
        if not already:
            actions.append({"type": "create_index", "index": idx_name, "column": col, "sql": sql})
        else:
            actions.append({"type": "skip_index", "index": idx_name, "reason": "already exists"})

    if dry_run:
        if args.verbose:
            print("DRY-RUN — afterhours readiness tables")
            for tname, existed in table_status.items():
                print(f"  Table '{tname}' exists: {existed}")
            for a in actions:
                tag = a["type"].upper()
                name = a.get("table") or a.get("index")
                reason = a.get("reason", "would execute")
                print(f"  [{tag}] {name}: {reason}")
    else:
        cur = conn.cursor()
        for a in actions:
            if a["type"] in ("create_table", "create_index"):
                if args.verbose:
                    print(f"EXEC: {a['sql'][:80]}...")
                cur.execute(a["sql"])
        conn.commit()
        if args.verbose:
            print("Migration applied successfully.")

    conn.close()

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "dry_run" if dry_run else "apply",
        "tables": table_status,
        "actions": actions,
    }

    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))

    if args.output_md:
        Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
        md = [
            "# Migration: afterhours readiness tables\n",
            f"Mode: **{'dry_run' if dry_run else 'apply'}**\n",
        ]
        for tname, existed in table_status.items():
            md.append(f"Table `{tname}` existed: {existed}\n")
        md += [
            "## Actions",
            "| Type | Object | Detail |",
            "|------|--------|--------|",
        ]
        for a in actions:
            name = a.get("table") or a.get("index")
            detail = a.get("reason", "executed" if not dry_run else "would execute")
            md.append(f"| {a['type']} | {name} | {detail} |")
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
