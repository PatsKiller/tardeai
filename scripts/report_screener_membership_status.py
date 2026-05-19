#!/usr/bin/env python3
"""report_screener_membership_status.py — Screener membership lifecycle report.

Read-only. No trades. No orders. No mutations.

Usage:
    .venv/bin/python scripts/report_screener_membership_status.py --verbose
    .venv/bin/python scripts/report_screener_membership_status.py --since-days 14 --output-json out.json --output-md out.md --verbose
"""
import argparse, json, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))


def _db_query(conn, sql, params=None, fetch="all"):
    cur = conn.cursor()
    cur.execute(sql, params or [])
    if fetch == "one":
        row = cur.fetchone()
        return dict(zip([d[0] for d in cur.description], row)) if row else {}
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in rows]


def main():
    p = argparse.ArgumentParser(description="Screener membership status (read-only)")
    p.add_argument("--since-days", type=int, default=14)
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    from db_adapter import _get_conn
    conn = _get_conn()
    if not conn:
        print("ERROR: no DB connection")
        sys.exit(1)

    since = datetime.now(timezone.utc) - timedelta(days=args.since_days)

    total = _db_query(conn, "SELECT count(*) as c FROM screener_symbol_membership", fetch="one")
    by_status = _db_query(conn, "SELECT membership_status, count(*) as c FROM screener_symbol_membership GROUP BY membership_status ORDER BY c DESC")
    history_total = _db_query(conn, "SELECT count(*) as c FROM screener_symbol_membership_history", fetch="one")
    by_event = _db_query(conn, "SELECT event_type, count(*) as c FROM screener_symbol_membership_history GROUP BY event_type ORDER BY c DESC")

    # Multi-screener symbols
    multi = _db_query(conn, "SELECT count(*) as c FROM (SELECT symbol FROM screener_symbol_membership GROUP BY symbol HAVING count(*) > 1) sub", fetch="one")

    # Dropped from all screeners
    dropped_all = _db_query(conn, """
        SELECT count(DISTINCT symbol) as c FROM screener_symbol_membership
        WHERE membership_status IN ('dropped','stale','expired')
        AND symbol NOT IN (SELECT symbol FROM screener_symbol_membership WHERE membership_status = 'present')
    """, fetch="one")

    # Symbols missing from recent scans (not yet marked)
    missing_3d = _db_query(conn, """
        SELECT count(*) as c FROM screener_symbol_membership m
        WHERE membership_status = 'present'
        AND NOT EXISTS (
            SELECT 1 FROM trade_ai_scans s
            WHERE s.symbol = m.symbol AND s.source = m.screener_id
            AND s.scanned_at > NOW() - INTERVAL '3 days'
        )
    """, fetch="one")

    # Screeners with stale data
    stale_screeners = _db_query(conn, """
        SELECT screener_id, count(*) as c,
               MAX(last_seen_in_screener_at) as latest_seen
        FROM screener_symbol_membership
        WHERE membership_status IN ('stale','expired')
        GROUP BY screener_id ORDER BY c DESC
    """)

    # Status map
    status_map = {r["membership_status"]: int(r["c"]) for r in by_status}
    event_map = {r["event_type"]: int(r["c"]) for r in by_event}

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "since_days": args.since_days,
        "total_memberships": int(total.get("c", 0)),
        "present": status_map.get("present", 0),
        "dropped": status_map.get("dropped", 0),
        "stale": status_map.get("stale", 0),
        "expired": status_map.get("expired", 0),
        "reentered": status_map.get("reentered", 0),
        "by_status": by_status,
        "history_events": int(history_total.get("c", 0)),
        "entered_events": event_map.get("entered", 0),
        "present_events": event_map.get("present", 0),
        "dropped_events": event_map.get("dropped", 0),
        "reentered_events": event_map.get("reentered", 0),
        "stale_events": event_map.get("stale", 0),
        "expired_events": event_map.get("expired", 0),
        "by_event_type": by_event,
        "multi_screener_symbols": int(multi.get("c", 0)),
        "dropped_from_all_screeners": int(dropped_all.get("c", 0)),
        "present_but_missing_3d": int(missing_3d.get("c", 0)),
        "screeners_with_stale_membership": [{k: str(v) if k == "latest_seen" else v for k, v in s.items()} for s in stale_screeners],
        "lifecycle_detection_working": status_map.get("dropped", 0) > 0 or status_map.get("reentered", 0) > 0,
    }

    if args.verbose:
        print(f"Membership Status Report")
        print(f"  Total memberships: {report['total_memberships']}")
        print(f"  Present: {report['present']}")
        print(f"  Dropped: {report['dropped']}")
        print(f"  Stale: {report['stale']}")
        print(f"  Expired: {report['expired']}")
        print(f"  Reentered: {report['reentered']}")
        print(f"  History events: {report['history_events']}")
        print(f"    entered: {report['entered_events']}")
        print(f"    present: {report['present_events']}")
        print(f"    dropped: {report['dropped_events']}")
        print(f"    reentered: {report['reentered_events']}")
        print(f"  Multi-screener symbols: {report['multi_screener_symbols']}")
        print(f"  Dropped from all screeners: {report['dropped_from_all_screeners']}")
        print(f"  Present but missing 3d: {report['present_but_missing_3d']}")
        print(f"  Lifecycle detection working: {report['lifecycle_detection_working']}")

    conn.close()

    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
        md = [
            "# Screener Membership Status\n",
            f"Generated: {report['generated_at']}\n",
            "| Metric | Count |",
            "|--------|-------|",
            f"| Total memberships | {report['total_memberships']} |",
            f"| Present | {report['present']} |",
            f"| Dropped | {report['dropped']} |",
            f"| Stale | {report['stale']} |",
            f"| Expired | {report['expired']} |",
            f"| Reentered | {report['reentered']} |",
            f"| History events | {report['history_events']} |",
            f"| entered events | {report['entered_events']} |",
            f"| present events | {report['present_events']} |",
            f"| dropped events | {report['dropped_events']} |",
            f"| reentered events | {report['reentered_events']} |",
            f"| Multi-screener symbols | {report['multi_screener_symbols']} |",
            f"| Dropped from all screeners | {report['dropped_from_all_screeners']} |",
            f"| Present but missing 3d | {report['present_but_missing_3d']} |",
            f"| Lifecycle detection working | {report['lifecycle_detection_working']} |",
        ]
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
