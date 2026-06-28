#!/usr/bin/env python3
"""P0-3 migration — persist Social Scout operator-awareness metadata as durable columns.

Additive and idempotent (ADD COLUMN IF NOT EXISTS). Backward-compatible: existing rows keep NULL,
all existing code paths are unaffected. No data modified, no broker calls, no raw social-post text
stored (only derived pillar metadata + the operator pill; lineage stays via discovery_trace_id).

    python3 scripts/migrate_social_scout_fields.py            # apply
    python3 scripts/migrate_social_scout_fields.py --dry-run  # print DDL only
    python3 scripts/migrate_social_scout_fields.py --check    # report column presence
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Scout metadata columns added to BOTH discovery tables. Arrays are stored as JSONB where supported
# (DB layer falls back to JSON text — see stamp_scout_fields, which json.dumps the arrays).
_SCOUT_COLUMNS = [
    ("scout_status", "TEXT"),
    ("scout_pillar_count", "INTEGER"),
    ("scout_pillars_met", "JSONB"),
    ("scout_pillars_missing", "JSONB"),
    ("operator_pill", "TEXT"),
    ("operator_subtitle", "TEXT"),
    ("operator_color_token", "TEXT"),
    ("not_validation_ready", "BOOLEAN"),
    ("not_tradeable", "BOOLEAN"),
]

COLUMNS = {
    "scalp_scan_results": list(_SCOUT_COLUMNS),
    "trade_ai_scans": list(_SCOUT_COLUMNS),
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
