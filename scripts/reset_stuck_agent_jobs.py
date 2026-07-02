#!/usr/bin/env python3
"""reset_stuck_agent_jobs.py — reaper for zombie 'processing' rows in the watchlist pipeline.

Covers BOTH tables that fail the same way when the worker dies / times out (12m cap) mid-work:
- watchlist_agent_jobs: job stays 'processing' forever (no updated_at to age it out) and never
  re-runs, silently blocking throughput (2026-06-29: KTOS/EVER stuck ~5h) → reset to 'queued'.
- watchlist_analysis_maturity.final_synthesis_status: run_synthesis sets 'processing' before the
  LLM call; a mid-synthesis death strands it there, and _check_synthesis_ready skips
  completed/processing/queued — so the symbol is silently excluded from CIO-view refreshes
  (2026-07-01: 19 symbols found stuck, CEPO 34 days) → reset to 'pending' so
  _check_pending_synthesis picks it up on the next worker run.

Read/DB-state only. No broker writes. Default DRY-RUN; --apply to reset.

    python3 scripts/reset_stuck_agent_jobs.py            # dry-run: show stuck jobs + syntheses
    python3 scripts/reset_stuck_agent_jobs.py --apply    # reset both zombie kinds
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
               EXTRACT(EPOCH FROM (now() - COALESCE(started_at, created_at)))/60.0 AS age_min
        FROM watchlist_agent_jobs
        WHERE status = 'processing'
          AND COALESCE(started_at, created_at) < now() - interval '%s minutes'
        ORDER BY COALESCE(started_at, created_at)
    """ % int(minutes))
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def reset(conn, minutes: int = STUCK_MINUTES) -> int:
    cur = conn.cursor()
    cur.execute("""
        UPDATE watchlist_agent_jobs SET status='queued', started_at=NULL
        WHERE status = 'processing'
          AND COALESCE(started_at, created_at) < now() - interval '%s minutes'
    """ % int(minutes))
    n = cur.rowcount
    conn.commit()
    return n


def find_stuck_synthesis(conn, minutes: int = STUCK_MINUTES) -> list:
    """Maturity rows stranded in final_synthesis_status='processing' (this table HAS updated_at)."""
    cur = conn.cursor()
    cur.execute("""
        SELECT symbol, EXTRACT(EPOCH FROM (now() - updated_at))/60.0 AS age_min
        FROM watchlist_analysis_maturity
        WHERE final_synthesis_status = 'processing' AND updated_at < now() - interval '%s minutes'
        ORDER BY updated_at
    """ % int(minutes))
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def reset_synthesis(conn, minutes: int = STUCK_MINUTES) -> int:
    cur = conn.cursor()
    cur.execute("""
        UPDATE watchlist_analysis_maturity
        SET final_synthesis_status='pending', updated_at=now()
        WHERE final_synthesis_status='processing' AND updated_at < now() - interval '%s minutes'
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
    stuck_syn = find_stuck_synthesis(conn, args.minutes)
    out = {"ok": True, "stuck_count": len(stuck), "threshold_minutes": args.minutes,
           "stuck": [{"id": s["id"], "request_type": s["request_type"], "symbol": s["symbol"],
                      "age_min": round(float(s["age_min"]), 1)} for s in stuck[:20]],
           "stuck_synthesis_count": len(stuck_syn),
           "stuck_synthesis": [{"symbol": s["symbol"], "age_min": round(float(s["age_min"]), 1)}
                               for s in stuck_syn[:20]],
           "safety_note": "DB-state only (jobs processing→queued, synthesis processing→pending). No broker writes."}
    if args.apply:
        out["reset"] = reset(conn, args.minutes)
        out["reset_synthesis"] = reset_synthesis(conn, args.minutes)
        out["dry_run"] = False
    else:
        out["dry_run"] = True
    print(json.dumps(out, indent=2, default=str) if args.json else
          f"stuck(processing>{args.minutes}m) jobs={out['stuck_count']} synthesis={out['stuck_synthesis_count']}"
          + (f" reset={out['reset']}+{out['reset_synthesis']}" if args.apply else " (dry-run)"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
