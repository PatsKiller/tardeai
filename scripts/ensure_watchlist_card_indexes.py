#!/usr/bin/env python3
"""ensure_watchlist_card_indexes.py — idempotent indexes that keep the watchlist-items card query
(_wl_items: symbol_profiles + catalyst_events joins) fast. Without these the catalyst LATERAL ran a
per-symbol sort over all ~3,300 watchlist rows → _wl_items took ~10s; with them it is ~0.5s.

Safe to re-run (CREATE INDEX IF NOT EXISTS). Run once after deploy / on a fresh DB.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db_adapter import _get_conn

INDEXES = [
    # symbol_profiles join uses upper(symbol) = upper(wi.symbol)
    "CREATE INDEX IF NOT EXISTS idx_symprofiles_upper ON symbol_profiles (upper(symbol))",
    # catalyst join filters upper(symbol); plain functional index for the equality lookup
    "CREATE INDEX IF NOT EXISTS idx_catalyst_upper_symbol ON catalyst_events (upper(symbol))",
    # the hot path: latest NON-'other' catalyst per symbol — partial composite so it's a single seek
    "CREATE INDEX IF NOT EXISTS idx_catalyst_real_latest ON catalyst_events "
    "(upper(symbol), (COALESCE(published_at, created_at)) DESC) WHERE catalyst_type <> 'other'",
]


def main():
    conn = _get_conn()
    cur = conn.cursor()
    for ddl in INDEXES:
        cur.execute(ddl)
        print("ok:", ddl.split(" ON ")[0].replace("CREATE INDEX IF NOT EXISTS ", ""))
    conn.commit()
    cur.execute("ANALYZE symbol_profiles")
    cur.execute("ANALYZE catalyst_events")
    conn.commit()
    print("done — analyzed")


if __name__ == "__main__":
    main()
