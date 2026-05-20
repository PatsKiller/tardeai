#!/usr/bin/env python3
"""migrate_journal_ux2_lesson_memory.py — Idempotent migration for Journal UX2 lesson memory tables.

Creates 3 tables IF NOT EXISTS:
  - trade_lesson_memory
  - strategy_lesson_rollup
  - closed_trade_digest_log

Read-only unless --apply is passed.
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))

from db_adapter import _get_conn

DDL_TRADE_LESSON_MEMORY = """
CREATE TABLE IF NOT EXISTS trade_lesson_memory (
    id SERIAL PRIMARY KEY,
    trade_id INTEGER,
    symbol VARCHAR(10),
    strategy_id VARCHAR(64),
    close_date DATE,
    exit_reason VARCHAR(64),
    dashboard_verdict VARCHAR(30),
    exit_quality VARCHAR(20),
    mistake_type VARCHAR(30),
    lesson_category VARCHAR(30),
    improved_lesson TEXT,
    rule_feedback TEXT,
    next_operator_action TEXT,
    action_priority VARCHAR(10),
    action_owner VARCHAR(20),
    confidence_delta VARCHAR(20),
    repeated_pattern_key VARCHAR(128),
    pattern_count INTEGER DEFAULT 1,
    pnl NUMERIC(10,2),
    r_multiple NUMERIC(6,2),
    human_review_only BOOLEAN DEFAULT TRUE,
    operator_review_status VARCHAR(30) DEFAULT 'pending',
    source_payload_hash VARCHAR(64),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(trade_id, lesson_category, source_payload_hash)
);
"""

DDL_STRATEGY_LESSON_ROLLUP = """
CREATE TABLE IF NOT EXISTS strategy_lesson_rollup (
    id SERIAL PRIMARY KEY,
    strategy_id VARCHAR(64) NOT NULL,
    period_start DATE,
    period_end DATE,
    closed_trades INTEGER DEFAULT 0,
    wins INTEGER DEFAULT 0,
    losses INTEGER DEFAULT 0,
    avg_r NUMERIC(6,2),
    realized_pnl NUMERIC(12,2),
    repeated_mistakes TEXT,
    positive_patterns TEXT,
    negative_patterns TEXT,
    confidence_delta_summary TEXT,
    review_recommendation VARCHAR(30),
    human_review_only BOOLEAN DEFAULT TRUE,
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(strategy_id, period_start, period_end)
);
"""

DDL_CLOSED_TRADE_DIGEST_LOG = """
CREATE TABLE IF NOT EXISTS closed_trade_digest_log (
    id SERIAL PRIMARY KEY,
    digest_date DATE,
    sent_at TIMESTAMPTZ,
    route_level VARCHAR(20),
    closed_count INTEGER,
    action_count INTEGER,
    lessons_count INTEGER,
    delivery_status VARCHAR(20),
    test_mode BOOLEAN DEFAULT FALSE,
    message_preview TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
"""

INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_tlm_symbol ON trade_lesson_memory (symbol);",
    "CREATE INDEX IF NOT EXISTS idx_tlm_strategy_id ON trade_lesson_memory (strategy_id);",
    "CREATE INDEX IF NOT EXISTS idx_tlm_lesson_category ON trade_lesson_memory (lesson_category);",
    "CREATE INDEX IF NOT EXISTS idx_tlm_repeated_pattern_key ON trade_lesson_memory (repeated_pattern_key);",
]


def run(args):
    conn = _get_conn()
    if conn is None:
        print("[ERROR] No database connection available.")
        return {"status": "error", "reason": "no_db_connection"}

    statements = [DDL_TRADE_LESSON_MEMORY, DDL_STRATEGY_LESSON_ROLLUP, DDL_CLOSED_TRADE_DIGEST_LOG] + INDEXES
    results = []

    cur = conn.cursor()
    for stmt in statements:
        label = stmt.strip().split("(")[0].strip()[:80]
        if args.verbose:
            print(f"  [SQL] {label}")
        if args.apply:
            try:
                cur.execute(stmt)
                results.append({"statement": label, "status": "ok"})
            except Exception as e:
                conn.rollback()
                results.append({"statement": label, "status": "error", "error": str(e)})
                print(f"  [ERROR] {label}: {e}")
        else:
            results.append({"statement": label, "status": "dry_run"})

    if args.apply:
        conn.commit()
        print(f"[OK] Migration applied: {len(results)} statements executed.")
    else:
        print(f"[DRY-RUN] Would execute {len(results)} statements. Pass --apply to run.")

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mode": "apply" if args.apply else "dry_run",
        "statements": results,
        "total": len(results),
    }

    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        print(json.dumps(report, indent=2))
    if args.output_md:
        print(f"\n## Migration Report\n")
        print(f"- Mode: {'apply' if args.apply else 'dry_run'}")
        print(f"- Statements: {len(results)}")
        for r in results:
            print(f"  - {r['statement']}: {r['status']}")

    return report


def main():
    parser = argparse.ArgumentParser(description="Migrate Journal UX2 lesson memory tables")
    parser.add_argument("--dry-run", dest="apply", action="store_false", default=False,
                        help="Preview only (default)")
    parser.add_argument("--apply", dest="apply", action="store_true",
                        help="Execute migration")
    parser.add_argument("--output-json", type=str, help="Output JSON path")
    parser.add_argument("--output-md", type=str, help="Output Markdown path")
    parser.add_argument("--verbose", action="store_true", help="Verbose output")
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
