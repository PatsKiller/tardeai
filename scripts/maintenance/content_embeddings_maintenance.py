#!/usr/bin/env python3
"""WS5 — Explicit maintenance for content_embeddings (never auto).

Usage:
  # Report only
  .venv/bin/python scripts/maintenance/content_embeddings_maintenance.py --report

  # REINDEX (online-ish, safer than VACUUM FULL)
  .venv/bin/python scripts/maintenance/content_embeddings_maintenance.py --reindex --confirm

  # VACUUM FULL (locks table; requires --confirm and --i-know-this-locks)
  .venv/bin/python scripts/maintenance/content_embeddings_maintenance.py \\
      --vacuum-full --confirm --i-know-this-locks

Does NOT auto-delete multi-GB home archives. Does NOT run from health-agent.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]


def _dsn() -> str:
    dsn = os.environ.get("DATABASE_URL") or os.environ.get("TRADEAI_DSN")
    if dsn:
        return dsn
    # fall back to SM-rendered env if present
    envf = Path(f"/run/user/{os.getuid()}/tradeai/env")
    if envf.exists():
        for line in envf.read_text().splitlines():
            if line.startswith("DATABASE_URL="):
                return line.split("=", 1)[1].strip().strip('"')
    raise SystemExit("No DATABASE_URL/TRADEAI_DSN — refuse to guess.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--reindex", action="store_true")
    ap.add_argument("--vacuum-full", action="store_true")
    ap.add_argument("--confirm", action="store_true", help="Required for mutating ops")
    ap.add_argument("--i-know-this-locks", action="store_true", help="Required for VACUUM FULL")
    args = ap.parse_args()

    import psycopg2

    dsn = _dsn()
    conn = psycopg2.connect(dsn)
    conn.autocommit = True
    cur = conn.cursor()

    if args.report or not (args.reindex or args.vacuum_full):
        cur.execute(
            """
            SELECT pg_size_pretty(pg_total_relation_size('content_embeddings')),
                   (SELECT count(*) FROM content_embeddings)
            """
        )
        size, n = cur.fetchone()
        print(f"content_embeddings rows={n} total_size={size}")
        cur.execute(
            """
            SELECT count(*) FROM content_embeddings ce
            WHERE ce.source_type = 'news'
              AND NOT EXISTS (SELECT 1 FROM news_articles na WHERE na.id = ce.source_id::int)
            """
        )
        orphans = cur.fetchone()[0]
        print(f"news orphans (approx)={orphans}")
        if not (args.reindex or args.vacuum_full):
            return 0

    if args.reindex:
        if not args.confirm:
            print("REFUSE: --reindex requires --confirm", file=sys.stderr)
            return 2
        print("REINDEX content_embeddings …")
        cur.execute("REINDEX TABLE content_embeddings")
        print("REINDEX done")

    if args.vacuum_full:
        if not args.confirm or not args.i_know_this_locks:
            print(
                "REFUSE: --vacuum-full requires --confirm AND --i-know-this-locks",
                file=sys.stderr,
            )
            return 2
        print("VACUUM FULL content_embeddings (table locked) …")
        cur.execute("VACUUM FULL content_embeddings")
        print("VACUUM FULL done")

    cur.close()
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
