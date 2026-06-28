#!/usr/bin/env python3
"""P0-6 migration — add nullable discovery_trace_id to the social→trade lineage tables.

Additive and idempotent (ADD COLUMN IF NOT EXISTS). Backward-compatible: existing rows keep
NULL, all existing code paths are unaffected. No data is modified, no broker calls.

    python3 scripts/migrate_discovery_trace_id.py            # apply
    python3 scripts/migrate_discovery_trace_id.py --dry-run  # print DDL only
    python3 scripts/migrate_discovery_trace_id.py --check    # report column presence
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

TABLES = [
    "scalp_scan_results",
    "trade_ai_scans",
    "strategy_signals",
    "paper_trade_proposals",
    "paper_trades",
]


def _ddl(table: str) -> list[str]:
    return [
        f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS discovery_trace_id TEXT",
        f"CREATE INDEX IF NOT EXISTS idx_{table}_discovery_trace "
        f"ON {table}(discovery_trace_id) WHERE discovery_trace_id IS NOT NULL",
    ]


def check(conn) -> dict:
    cur = conn.cursor()
    out = {}
    for t in TABLES:
        try:
            cur.execute("SELECT 1 FROM information_schema.columns "
                        "WHERE table_name=%s AND column_name='discovery_trace_id'", (t,))
            out[t] = cur.fetchone() is not None
        except Exception as e:
            out[t] = f"error: {e}"
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    if args.dry_run:
        for t in TABLES:
            for stmt in _ddl(t):
                print(stmt + ";")
        return 0

    from db_adapter import get_connection
    conn = get_connection()

    if args.check:
        for t, ok in check(conn).items():
            print(f"  {t}: discovery_trace_id {'present' if ok is True else ok}")
        return 0

    cur = conn.cursor()
    applied = 0
    for t in TABLES:
        for stmt in _ddl(t):
            try:
                cur.execute(stmt)
                applied += 1
            except Exception as e:
                conn.rollback()
                print(f"  [WARN] {t}: {e}")
        conn.commit()
    res = check(conn)
    print(f"  applied {applied} statements; columns: "
          + ", ".join(f"{t}={'ok' if v is True else v}" for t, v in res.items()))
    return 0 if all(v is True for v in res.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
