#!/usr/bin/env python3
"""backfill_screener_catalog_from_recent_runs.py — Populate membership from scan data.

Default: dry-run. No trades. No orders.

Usage:
    .venv/bin/python scripts/backfill_screener_catalog_from_recent_runs.py --dry-run --verbose
    .venv/bin/python scripts/backfill_screener_catalog_from_recent_runs.py --apply --verbose
"""
import argparse, json, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))


def _get_conn():
    try:
        from db_adapter import _get_conn as gc
        return gc()
    except Exception:
        return None


def main():
    p = argparse.ArgumentParser(description="Backfill catalog/membership from scans (default: dry-run)")
    p.add_argument("--since-days", type=int, default=14)
    p.add_argument("--dry-run", action="store_true", default=True)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()
    if args.apply: args.dry_run = False

    conn = _get_conn()
    if not conn:
        print("ERROR: no DB connection")
        sys.exit(1)

    cur = conn.cursor()
    since = datetime.now(timezone.utc) - timedelta(days=args.since_days)

    # Get all distinct symbol/run_label pairs from recent scans
    cur.execute("""
        SELECT DISTINCT symbol, run_label, source, scanned_at::date as scan_date,
               MIN(scanned_at) as first_scan, MAX(scanned_at) as last_scan
        FROM trade_ai_scans
        WHERE scanned_at > %s
        GROUP BY symbol, run_label, source, scanned_at::date
        ORDER BY scan_date, run_label, symbol
    """, [since])
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]
    scans = [dict(zip(cols, r)) for r in rows]

    if args.verbose:
        print(f"Found {len(scans)} symbol/run pairs from last {args.since_days} days")

    # Group by symbol to find first/last seen
    by_symbol = {}
    for s in scans:
        sym = s["symbol"]
        by_symbol.setdefault(sym, []).append(s)

    catalog_inserts = 0
    catalog_updates = 0
    membership_inserts = 0
    history_events = 0

    for sym, entries in by_symbol.items():
        entries.sort(key=lambda x: x["first_scan"])
        first = entries[0]
        last = entries[-1]
        run_id = f"{last['scan_date']}_{last['run_label']}"
        source = last.get("source", "screener")

        if not args.dry_run:
            # Upsert screener_symbol_membership (use source as screener_id since no per-screener tracking in scans)
            cur.execute("""
                INSERT INTO screener_symbol_membership
                    (symbol, screener_id, first_seen_in_screener_at, last_seen_in_screener_at,
                     last_seen_run_id, present_this_run, consecutive_seen_count, membership_status)
                VALUES (%s, %s, %s, %s, %s, TRUE, %s, 'present')
                ON CONFLICT (symbol, screener_id) DO UPDATE SET
                    last_seen_in_screener_at = EXCLUDED.last_seen_in_screener_at,
                    last_seen_run_id = EXCLUDED.last_seen_run_id,
                    present_this_run = TRUE,
                    consecutive_seen_count = screener_symbol_membership.consecutive_seen_count + 1,
                    membership_status = 'present',
                    updated_at = NOW()
            """, [sym, source, first["first_scan"], last["last_scan"], run_id, len(entries)])
            membership_inserts += 1

            # Append entered event (only if first time)
            cur.execute("""
                INSERT INTO screener_symbol_membership_history
                    (symbol, screener_id, run_id, event_type, event_at, reason)
                SELECT %s, %s, %s, 'entered', %s, 'backfill from recent scans'
                WHERE NOT EXISTS (
                    SELECT 1 FROM screener_symbol_membership_history
                    WHERE symbol = %s AND screener_id = %s AND event_type = 'entered'
                )
            """, [sym, source, run_id, first["first_scan"], sym, source])
            history_events += 1
        else:
            membership_inserts += 1
            history_events += 1

    if not args.dry_run:
        conn.commit()

    conn.close()

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "dry_run" if args.dry_run else "apply",
        "since_days": args.since_days,
        "scan_pairs": len(scans),
        "unique_symbols": len(by_symbol),
        "membership_writes": membership_inserts,
        "history_events": history_events,
    }

    if args.verbose:
        print(f"{'DRY RUN' if args.dry_run else 'APPLIED'}: {len(by_symbol)} symbols, {membership_inserts} memberships, {history_events} events")

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        md = [f"# Catalog Backfill {'DRY RUN' if args.dry_run else 'APPLIED'}\n",
              f"Symbols: {len(by_symbol)} | Memberships: {membership_inserts} | Events: {history_events}"]
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
