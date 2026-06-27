#!/usr/bin/env python3
"""Prune old SUPERSEDED protection adjustment rows (bounded retention)."""
from __future__ import annotations

import argparse
import os

RETENTION_DAYS = int(os.getenv("PROTECTION_PROPOSAL_RETENTION_DAYS", "30"))


def prune(conn=None, *, dry_run: bool = False) -> dict:
    from db_adapter import _get_conn
    conn = conn or _get_conn()
    cur = conn.cursor()
    cur.execute(
        """SELECT count(*) FROM paper_protection_adjustment_proposals
           WHERE status = 'SUPERSEDED'
             AND created_at < now() - (%s * interval '1 day')""",
        (RETENTION_DAYS,),
    )
    n = int(cur.fetchone()[0] or 0)
    deleted = 0
    if n and not dry_run:
        cur.execute(
            """DELETE FROM paper_protection_adjustment_proposals
               WHERE status = 'SUPERSEDED'
                 AND created_at < now() - (%s * interval '1 day')""",
            (RETENTION_DAYS,),
        )
        deleted = cur.rowcount
        conn.commit()
    return {"retention_days": RETENTION_DAYS, "eligible": n, "deleted": deleted, "dry_run": dry_run}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    import json
    print(json.dumps(prune(dry_run=args.dry_run), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())