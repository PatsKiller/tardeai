#!/usr/bin/env python3
"""db_storage_report.py — table size + retention-eligibility snapshot.

Usage:
  .venv/bin/python scripts/db_storage_report.py
  .venv/bin/python scripts/db_storage_report.py --json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

# load DB_PASSWORD
if not os.getenv("DB_PASSWORD"):
    try:
        for line in (ROOT / ".env").read_text().splitlines():
            if line.startswith("DB_PASSWORD="):
                os.environ["DB_PASSWORD"] = line.split("=", 1)[1].strip().strip("'\"")
    except Exception:
        pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--limit", type=int, default=30)
    args = ap.parse_args()
    import psycopg2
    conn = psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432")),
        dbname=os.getenv("DB_NAME", "trade_ai"),
        user=os.getenv("DB_USER", "trade_ai"),
        password=os.getenv("DB_PASSWORD", ""),
    )
    cur = conn.cursor()
    cur.execute("SELECT pg_database_size(current_database())")
    db_bytes = cur.fetchone()[0]
    cur.execute("""
        SELECT c.relname,
               pg_total_relation_size(c.oid) AS bytes,
               COALESCE(s.n_live_tup, 0) AS live_rows
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        LEFT JOIN pg_stat_user_tables s ON s.relid = c.oid
        WHERE n.nspname = 'public' AND c.relkind = 'r'
        ORDER BY pg_total_relation_size(c.oid) DESC
        LIMIT %s
    """, (args.limit,))
    rows = [
        {"table": r[0], "bytes": r[1], "gb": round(r[1] / 1e9, 3), "live_rows": int(r[2])}
        for r in cur.fetchall()
    ]
    # flag tables not in db_retention POLICIES
    try:
        from db_retention import POLICIES
        covered = {t for t, _, _ in POLICIES}
    except Exception:
        covered = set()
    for r in rows:
        r["in_db_retention_policy"] = r["table"] in covered

    out = {
        "db_bytes": db_bytes,
        "db_gb": round(db_bytes / 1e9, 2),
        "top_tables": rows,
        "uncovered_top": [r["table"] for r in rows if not r["in_db_retention_policy"]][:15],
    }
    if args.json:
        print(json.dumps(out, indent=2))
    else:
        print(f"Database size: {out['db_gb']} GB")
        print(f"{'Table':<40} {'GB':>8} {'Rows':>12} Policy")
        print("-" * 70)
        for r in rows:
            flag = "yes" if r["in_db_retention_policy"] else "NO"
            print(f"{r['table']:<40} {r['gb']:>8.3f} {r['live_rows']:>12,} {flag}")
        if out["uncovered_top"]:
            print("\nTop tables missing from db_retention POLICIES:")
            for t in out["uncovered_top"]:
                print(f"  - {t}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
