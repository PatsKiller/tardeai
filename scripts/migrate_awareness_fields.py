#!/usr/bin/env python3
"""P2-4 migration — persist awareness / alias metadata on trade_ai_scans.

    python3 scripts/migrate_awareness_fields.py            # apply
    python3 scripts/migrate_awareness_fields.py --dry-run
    python3 scripts/migrate_awareness_fields.py --check
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_COLUMNS = [
    ("awareness_status", "TEXT"),
    ("setup_class", "TEXT"),
    ("symbol_candidate", "TEXT"),
    ("symbol_alias_confidence", "REAL"),
    ("manual_review_required", "BOOLEAN"),
]


def _ddl() -> list[str]:
    return [f"ALTER TABLE trade_ai_scans ADD COLUMN IF NOT EXISTS {name} {typ}" for name, typ in _COLUMNS]


def check(conn) -> dict[str, bool]:
    cur = conn.cursor()
    cur.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name='trade_ai_scans'"
    )
    have = {r[0] for r in cur.fetchall()}
    return {name: name in have for name, _ in _COLUMNS}


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
        for col, ok in check(conn).items():
            print(f"  {col}: {'ok' if ok else 'MISSING'}")
        return 0

    cur = conn.cursor()
    for stmt in _ddl():
        cur.execute(stmt)
    conn.commit()
    print(f"Applied {len(_ddl())} awareness columns to trade_ai_scans")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())