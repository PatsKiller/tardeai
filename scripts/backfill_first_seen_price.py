#!/usr/bin/env python3
"""backfill_first_seen_price.py — stamp the price a symbol had when it joined the watchlist.

Powers the card's "+X% since added" trend segment. Going forward the intraday enrichment
sweep stamps `first_seen_price` on a row's first enrichment (COALESCE — never overwritten);
this script (a) ensures the column exists and (b) backfills EXISTING rows from yfinance
daily closes at their `first_seen_at` date. Scope defaults to the Hermes top-N the watch
page actually shows — backfilling all 11k historical rows would be yfinance abuse for
symbols nobody views. Rows whose history is unavailable stay NULL (the card omits the
segment rather than faking a baseline).

  python3 scripts/backfill_first_seen_price.py            # dry-run report
  python3 scripts/backfill_first_seen_price.py --apply
  python3 scripts/backfill_first_seen_price.py --apply --top 400
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _conn():
    from db_adapter import _get_conn
    return _get_conn()


def ensure_column() -> None:
    cur = _conn().cursor()
    cur.execute("ALTER TABLE watchlist_items ADD COLUMN IF NOT EXISTS first_seen_price numeric")
    cur.connection.commit()


def candidates(top: int) -> list[dict]:
    cur = _conn().cursor()
    cur.execute("""SELECT DISTINCT ON (symbol) symbol, first_seen_at::date AS fs
                   FROM watchlist_items
                   WHERE status IN ('active','researched') AND first_seen_at IS NOT NULL
                     AND first_seen_price IS NULL
                     AND hermes_rank IS NOT NULL AND hermes_rank <= %s
                     AND symbol ~ '^[A-Z]{1,5}$'
                   ORDER BY symbol, first_seen_at ASC""", (top,))
    return [{"symbol": r[0], "first_seen": r[1]} for r in cur.fetchall()]


def close_at(symbol: str, day) -> float | None:
    """First daily close on/after the first-seen date (5-session window)."""
    import yfinance as yf
    try:
        hist = yf.Ticker(symbol).history(start=day - timedelta(days=1), end=day + timedelta(days=8), interval="1d")
    except Exception:
        return None
    if hist is None or len(hist) == 0:
        return None
    for idx, row in hist.iterrows():
        d = idx.date() if hasattr(idx, "date") else None
        px = float(row.get("Close") or 0)
        if d and d >= day and px > 0:
            return round(px, 4)
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write stamps (default: dry-run report)")
    ap.add_argument("--top", type=int, default=250, help="Hermes-rank scope (default 250)")
    a = ap.parse_args()

    ensure_column()
    rows = candidates(a.top)
    print(f"{len(rows)} symbols in Hermes top-{a.top} missing first_seen_price")
    if not rows:
        return 0

    conn = _conn()
    cur = conn.cursor()
    stamped, missed = [], []
    for r in rows:
        px = close_at(r["symbol"], r["first_seen"])
        if px is None:
            missed.append(r["symbol"])
            continue
        if a.apply:
            cur.execute("""UPDATE watchlist_items SET first_seen_price=%s
                           WHERE symbol=%s AND first_seen_price IS NULL""", (px, r["symbol"]))
        stamped.append(f"{r['symbol']}@{px}")
        time.sleep(0.35)
    if a.apply:
        conn.commit()
    print(json.dumps({
        "applied": a.apply,
        "stamped": len(stamped),
        "no_history": missed[:20] + (["…"] if len(missed) > 20 else []),
        "sample": stamped[:10],
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
