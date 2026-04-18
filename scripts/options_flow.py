"""options_flow.py — Unusual options flow for Trade AI v11.

Fetches high-volume / high-premium options activity for GO-tier tickers
via Polygon options snapshot API.

Display only — does NOT affect scoring.

Output per ticker:
  - contract type (CALL / PUT)
  - strike, expiry
  - volume vs open interest ratio (signals unusual activity)
  - premium value estimate
  - sweep flag (filled across multiple exchanges)
  - direction label: bullish / bearish / neutral
"""
from __future__ import annotations
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
import requests


def _env(k: str) -> str:
    return os.getenv(k, "").strip()


# ── Polygon options fetch ─────────────────────────────────────────────────────

def _fetch_polygon_options(symbol: str) -> List[Dict]:
    key = _env("POLYGON_API_KEY")
    if not key:
        return []
    try:
        url = f"https://api.polygon.io/v3/snapshot/options/{symbol}"
        resp = requests.get(url, params={
            "order": "desc",
            "limit": 25,
            "sort": "day.volume",
            "apiKey": key,
        }, timeout=(5, 8))
        resp.raise_for_status()
        return resp.json().get("results", [])
    except Exception:
        return []


def _classify_direction(contract_type: str, delta: float) -> str:
    """Classify option trade direction as bullish / bearish / neutral."""
    if contract_type == "call":
        return "bullish" if delta > 0.3 else "neutral"
    if contract_type == "put":
        return "bearish" if delta < -0.3 else "neutral"
    return "neutral"


def _is_unusual(vol: int, oi: int, premium: float) -> bool:
    """Flag as unusual if volume/OI ratio >= 2 or premium >= $50K."""
    if oi > 0 and vol / oi >= 2:
        return True
    if premium >= 50_000:
        return True
    return False


def _parse_option(item: Dict) -> Optional[Dict]:
    """Parse a Polygon options snapshot result into a clean dict."""
    try:
        details  = item.get("details", {})
        day      = item.get("day", {})
        greeks   = item.get("greeks", {})

        contract_type = details.get("contract_type", "").lower()   # call / put
        strike        = details.get("strike_price", 0)
        expiry        = details.get("expiration_date", "")
        ticker        = details.get("ticker", "")

        vol  = int(day.get("volume", 0) or 0)
        oi   = int(item.get("open_interest", 0) or 0)
        vwap = float(day.get("vwap", 0) or 0)
        premium = vol * vwap * 100  # rough premium estimate

        delta = float(greeks.get("delta", 0) or 0)

        if vol < 50:  # skip noise
            return None

        unusual = _is_unusual(vol, oi, premium)
        direction = _classify_direction(contract_type, delta)

        # Sweep heuristic: if break-even % is small + high volume, likely a sweep
        # Polygon doesn't expose exchange count directly so we use vol/OI ratio as proxy
        is_sweep = (oi > 0 and vol / oi >= 3) or premium >= 250_000

        return {
            "ticker":         ticker,
            "contract_type":  contract_type.upper(),
            "strike":         strike,
            "expiry":         expiry,
            "volume":         vol,
            "open_interest":  oi,
            "vwap":           round(vwap, 2),
            "premium_est":    int(premium),
            "premium_display": f"${premium/1000:.0f}K" if premium < 1_000_000 else f"${premium/1_000_000:.1f}M",
            "delta":          round(delta, 3),
            "direction":      direction,
            "is_unusual":     unusual,
            "is_sweep":       is_sweep,
            "vol_oi_ratio":   round(vol / oi, 1) if oi else 0,
        }
    except Exception:
        return None


# ── Public API ────────────────────────────────────────────────────────────────

def fetch_options_flow(symbols: List[str], min_premium: int = 50_000) -> Dict[str, List[Dict]]:
    """Fetch unusual options activity for a list of symbols.

    Args:
        symbols      : list of ticker symbols to query
        min_premium  : minimum estimated premium to include (default $50K)

    Returns:
        {symbol: [option_flow_dict, ...]} — sorted by premium descending
    """
    results: Dict[str, List[Dict]] = {}
    for sym in symbols:
        raw = _fetch_polygon_options(sym)
        parsed = []
        for item in raw:
            p = _parse_option(item)
            if p and p["is_unusual"] and p["premium_est"] >= min_premium:
                parsed.append(p)
        if parsed:
            parsed.sort(key=lambda x: x["premium_est"], reverse=True)
            results[sym] = parsed[:10]  # top 10 per symbol
    return results


def get_options_summary(options_flow: Dict[str, List[Dict]]) -> Dict[str, Any]:
    """Build a run-level options flow summary for alerts and dashboard header.

    Returns:
      {
        total_sweeps       : int
        total_premium      : str  (formatted)
        top_call           : dict or None
        top_put            : dict or None
        bullish_count      : int
        bearish_count      : int
        sweep_summary_text : str  (for WhatsApp)
      }
    """
    all_items = [item for items in options_flow.values() for item in items]
    sweeps       = [i for i in all_items if i["is_sweep"]]
    total_prem   = sum(i["premium_est"] for i in all_items)
    calls        = [i for i in all_items if i["contract_type"] == "CALL"]
    puts         = [i for i in all_items if i["contract_type"] == "PUT"]
    bullish      = sum(1 for i in all_items if i["direction"] == "bullish")
    bearish      = sum(1 for i in all_items if i["direction"] == "bearish")

    top_call = max(calls, key=lambda x: x["premium_est"]) if calls else None
    top_put  = max(puts,  key=lambda x: x["premium_est"]) if puts  else None

    prem_display = f"${total_prem/1_000_000:.1f}M" if total_prem >= 1_000_000 else f"${total_prem/1000:.0f}K"

    # Short WhatsApp-friendly line
    parts = [f"{len(sweeps)} sweep(s)", f"{bullish}🟢/{bearish}🔴 flow"]
    if top_call:
        sym_short = top_call["ticker"].split(":")[1][:6] if ":" in top_call["ticker"] else top_call["ticker"][:6]
        parts.append(f"Top CALL: {sym_short} {top_call['premium_display']}")
    sweep_text = "  ".join(parts) if all_items else "No unusual flow"

    return {
        "total_sweeps":       len(sweeps),
        "total_premium":      prem_display,
        "top_call":           top_call,
        "top_put":            top_put,
        "bullish_count":      bullish,
        "bearish_count":      bearish,
        "sweep_summary_text": sweep_text,
    }
