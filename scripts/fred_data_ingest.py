#!/usr/bin/env python3
"""fred_data_ingest.py — FRED macro economic data ingestion wrapper.

Fetches inflation, rates, yield curve, unemployment, VIX from FRED API.
Data stored in fred_economic_series table.

Requires: FRED_API_KEY in .env (free from https://fred.stlouisfed.org/docs/api/api_key.html)

Usage:
    python3 scripts/fred_data_ingest.py --test     # Fetch + verify all 7 series
    python3 scripts/fred_data_ingest.py --ingest    # Daily/weekly snapshot
    python3 scripts/fred_data_ingest.py --context   # Show macro context string for agents
    python3 scripts/fred_data_ingest.py --history   # Fetch 90-day history for each series
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from external_market_data_ingest import (
    ingest_fred, get_macro_context, _get_conn, _env, FRED_SERIES
)


def ingest_history(days: int = 90) -> dict:
    """Fetch historical observations for all FRED series (backfill)."""
    import urllib.request
    import json
    from datetime import datetime, timedelta

    api_key = _env("FRED_API_KEY")
    if not api_key:
        print("[fred-history] No FRED_API_KEY — skipping")
        return {"source": "fred_history", "fetched": 0, "reason": "no_key"}

    start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    conn = _get_conn()
    cur = conn.cursor()
    total = 0

    for series_id, name in FRED_SERIES.items():
        try:
            url = (f"https://api.stlouisfed.org/fred/series/observations"
                   f"?series_id={series_id}&api_key={api_key}&file_type=json"
                   f"&observation_start={start}&sort_order=desc&limit=100")
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())

            count = 0
            for obs in data.get("observations", []):
                val = obs.get("value", ".")
                obs_date = obs.get("date", "")
                if val != "." and obs_date:
                    cur.execute("""
                        INSERT INTO fred_economic_series (series_id, series_name, value, observation_date)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (series_id, observation_date) DO UPDATE SET value=EXCLUDED.value, fetched_at=NOW()
                    """, (series_id, name, float(val), obs_date))
                    count += 1
            total += count
            print(f"  {series_id} ({name}): {count} observations")
        except Exception as e:
            print(f"  {series_id}: ERROR — {e}")

    conn.commit()
    conn.close()
    return {"source": "fred_history", "fetched": total}


def show_status():
    """Show current FRED data status."""
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("""
        SELECT series_id, series_name, value, observation_date, fetched_at
        FROM fred_economic_series
        ORDER BY series_id, observation_date DESC
    """)
    rows = cur.fetchall()
    cur.execute("SELECT count(DISTINCT series_id) as series, count(*) as total FROM fred_economic_series")
    stats = cur.fetchone()
    conn.close()

    print(f"\n{'='*60}")
    print(f"FRED Economic Data — {stats['series']} series, {stats['total']} total observations")
    print(f"{'='*60}")

    # Group by series
    from collections import defaultdict
    by_series = defaultdict(list)
    for r in rows:
        by_series[r['series_id']].append(r)

    for sid in sorted(FRED_SERIES.keys()):
        obs_list = by_series.get(sid, [])
        if obs_list:
            latest = obs_list[0]
            print(f"\n  {sid} — {latest['series_name']}")
            print(f"    Latest: {float(latest['value']):.2f} ({latest['observation_date']})")
            print(f"    Observations: {len(obs_list)} | Fetched: {str(latest['fetched_at'])[:19]}")
        else:
            print(f"\n  {sid} — {FRED_SERIES[sid]}")
            print(f"    NO DATA")


def test():
    """Full test: ingest latest + show context."""
    print("=== FRED Data Ingest Test ===\n")

    api_key = _env("FRED_API_KEY")
    if not api_key:
        print("ERROR: No FRED_API_KEY in .env")
        print("Get a free key at: https://fred.stlouisfed.org/docs/api/api_key.html")
        print("Then add: FRED_API_KEY=your_key_here to .env")
        return

    print(f"API Key: {api_key[:4]}...{api_key[-4:]}")
    print(f"Series to fetch: {len(FRED_SERIES)}")
    for sid, name in FRED_SERIES.items():
        print(f"  {sid}: {name}")

    print("\n--- Fetching latest observations ---")
    result = ingest_fred()
    print(f"Result: {result}")

    print("\n--- Macro context for agents ---")
    ctx = get_macro_context()
    print(ctx or "(no data)")

    show_status()
    print("\n=== Test Complete ===")


if __name__ == "__main__":
    if "--test" in sys.argv:
        test()
    elif "--ingest" in sys.argv:
        result = ingest_fred()
        print(f"FRED ingest: {result}")
    elif "--context" in sys.argv:
        print(get_macro_context() or "(no FRED data)")
    elif "--history" in sys.argv:
        days = 90
        for i, a in enumerate(sys.argv):
            if a == "--days" and i + 1 < len(sys.argv):
                days = int(sys.argv[i + 1])
        result = ingest_history(days)
        print(f"FRED history: {result}")
        show_status()
    elif "--status" in sys.argv:
        show_status()
    else:
        print("Usage: --test | --ingest | --context | --history [--days 90] | --status")
