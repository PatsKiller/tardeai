"""
earnings_date_enrichment.py — Fetch upcoming earnings dates via yfinance
Version: 1.0 | April 17, 2026

Fetches earnings dates for all portfolio tickers (individual stocks only,
ETFs/mutual funds skipped). Stores in data/portfolios/state/earnings_dates.json.

Designed to run weekly (earnings announcements don't change daily).
Called by daily pipeline or standalone.
"""
from __future__ import annotations
import json, sys, time
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

PROJECT_ROOT = Path(__file__).parent.parent
STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"

CASH_SYMS = {"CASH", "--", "SNSXX", "SWVXX", "SPRXX", "VMFXX", "FDRXX"}

# Tickers with hyphens are Fidelity 401k proprietary fund names — skip
# ETFs without earnings are expected to return None — that's fine
SKIP_PATTERNS = {"-"}  # symbols containing hyphen are proprietary fund names


def _load_portfolio_tickers() -> list:
    """Get all unique non-cash tickers from holdings."""
    h_path = STATE_DIR / "holdings.json"
    if not h_path.exists():
        return []
    h = json.loads(h_path.read_text())
    seen = set()
    tickers = []
    for pos in h.get("holdings", []):
        sym = pos.get("symbol", "")
        if not sym or sym in CASH_SYMS or sym in seen:
            continue
        if any(p in sym for p in SKIP_PATTERNS):
            continue
        mv = pos.get("market_value", 0) or 0
        if mv <= 0:
            continue
        seen.add(sym)
        tickers.append(sym)
    return tickers


def fetch_earnings_dates(tickers: list) -> Dict[str, Dict]:
    """Fetch upcoming earnings dates from Yahoo Finance via yfinance."""
    try:
        import yfinance as yf
    except ImportError:
        print("  [earnings] yfinance not installed — skipping")
        return {}

    results = {}
    fetched = 0
    errors = 0

    for sym in tickers:
        try:
            t = yf.Ticker(sym)
            cal = t.calendar
            earnings_date = None

            if isinstance(cal, dict):
                ed = cal.get("Earnings Date")
                if isinstance(ed, list) and ed:
                    # yfinance returns a list of Timestamp objects
                    raw = ed[0]
                    if hasattr(raw, "strftime"):
                        earnings_date = raw.strftime("%Y-%m-%d")
                    else:
                        earnings_date = str(raw)[:10]

            results[sym] = {
                "earnings_date": earnings_date,
                "fetched_at": datetime.now().isoformat(),
            }
            if earnings_date:
                fetched += 1
        except Exception as e:
            results[sym] = {
                "earnings_date": None,
                "fetched_at": datetime.now().isoformat(),
                "error": str(e)[:80],
            }
            errors += 1

    print(f"  [earnings] Fetched {fetched}/{len(tickers)} dates ({errors} errors)")
    return results


def refresh_earnings_dates(project_root: str = ".") -> Path:
    """Full refresh: load tickers, fetch dates, save JSON."""
    global STATE_DIR
    STATE_DIR = Path(project_root) / "data" / "portfolios" / "state"

    tickers = _load_portfolio_tickers()
    if not tickers:
        print("  [earnings] No portfolio tickers found")
        return STATE_DIR / "earnings_dates.json"

    print(f"  [earnings] Fetching earnings dates for {len(tickers)} tickers via yfinance...")
    results = fetch_earnings_dates(tickers)

    out_path = STATE_DIR / "earnings_dates.json"

    # Merge with existing data (preserve old dates for tickers not refreshed)
    existing = {}
    if out_path.exists():
        try:
            existing = json.loads(out_path.read_text())
        except Exception:
            pass

    existing.update(results)
    existing["_meta"] = {
        "last_refresh": datetime.now().isoformat(),
        "tickers_fetched": len(tickers),
        "dates_found": sum(1 for v in results.values() if v.get("earnings_date")),
    }

    out_path.write_text(json.dumps(existing, indent=2, default=str))
    print(f"  [earnings] Saved to {out_path}")
    return out_path


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Fetch earnings dates via yfinance")
    parser.add_argument("--project-root", default=".")
    args = parser.parse_args()
    refresh_earnings_dates(args.project_root)
