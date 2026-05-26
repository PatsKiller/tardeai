#!/usr/bin/env python3
"""migrate_screener_arch4_strategy_fit_audit.py — Idempotent migration for universe_strategy_fit_audit.

Read-only by default (--dry-run). Use --apply to execute DDL.
No trades. No orders.
"""
import argparse, json, sys
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))

TABLE_NAME = "universe_strategy_fit_audit"

CREATE_TABLE_SQL = """\
CREATE TABLE IF NOT EXISTS universe_strategy_fit_audit (
    id SERIAL PRIMARY KEY,
    audit_run_id VARCHAR(64) NOT NULL,
    symbol VARCHAR(10) NOT NULL,
    strategy_id VARCHAR(64) NOT NULL,
    strategy_family VARCHAR(32),
    evaluated_at TIMESTAMPTZ DEFAULT NOW(),
    quote_status VARCHAR(20),
    liquidity_gate_status VARCHAR(20),
    family_gate_status VARCHAR(20),
    required_data_status VARCHAR(20),
    missing_fields TEXT,
    scoring_weights_used BOOLEAN,
    raw_score INTEGER DEFAULT 0,
    normalized_score INTEGER DEFAULT 0,
    match_strength VARCHAR(20),
    criteria_met TEXT,
    criteria_failed TEXT,
    blockers TEXT,
    top_match_for_symbol BOOLEAN DEFAULT FALSE,
    recommendation VARCHAR(40),
    human_review_only BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(audit_run_id, symbol, strategy_id)
);
"""

INDEX_DEFS = [
    ("idx_usfa_audit_run_id",     "audit_run_id"),
    ("idx_usfa_symbol",           "symbol"),
    ("idx_usfa_strategy_id",      "strategy_id"),
    ("idx_usfa_match_strength",   "match_strength"),
    ("idx_usfa_recommendation",   "recommendation"),
    ("idx_usfa_top_match",        "top_match_for_symbol"),
]


def _table_exists(conn):
    cur = conn.cursor()
    cur.execute(
        "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = %s)",
        [TABLE_NAME],
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
    p = argparse.ArgumentParser(description="Migrate: create universe_strategy_fit_audit table")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", default=True,
                       help="Report what would be created (default)")
    mode.add_argument("--apply", action="store_true",
                       help="Execute DDL statements")
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    # --apply flips dry-run off
    dry_run = not args.apply

    from db_adapter import _get_conn
    conn = _get_conn()
    if not conn:
        print("ERROR: no DB connection"); sys.exit(1)

    table_already = _table_exists(conn)
    idx_status = {}
    for idx_name, _ in INDEX_DEFS:
        idx_status[idx_name] = _index_exists(conn, idx_name)

    actions = []
    if not table_already:
        actions.append({"type": "create_table", "table": TABLE_NAME, "sql": CREATE_TABLE_SQL.strip()})
    else:
        actions.append({"type": "skip_table", "table": TABLE_NAME, "reason": "already exists"})

    for idx_name, col in INDEX_DEFS:
        sql = f"CREATE INDEX IF NOT EXISTS {idx_name} ON {TABLE_NAME} ({col});"
        if not idx_status[idx_name]:
            actions.append({"type": "create_index", "index": idx_name, "column": col, "sql": sql})
        else:
            actions.append({"type": "skip_index", "index": idx_name, "reason": "already exists"})

    if dry_run:
        if args.verbose:
            print(f"DRY-RUN — table '{TABLE_NAME}' exists: {table_already}")
            for a in actions:
                tag = a["type"].upper()
                name = a.get("table") or a.get("index")
                reason = a.get("reason", "would execute")
                print(f"  [{tag}] {name}: {reason}")
    else:
        # Apply mode
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
        "table": TABLE_NAME,
        "table_existed": table_already,
        "actions": actions,
    }

    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))

    if args.output_md:
        Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
        md = [
            f"# Migration: {TABLE_NAME}\n",
            f"Mode: **{'dry_run' if dry_run else 'apply'}**\n",
            f"Table existed: {table_already}\n",
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
