#!/usr/bin/env python3
"""report_screener_membership_status.py — Screener membership lifecycle report.

Read-only.

Usage:
    .venv/bin/python scripts/report_screener_membership_status.py --verbose
"""
import argparse, json, sys
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))


def _db_query(sql, params=None, fetch="all"):
    try:
        from db_adapter import _get_conn
        conn = _get_conn()
        if not conn: return [] if fetch == "all" else None
        cur = conn.cursor()
        cur.execute(sql, params or [])
        if fetch == "one":
            row = cur.fetchone()
            return dict(zip([d[0] for d in cur.description], row)) if row else None
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        conn.close()
        return [dict(zip(cols, r)) for r in rows]
    except Exception:
        return [] if fetch == "all" else None


def main():
    p = argparse.ArgumentParser(description="Screener membership status (read-only)")
    p.add_argument("--since-days", type=int, default=14)
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    total = _db_query("SELECT count(*) as c FROM screener_symbol_membership", fetch="one") or {}
    by_status = _db_query("SELECT membership_status, count(*) as c FROM screener_symbol_membership GROUP BY membership_status ORDER BY c DESC") or []
    history_count = _db_query("SELECT count(*) as c FROM screener_symbol_membership_history", fetch="one") or {}
    by_event = _db_query("SELECT event_type, count(*) as c FROM screener_symbol_membership_history GROUP BY event_type ORDER BY c DESC") or []

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_memberships": int(total.get("c", 0)),
        "by_status": [{k: v for k, v in r.items()} for r in by_status],
        "history_events": int(history_count.get("c", 0)),
        "by_event_type": [{k: v for k, v in r.items()} for r in by_event],
    }

    if args.verbose:
        print(f"Membership Status — {report['total_memberships']} memberships, {report['history_events']} events")
        for s in by_status:
            print(f"  {s['membership_status']}: {s['c']}")
        for e in by_event:
            print(f"  event {e['event_type']}: {e['c']}")

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        md = [f"# Screener Membership Status\n",
              f"Memberships: {report['total_memberships']} | Events: {report['history_events']}"]
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
