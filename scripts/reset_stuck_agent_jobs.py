#!/usr/bin/env python3
"""reset_stuck_agent_jobs.py — reaper for zombie watchlist_agent_jobs stuck in 'processing'.

The worker (process_watchlist_agent_jobs) marks a job 'processing', and if it dies / times out (12m
cap) mid-job the row stays 'processing' forever — there is no `updated_at` to age it out, so it never
re-runs and silently blocks throughput (seen 2026-06-29: KTOS/EVER rows stuck 'processing' ~5h). This
resets jobs that have been 'processing' far longer than any real job could take back to 'queued' so the
worker picks them up again.

Read/DB-state only. No broker writes. Default DRY-RUN; --apply to reset.

    python3 scripts/reset_stuck_agent_jobs.py            # dry-run: show stuck jobs
    python3 scripts/reset_stuck_agent_jobs.py --apply    # reset processing>threshold → queued
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

STUCK_MINUTES = 30   # a real job finishes in minutes; >30m in 'processing' is a zombie


def find_stuck(conn, minutes: int = STUCK_MINUTES) -> list:
    cur = conn.cursor()
    cur.execute("""
        SELECT id, request_type, symbol,
               EXTRACT(EPOCH FROM (now() - created_at))/60.0 AS age_min
        FROM watchlist_agent_jobs
        WHERE status = 'processing' AND created_at < now() - interval '%s minutes'
        ORDER BY created_at
    """ % int(minutes))
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def reset(conn, minutes: int = STUCK_MINUTES) -> int:
    cur = conn.cursor()
    cur.execute("""
        UPDATE watchlist_agent_jobs SET status='queued'
        WHERE status='processing' AND created_at < now() - interval '%s minutes'
    """ % int(minutes))
    n = cur.rowcount
    conn.commit()
    return n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="reset stuck 'processing' jobs to 'queued'")
    ap.add_argument("--minutes", type=int, default=STUCK_MINUTES)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    try:
        from db_adapter import get_connection
        conn = get_connection()
    except Exception as e:
        print(json.dumps({"ok": False, "warning": f"db unavailable: {str(e)[:80]}"}))
        return 0
    stuck = find_stuck(conn, args.minutes)
    out = {"ok": True, "stuck_count": len(stuck), "threshold_minutes": args.minutes,
           "stuck": [{"id": s["id"], "request_type": s["request_type"], "symbol": s["symbol"],
                      "age_min": round(float(s["age_min"]), 1)} for s in stuck[:20]],
           "safety_note": "DB-state only (reset processing→queued). No broker writes."}
    if args.apply:
        out["reset"] = reset(conn, args.minutes)
        out["dry_run"] = False
    else:
        out["dry_run"] = True
    print(json.dumps(out, indent=2, default=str) if args.json else
          f"stuck(processing>{args.minutes}m)={out['stuck_count']}"
          + (f" reset={out['reset']}" if args.apply else " (dry-run)"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
