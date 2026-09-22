#!/usr/bin/env python3
"""Downsample market_quotes: keep every daily close forever, drop intraday noise.

WHY NOT JUST SHORTEN RETENTION
------------------------------
Operator asked whether market_quotes could drop to a few hours, since fresh
quotes are always available on demand. I first said 7 days. That was WRONG, and
the correction matters:

  scripts/lib/data_broker/rotation_ladders.py:116
      for idx, lookback_days in enumerate([21, 63, 126]):
          cutoff = now - timedelta(days=lookback_days + 7)

Sector relative-strength reads DAILY CLOSES out of this table at 1m/3m/6m. A
7-day cut would silently break all three windows.

Worse, the CURRENT 90-day policy (db_retention.py:118) already truncates the
6-month window: 126 + 7 = 133 calendar days needed, 90 retained. That defect
predates this script.

WHAT ACTUALLY COSTS THE SPACE
-----------------------------
Measured 2026-09-21:

    rows                       34,219,869      5,805 MB
    distinct (symbol, day)        291,466
    intraday rows per close          117.4x
    rows < 7 days                 505,113

Both consumers read one row per symbol per day:

    sector_rs_daily.py:46   DISTINCT ON (upper(symbol), fetched_at::date)
                            ORDER BY ..., fetched_at DESC       -> the day's LAST quote
    rotation_ladders.py:121 DISTINCT ON (symbol) ... ORDER BY fetched_at ASC
                            -> the earliest DAILY CLOSE in the window

Keeping the LAST row per (symbol, day) satisfies both. Everything else is
resolution nobody queries.

    keep: 505,113 recent + 291,466 daily closes = 796,579  (2.3% of rows)
    drop: 33,423,290

That reclaims ~5.6 GB AND makes a 180-day daily spine affordable -- so it FIXES
the 6-month lookback rather than breaking it further.

SAFETY
------
This DELETES. AGENTS §0 rule 6 and §17 apply, so:
  * dry-run is the default and prints the exact plan
  * --apply is the operator's call, never taken automatically
  * deletes run in bounded batches so a 34M-row table is never locked in one
    transaction
  * the daily close for every symbol-day is preserved by construction -- the
    information content survives; only duplicate intraday samples go

    python scripts/market_quotes_downsample.py                  # dry run
    python scripts/market_quotes_downsample.py --keep-days 14   # wider window
    python scripts/market_quotes_downsample.py --apply          # operator only
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

#: Rows newer than this keep FULL intraday resolution. 7 days comfortably covers
#: any same-week debugging; the readers never look at intraday beyond today.
DEFAULT_KEEP_DAYS = 7

#: Bounded so a single statement never locks the whole table.
DEFAULT_BATCH = 50_000

#: The lane's proof-of-run.
RECEIPT = ROOT / "logs" / "market_quotes_downsample_receipts.jsonl"


def _plan(cur, keep_days: int) -> dict:
    """Count what would go and what would stay. Read-only."""
    cur.execute(
        """
        SELECT count(*) FILTER (WHERE fetched_at >= now() - make_interval(days => %s)) AS recent,
               count(*) FILTER (WHERE fetched_at <  now() - make_interval(days => %s)) AS older,
               count(*) AS total
        FROM market_quotes
        """,
        (keep_days, keep_days),
    )
    recent, older, total = cur.fetchone()

    cur.execute(
        """
        SELECT count(*) FROM (
            SELECT DISTINCT ON (upper(symbol), fetched_at::date) id
            FROM market_quotes
            WHERE fetched_at < now() - make_interval(days => %s)
            ORDER BY upper(symbol), fetched_at::date, fetched_at DESC
        ) k
        """,
        (keep_days,),
    )
    (closes,) = cur.fetchone()

    cur.execute("SELECT pg_total_relation_size('market_quotes')")
    (size_bytes,) = cur.fetchone()

    keep = recent + closes
    drop = older - closes
    return {
        "total_rows": total,
        "recent_rows_kept_full_resolution": recent,
        "older_rows": older,
        "daily_closes_kept": closes,
        "rows_kept": keep,
        "rows_dropped": drop,
        "pct_kept": round(100.0 * keep / total, 2) if total else 0.0,
        "table_size": f"{size_bytes / 1024**3:.2f} GB",
        "est_reclaim": f"{size_bytes * drop / total / 1024**3:.2f} GB" if total else "0",
    }


def _delete_batches(conn, cur, keep_days: int, batch: int, max_batches: int) -> int:
    """Delete non-close rows older than the window, in bounded batches."""
    cur.execute("DROP TABLE IF EXISTS mq_keep_ids")
    cur.execute(
        """
        CREATE TEMP TABLE mq_keep_ids AS
        SELECT DISTINCT ON (upper(symbol), fetched_at::date) id
        FROM market_quotes
        WHERE fetched_at < now() - make_interval(days => %s)
        ORDER BY upper(symbol), fetched_at::date, fetched_at DESC
        """,
        (keep_days,),
    )
    cur.execute("CREATE INDEX ON mq_keep_ids (id)")
    cur.execute("ANALYZE mq_keep_ids")
    conn.commit()

    removed = 0
    for n in range(max_batches):
        cur.execute(
            """
            DELETE FROM market_quotes
            WHERE id IN (
                SELECT q.id FROM market_quotes q
                LEFT JOIN mq_keep_ids k ON k.id = q.id
                WHERE q.fetched_at < now() - make_interval(days => %s)
                  AND k.id IS NULL
                LIMIT %s
            )
            """,
            (keep_days, batch),
        )
        got = cur.rowcount or 0
        conn.commit()
        removed += got
        print(f"  batch {n + 1}: removed {got:,} (running total {removed:,})", flush=True)
        if got == 0:
            break
    return removed


def _receipt(payload: dict) -> str:
    try:
        RECEIPT.parent.mkdir(parents=True, exist_ok=True)
        with RECEIPT.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, separators=(",", ":"), default=str) + "\n")
        return "written"
    except Exception as exc:  # noqa: BLE001
        return f"error:{type(exc).__name__}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--keep-days", type=int, default=DEFAULT_KEEP_DAYS,
                    help=f"days of FULL intraday resolution (default {DEFAULT_KEEP_DAYS})")
    ap.add_argument("--batch", type=int, default=DEFAULT_BATCH)
    ap.add_argument("--max-batches", type=int, default=2000)
    ap.add_argument("--apply", action="store_true",
                    help="execute (operator-only, AGENTS §17); without it this only reports")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    from db_adapter import _get_conn  # noqa: PLC0415

    out: dict = {
        "schema": "MarketQuotesDownsample@v1",
        "ts": datetime.now(timezone.utc).isoformat(),
        "keep_days": a.keep_days,
        "apply": bool(a.apply),
    }

    with _get_conn() as conn, conn.cursor() as cur:
        out["plan"] = _plan(cur, a.keep_days)

        if not a.apply:
            p = out["plan"]
            print(f"market_quotes downsample — {out['ts'][:19]}")
            print("-" * 62)
            print(f"  total rows                 : {p['total_rows']:,}")
            print(f"  kept, full resolution (<{a.keep_days}d): {p['recent_rows_kept_full_resolution']:,}")
            print(f"  kept, one close per day    : {p['daily_closes_kept']:,}")
            print(f"  ROWS KEPT                  : {p['rows_kept']:,}  ({p['pct_kept']}%)")
            print(f"  rows dropped               : {p['rows_dropped']:,}")
            print(f"  table size                 : {p['table_size']}")
            print(f"  estimated reclaim          : {p['est_reclaim']}")
            print()
            print("  Every symbol-day keeps its CLOSING quote. Both consumers")
            print("  (sector_rs_daily, rotation_ladders) read exactly that.")
            print()
            print("DRY RUN — nothing deleted. --apply is operator-only (§17).")
            if a.json:
                print(json.dumps(out, indent=2))
            out["receipt"] = _receipt(out)
            return 0

        removed = _delete_batches(conn, cur, a.keep_days, a.batch, a.max_batches)
        out["removed"] = removed
        cur.execute("SELECT pg_total_relation_size('market_quotes')")
        (after,) = cur.fetchone()
        out["size_after"] = f"{after / 1024**3:.2f} GB"
        print(f"\n  removed : {removed:,}")
        print(f"  size now: {out['size_after']}")
        print("  NOTE: run VACUUM (FULL) ANALYZE market_quotes to return the space to the OS.")

    out["receipt"] = _receipt(out)
    if a.json:
        print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
