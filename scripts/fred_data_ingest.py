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
    python3 scripts/fred_data_ingest.py --ingest --dry-run   # Report the plan; fetch nothing, write nothing

Lane ``fred-data-ingest`` (cron L248, ``--ingest``). ``--dry-run`` wins over every mode: it never enters
PipelineRun (no pipeline_runs row), never calls the FRED API and never reaches ingest_fred(); it opens a
READ ONLY session, reads the latest stored observation per series and prints the series a real run
would fetch and upsert. It reports only whether FRED_API_KEY is configured, never its value. No receipt.

A real ``--ingest`` run writes ``<state_root>/data/runtime/fred-data-ingest_last.json``
(LaneRunReceipt@v1; ``ok_at`` only on success). Exit codes: 0 = ran (some series fetched; a series with
no new value is not a failure); 1 = the run failed: crash / DB unavailable (failed receipt, exception
re-raised), no FRED_API_KEY, or 0 of the series fetched (nothing could be fetched when work existed);
2 = usage error (no mode given).
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from external_market_data_ingest import (
    ingest_fred, get_macro_context, _get_conn, _env, FRED_SERIES
)

# Pipeline telemetry
try:
    from pipeline_registry import PipelineRun
except ImportError:
    class PipelineRun:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def rows(self, n): pass


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
            last_exc = str(e)[:160]

    conn.commit()
    conn.close()
    # Liveness (2026-09-13): same provider as ingest_fred(), same key. --history is
    # operator-invoked (not scheduled); it reports when it runs.
    try:
        from lib.data_source_report import report_source
        report_source("fred", total > 0, rows=total,
                      error=None if total else (locals().get("last_exc") or "0 observations fetched"))
    except Exception:
        pass
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
            print("    NO DATA")


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


LANE_ID = "fred-data-ingest"


def _receipt_lib():
    try:
        from lib import lane_last_receipt as lr
    except ImportError:  # imported as scripts.fred_data_ingest
        from scripts.lib import lane_last_receipt as lr
    return lr


def dry_run(argv) -> int:
    """Dry run (AGENTS.md §6): READ ONLY latest-observation SELECT; no FRED call, no INSERT, no receipt."""
    mode = "history" if "--history" in argv else "ingest"
    key_configured = bool(_env("FRED_API_KEY"))
    latest = {}
    conn = _get_conn()
    try:
        _receipt_lib().enforce_readonly(conn)
        cur = conn.cursor()
        cur.execute("""
            SELECT DISTINCT ON (series_id) series_id, observation_date
            FROM fred_economic_series
            ORDER BY series_id, observation_date DESC
        """)
        latest = {r[0]: str(r[1]) for r in cur.fetchall()}
    finally:
        conn.close()
    for sid, name in FRED_SERIES.items():
        print(f"  [fred] would fetch {sid} ({name}); latest stored: {latest.get(sid, 'none')}")
    per = "1 latest observation" if mode == "ingest" else "up to 100 observations"
    _receipt_lib().dry_run_report(
        LANE_ID if mode == "ingest" else "fred-data-ingest-history",
        {"mode": mode, "series": len(FRED_SERIES), "fred_api_key_configured": key_configured,
         "series_with_stored_data": len(latest), "latest_stored": latest},
        would_write=[f"fred_economic_series upsert ({per} x {len(FRED_SERIES)} series)",
                     "data_source health row 'fred' (report_source)", "pipeline_runs row (PipelineRun)"],
    )
    return 0


def run_ingest() -> int:
    """The lane: ingest_fred() + LaneRunReceipt@v1 + honest exit code."""
    lr = _receipt_lib()
    started = lr.now_iso()
    try:
        result = ingest_fred()
    except Exception as exc:
        lr.write_lane_receipt(LANE_ID, ok=False, exit_code=1, started_at=started,
                              script="fred_data_ingest.py", error=f"{type(exc).__name__}: {exc}")
        raise
    print(f"FRED ingest: {result}")
    fetched = int(result.get("fetched") or 0)
    failed = fetched == 0  # no key, or every series failed -> nothing could be fetched
    rc = 1 if failed else 0
    lr.write_lane_receipt(LANE_ID, ok=not failed, exit_code=rc, started_at=started, script="fred_data_ingest.py",
                          summary={"fetched": fetched, "series": len(FRED_SERIES),
                                   "reason": result.get("reason")})
    return rc


def main(argv) -> int:
    if "--test" in argv:
        test()
    elif "--ingest" in argv:
        return run_ingest()
    elif "--context" in argv:
        print(get_macro_context() or "(no FRED data)")
    elif "--history" in argv:
        days = 90
        for i, a in enumerate(argv):
            if a == "--days" and i + 1 < len(argv):
                days = int(argv[i + 1])
        result = ingest_history(days)
        print(f"FRED history: {result}")
        show_status()
    elif "--status" in argv:
        show_status()
    else:
        print("Usage: --test | --ingest | --context | --history [--days 90] | --status  [--dry-run]")
        return 2
    return 0


if __name__ == "__main__":
    if "--dry-run" in sys.argv:
        # Before PipelineRun: a dry run records no pipeline_runs row and cannot reach ingest_fred().
        sys.exit(dry_run(sys.argv[1:]))
    with PipelineRun("fred_data_ingest") as _run:
        sys.exit(main(sys.argv[1:]))
