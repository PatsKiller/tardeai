#!/usr/bin/env python3
"""hermes_score_history_retention.py — Prune old Hermes score snapshots (audit 2026-07-02).

Keeps one row per (symbol, 6h bucket) for rows older than retention window.
Deletes raw ticks beyond retention to stop 3M+ row bloat.

  python3 scripts/hermes_score_history_retention.py --dry-run
  python3 scripts/hermes_score_history_retention.py --apply --days 90
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


def run(days: int = 90, apply: bool = False) -> dict:
    from db_adapter import _get_conn
    conn = _get_conn()
    cur = conn.cursor()

    cur.execute("SELECT count(*) FROM hermes_score_history")
    before = cur.fetchone()[0]

    cur.execute(
        f"""SELECT count(*) FROM hermes_score_history
            WHERE scored_at < NOW() - INTERVAL '{int(days)} days'"""
    )
    older = cur.fetchone()[0]

    deleted = 0
    if apply and older > 0:
        # Keep latest per symbol per 6h bucket in the retention window; delete the rest older than days.
        cur.execute(f"""
            DELETE FROM hermes_score_history h
            WHERE h.scored_at < NOW() - INTERVAL '{int(days)} days'
              AND h.id NOT IN (
                SELECT DISTINCT ON (symbol, date_trunc('hour', scored_at))
                       id
                FROM hermes_score_history
                WHERE scored_at < NOW() - INTERVAL '{int(days)} days'
                  AND EXTRACT(hour FROM scored_at)::int %% 6 = 0
                ORDER BY symbol, date_trunc('hour', scored_at), scored_at DESC
              )
        """)
        deleted = cur.rowcount
        conn.commit()

    cur.execute("SELECT count(*) FROM hermes_score_history")
    after = cur.fetchone()[0]

    out = {
        "ok": True,
        "apply": apply,
        "retention_days": days,
        "rows_before": before,
        "rows_older_than_window": older,
        "rows_deleted": deleted,
        "rows_after": after,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    print(json.dumps(out, indent=2))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    run(days=args.days, apply=args.apply and not args.dry_run)


if __name__ == "__main__":
    main()