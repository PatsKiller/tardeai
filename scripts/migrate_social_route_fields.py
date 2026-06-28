#!/usr/bin/env python3
"""P0-3 migration — persist social route/actionability as durable, first-class columns.

Additive and idempotent (ADD COLUMN IF NOT EXISTS). Backward-compatible: existing rows keep
NULL, all existing code paths are unaffected. No data modified, no broker calls.

    python3 scripts/migrate_social_route_fields.py            # apply
    python3 scripts/migrate_social_route_fields.py --dry-run  # print DDL only
    python3 scripts/migrate_social_route_fields.py --check    # report column presence
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# table -> [(column, type)]
COLUMNS = {
    "scalp_scan_results": [
        ("route", "TEXT"), ("route_actionability", "TEXT"), ("route_strategy_id", "TEXT"),
        ("route_reason_codes", "JSONB"), ("discovery_trace_id", "TEXT"),
        ("catalyst_verified", "BOOLEAN"), ("catalyst_source", "TEXT"),
    ],
    "trade_ai_scans": [
        ("route", "TEXT"), ("route_actionability", "TEXT"), ("route_strategy_id", "TEXT"),
        ("route_reason_codes", "JSONB"), ("discovery_trace_id", "TEXT"),
    ],
}


def _ddl():
    out = []
    for table, cols in COLUMNS.items():
        for name, typ in cols:
            out.append(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {name} {typ}")
    return out


def check(conn):
    cur = conn.cursor()
    res = {}
    for table, cols in COLUMNS.items():
        cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name=%s", (table,))
        have = {r[0] for r in cur.fetchall()}
        res[table] = {name: (name in have) for name, _ in cols}
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    if args.dry_run:
        for s in _ddl():
            print(s + ";")
        return 0

    from db_adapter import get_connection
    conn = get_connection()
    if args.check:
        for t, cols in check(conn).items():
            print(f"  {t}: " + ", ".join(f"{c}={'ok' if v else 'MISSING'}" for c, v in cols.items()))
        return 0

    cur = conn.cursor()
    applied = 0
    for stmt in _ddl():
        try:
            cur.execute(stmt)
            applied += 1
        except Exception as e:
            conn.rollback()
            print(f"  [WARN] {stmt}: {e}")
    conn.commit()
    res = check(conn)
    allok = all(all(v.values()) for v in res.values())
    print(f"  applied {applied} statements; all columns present: {allok}")
    return 0 if allok else 1


if __name__ == "__main__":
    raise SystemExit(main())
