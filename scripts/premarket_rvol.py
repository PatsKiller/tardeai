"""premarket_rvol.py — TOS-style RVOL tiers and pre-market price enrichment.

RVOL Calculation (done in finviz_ingestion.py):
  RVOL = volume / avg_volume   (Method 1 — TOS-style, Loveable Method 1)
  Both volume and avg_volume come from Finviz CSV.
  This gives accurate RVOL even pre-market since Finviz exports both fields.

This module adds:
  1. TOS-style tier badges to all scored tickers
  2. Pre-market price updates from Yahoo Finance (4AM-9:30AM only)
  3. Standalone test to verify the tier display

TOS Tiers:
  > 5.0x  🚀 Explosive       (purple #9C27B0)
  > 3.0x  🔥 Extremely High  (red    #DB4437)
  > 2.0x  ⚡ High            (orange #FF9800)
  > 1.5x  📈 Above Average   (green  #0F9D58)
  0.8-1.5x ➡️ Normal         (gray   #9A9AB0)
  < 0.8x  📉 Below Average   (blue   #1A73E8)
"""
from __future__ import annotations

import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
import requests


def _et_now() -> datetime:
    utc_now = datetime.now(timezone.utc)
    try:
        import zoneinfo
        return datetime.now(zoneinfo.ZoneInfo("America/New_York"))
    except Exception:
        month = utc_now.month
        offset = -4 if 3 < month < 11 else -5
        return utc_now + timedelta(hours=offset)


def _session() -> str:
    et = _et_now()
    m = et.hour * 60 + et.minute
    if et.weekday() >= 5: return "closed"
    if 4*60 <= m < 9*60+30: return "pre_market"
    if 9*60+30 <= m < 16*60: return "market_hours"
    if 16*60 <= m < 20*60: return "after_hours"
    return "closed"


def rvol_tier(rvol: float) -> Dict[str, str]:
    """Return TOS-style tier dict for an RVOL value."""
    if rvol >= 5.0: return {"tier":"explosive",      "label":"🚀 Explosive",      "color":"#9C27B0"}
    if rvol >= 3.0: return {"tier":"extremely_high", "label":"🔥 Extremely High", "color":"#DB4437"}
    if rvol >= 2.0: return {"tier":"high",           "label":"⚡ High",           "color":"#FF9800"}
    if rvol >= 1.5: return {"tier":"above_average",  "label":"📈 Above Average",  "color":"#0F9D58"}
    if rvol >= 0.8: return {"tier":"normal",         "label":"➡️ Normal",          "color":"#9A9AB0"}
    return             {"tier":"below_average",  "label":"📉 Below Average", "color":"#1A73E8"}


def _fetch_premarket_price(sym: str) -> Optional[Dict]:
    """Fetch pre-market price/change from Yahoo Finance."""
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
        resp = requests.get(url,
            headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
            params={"interval": "1d", "range": "1d"},
            timeout=6)
        if resp.status_code != 200:
            resp = requests.get(url.replace("query1.", "query2."),
                headers={"User-Agent": "Mozilla/5.0"},
                params={"interval": "1d", "range": "1d"}, timeout=5)
            if resp.status_code != 200:
                return None
        meta = resp.json()["chart"]["result"][0]["meta"]
        pre_price = meta.get("preMarketPrice") or 0
        pre_chg   = meta.get("preMarketChangePercent") or 0
        reg_price = meta.get("regularMarketPrice") or 0
        pre_vol   = meta.get("preMarketVolume") or 0
        reg_vol   = meta.get("regularMarketVolume") or 0
        return {
            "pre_price": pre_price,
            "pre_change_pct": pre_chg,
            "reg_price": reg_price,
            "pre_market_volume": pre_vol,
            "regular_volume": reg_vol,
        }
    except Exception:
        return None


def enrich_rvol(
    tickers: List[Dict[str, Any]],
    force: bool = False,
    delay: float = 0.15,
    max_tickers: int = 30,
) -> None:
    """
    Add TOS-style tier badges to all tickers.
    During pre-market, also update price from Yahoo if available.

    RVOL itself is computed in finviz_ingestion.py as volume/avg_volume.
    This function only adds the visual tier metadata and optionally
    refreshes pre-market price.
    """
    session = _session()

    for i, t in enumerate(tickers[:max_tickers]):
        rvol = float(t.get("relative_volume") or 0)

        # Always add tier badges
        tier = rvol_tier(rvol)
        t["rvol_tier"]  = tier
        t["rvol_emoji"] = tier["label"].split()[0]
        t.setdefault("rvol_source", "finviz")

        # During pre-market: try to get real-time price from Yahoo
        if session == "pre_market":
            data = _fetch_premarket_price(t.get("symbol", ""))
            if data and data.get("pre_price"):
                t["price"]           = data["pre_price"]
                t["change_percent"]  = round(data.get("pre_change_pct", 0), 2)
                t["gap_percent"]     = round(data.get("pre_change_pct", 0), 2)
                t["rvol_source"]     = "yahoo_pre_market"
                # If Yahoo has pre-market volume and we have avg_volume, recompute RVOL
                pre_vol = data.get("pre_market_volume") or 0
                avg_vol = t.get("avg_volume") or 0
                if pre_vol > 0 and avg_vol > 0:
                    rvol = round(pre_vol / avg_vol, 2)
                    t["relative_volume"] = rvol
                    t["rvol_tier"]       = rvol_tier(rvol)
                    t["rvol_emoji"]      = t["rvol_tier"]["label"].split()[0]

            if delay > 0 and i < min(len(tickers), max_tickers) - 1:
                time.sleep(delay)


if __name__ == "__main__":
    import sys
    test_syms = [s for s in sys.argv[1:] if not s.startswith("--")]
    if not test_syms:
        test_syms = ["CYCN", "ELAB", "RENX", "AAPL", "SPY"]

    print(f"\n=== RVOL Tier Test — {_session()} session ===\n")
    print(f"  RVOL is computed as: volume / avg_volume (both from Finviz)")
    print(f"  Simulating tickers with known volume data from yesterday:\n")

    # Simulate real Finviz data for yesterday's runners
    test_tickers = [
        {"symbol": "CYCN",  "volume": 252321938, "avg_volume": 1510270,  "relative_volume": 0},
        {"symbol": "ELAB",  "volume": 37039786,  "avg_volume": 892300,   "relative_volume": 0},
        {"symbol": "RENX",  "volume": 85540042,  "avg_volume": 1630000,  "relative_volume": 0},
        {"symbol": "AAPL",  "volume": 45000000,  "avg_volume": 55000000, "relative_volume": 0},
        {"symbol": "SPY",   "volume": 95000000,  "avg_volume": 85000000, "relative_volume": 0},
    ]

    # Simulate what finviz_ingestion does: volume/avg_volume
    for t in test_tickers:
        if t["avg_volume"] > 0:
            t["relative_volume"] = round(t["volume"] / t["avg_volume"], 2)

    enrich_rvol(test_tickers, force=False, delay=0)

    print(f"  {'Symbol':<7} {'RVOL':>8}  {'Tier':<25} {'Color'}")
    print(f"  {'-'*7} {'-'*8}  {'-'*25} {'-'*12}")
    for t in test_tickers:
        tier = t.get("rvol_tier", {})
        print(f"  {t['symbol']:<7} {t['relative_volume']:>7.1f}x  "
              f"{tier.get('label','—'):<25} {tier.get('color','')}")
    print()
