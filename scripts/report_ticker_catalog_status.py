#!/usr/bin/env python3
"""report_ticker_catalog_status.py — Ticker catalog status using incubator_universe.

Read-only.

Usage:
    .venv/bin/python scripts/report_ticker_catalog_status.py --verbose
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
    p = argparse.ArgumentParser(description="Ticker catalog status (read-only)")
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    total = _db_query("SELECT count(*) as c FROM incubator_universe", fetch="one") or {}
    active = _db_query("SELECT count(*) as c FROM incubator_universe WHERE status='ACTIVE'", fetch="one") or {}
    classifications = _db_query("SELECT count(*) as c FROM ticker_strategy_classifications WHERE active=TRUE", fetch="one") or {}
    watchlist = _db_query("SELECT count(*) as c FROM watchlist_items", fetch="one") or {}
    new_24h = _db_query("SELECT count(*) as c FROM incubator_universe WHERE first_seen_at > NOW() - INTERVAL '24 hours'", fetch="one") or {}
    new_7d = _db_query("SELECT count(*) as c FROM incubator_universe WHERE first_seen_at > NOW() - INTERVAL '7 days'", fetch="one") or {}

    by_strategy = _db_query("SELECT strategy_id, count(*) as c FROM incubator_universe WHERE status='ACTIVE' GROUP BY strategy_id ORDER BY c DESC LIMIT 15") or []

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_incubator": int(total.get("c", 0)),
        "active_incubator": int(active.get("c", 0)),
        "active_classifications": int(classifications.get("c", 0)),
        "watchlist_items": int(watchlist.get("c", 0)),
        "new_24h": int(new_24h.get("c", 0)),
        "new_7d": int(new_7d.get("c", 0)),
        "by_strategy": [{k: v for k, v in r.items()} for r in by_strategy],
        "catalog_source": "incubator_universe + ticker_strategy_classifications + watchlist_items",
    }

    if args.verbose:
        print(f"Ticker Catalog — {report['total_incubator']} incubator, {report['active_incubator']} active, {report['active_classifications']} classified")
        print(f"  Watchlist: {report['watchlist_items']}, New 24h: {report['new_24h']}, New 7d: {report['new_7d']}")
        for s in by_strategy[:10]:
            print(f"  {s['strategy_id']}: {s['c']}")

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        md = [f"# Ticker Catalog Status\n",
              f"Incubator: {report['total_incubator']} total, {report['active_incubator']} active\n",
              f"Classifications: {report['active_classifications']} | Watchlist: {report['watchlist_items']}\n",
              f"New 24h: {report['new_24h']} | New 7d: {report['new_7d']}"]
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
