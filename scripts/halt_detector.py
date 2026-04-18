"""halt_detector.py — Trading halt detection for Trade AI v12.

Sources (tried in order):
  1. NASDAQ trading halt data feed (public CSV, no key needed)
  2. Polygon ticker snapshot (checks for zero-volume anomalies)
  3. Catalyst news scan for "halt" / "resume" keywords

Returns per-ticker halt status and a run-level halt summary.
Halted tickers are flagged on the HTML card and trigger a WhatsApp alert.
"""
from __future__ import annotations
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import requests

HALT_KEYWORDS = [
    "trading halted", "halt in effect", "trading halt",
    "circuit breaker", "luld halt", "regulatory halt",
    "sec halt", "ipo halt", "news pending halt",
]
RESUME_KEYWORDS = [
    "trading resumed", "halt lifted", "resumption of trading",
    "trading resumes",
]


def _env(k: str) -> str:
    return os.getenv(k, "").strip()


# ── NASDAQ halt feed (public, no key) ────────────────────────────────────────

def _fetch_nasdaq_halts() -> List[Dict]:
    """Parse NASDAQ's live trading halt data feed."""
    try:
        url  = "https://nasdaqtrader.com/dynamic/symdir/tradinghaltdata.txt"
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        resp.raise_for_status()
        lines   = resp.text.strip().split("\n")
        if len(lines) < 2:
            return []
        headers = [h.strip() for h in lines[0].split("|")]
        halts   = []
        for line in lines[1:]:
            parts = line.split("|")
            if len(parts) < len(headers):
                continue
            row = dict(zip(headers, [p.strip() for p in parts]))
            # Columns: Symbol, HaltDate, HaltTime, ReasonCode, Name, RegSHO, ResumptionDate, ResumptionTradeTime
            halts.append({
                "symbol":      row.get("Symbol", "").upper(),
                "halt_date":   row.get("HaltDate", ""),
                "halt_time":   row.get("HaltTime", ""),
                "reason_code": row.get("ReasonCode", ""),
                "name":        row.get("Name", ""),
                "resumed":     bool(row.get("ResumptionDate", "").strip()),
                "resume_time": row.get("ResumptionTradeTime", ""),
                "source":      "nasdaq",
            })
        return halts
    except Exception:
        return []


# ── Polygon snapshot check ────────────────────────────────────────────────────

def _check_polygon_status(symbols: List[str]) -> Dict[str, bool]:
    """Check if tickers have day.volume == 0 (possible halt proxy) via Polygon."""
    key = _env("POLYGON_API_KEY")
    if not key or not symbols:
        return {}
    try:
        url  = "https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/tickers"
        resp = requests.get(url, params={"tickers": ",".join(symbols[:50]), "apiKey": key}, timeout=10)
        resp.raise_for_status()
        result = {}
        for item in resp.json().get("tickers", []):
            sym = item.get("ticker", "")
            day_vol = item.get("day", {}).get("v", -1)
            result[sym] = (day_vol == 0)   # True if possibly halted
        return result
    except Exception:
        return {}


# ── Catalyst news scan ────────────────────────────────────────────────────────

def _scan_catalysts_for_halts(enrichments: Dict[str, Dict]) -> Dict[str, str]:
    """Check catalyst headlines for halt/resume keywords."""
    halt_status: Dict[str, str] = {}
    for sym, data in enrichments.items():
        for cat in data.get("catalysts", [])[:10]:
            title   = (cat.get("title") or "").lower()
            summary = (cat.get("summary") or "").lower()
            text    = title + " " + summary
            if any(kw in text for kw in RESUME_KEYWORDS):
                halt_status[sym] = "resumed"
                break
            if any(kw in text for kw in HALT_KEYWORDS):
                halt_status[sym] = "halted"
                break
    return halt_status


# ── Reason code decoder ───────────────────────────────────────────────────────

REASON_CODES = {
    "T1": "News Pending",
    "T2": "News Released",
    "T3": "News and Resumption Times",
    "T5": "Single Stock Circuit Breaker",
    "T6": "Extraordinary Market Activity",
    "T8": "ETF",
    "T12": "Additional Information Requested",
    "H4": "Non-compliance",
    "H9": "Not Current",
    "H10": "SEC Trading Suspension",
    "H11": "Regulatory Concern",
    "LUDP": "LULD Pause",
    "LUDS": "LULD Straddle State",
    "MWC1": "Market-Wide Circuit Breaker Lvl 1",
    "MWC2": "Market-Wide Circuit Breaker Lvl 2",
    "MWC3": "Market-Wide Circuit Breaker Lvl 3",
    "IPO1": "IPO Not Yet Trading",
    "M": "Volatility Trading Pause",
    "D": "Security Deleted",
}


# ── Main detector ─────────────────────────────────────────────────────────────

def detect_halts(
    scored_tickers: List[Dict[str, Any]],
    enrichments: Dict[str, Dict] | None = None,
) -> Dict[str, Any]:
    """Detect halts and resumes for the current watchlist.

    Returns:
      {
        halted_tickers  : [{symbol, status, reason, reason_text, source}]
        resumed_tickers : [{symbol, status, reason, reason_text, source}]
        halt_count      : int
        resume_count    : int
        halt_map        : {symbol: halt_info_dict}  (for quick lookup)
      }
    """
    symbols = [t["symbol"] for t in scored_tickers if t.get("symbol")]

    # Collect halt data from all sources
    nasdaq_halts    = _fetch_nasdaq_halts()
    polygon_paused  = _check_polygon_status(symbols)
    catalyst_halts  = _scan_catalysts_for_halts(enrichments or {})

    # Build halt map indexed by symbol
    halt_map: Dict[str, Dict] = {}

    # NASDAQ feed — most authoritative
    today_str = datetime.now(timezone.utc).strftime("%m/%d/%Y")
    for h in nasdaq_halts:
        sym = h["symbol"]
        if sym not in symbols:
            continue
        if h.get("halt_date", "") != today_str:
            continue   # only care about today's halts
        status = "resumed" if h["resumed"] else "halted"
        reason = h.get("reason_code", "")
        halt_map[sym] = {
            "symbol":      sym,
            "status":      status,
            "reason":      reason,
            "reason_text": REASON_CODES.get(reason, reason),
            "halt_time":   h.get("halt_time", ""),
            "resume_time": h.get("resume_time", ""),
            "source":      "nasdaq",
        }

    # Polygon zero-volume proxy (only add if not already from NASDAQ)
    for sym, possibly_halted in polygon_paused.items():
        if possibly_halted and sym in symbols and sym not in halt_map:
            halt_map[sym] = {
                "symbol":      sym,
                "status":      "possibly_halted",
                "reason":      "zero_volume",
                "reason_text": "No volume detected via Polygon snapshot",
                "source":      "polygon",
            }

    # Catalyst keyword scan (only add if not already caught)
    for sym, status in catalyst_halts.items():
        if sym in symbols and sym not in halt_map:
            halt_map[sym] = {
                "symbol":  sym,
                "status":  status,
                "reason":  "news_mention",
                "reason_text": "Halt/resume keyword in catalyst feed",
                "source":  "catalyst_news",
            }

    # Annotate scored tickers with halt info
    for t in scored_tickers:
        info = halt_map.get(t["symbol"])
        t["halt_info"] = info
        t["is_halted"]  = bool(info and info["status"] in ("halted", "possibly_halted"))
        t["is_resumed"] = bool(info and info["status"] == "resumed")

    halted  = [v for v in halt_map.values() if v["status"] in ("halted", "possibly_halted")]
    resumed = [v for v in halt_map.values() if v["status"] == "resumed"]

    return {
        "halted_tickers":  halted,
        "resumed_tickers": resumed,
        "halt_count":      len(halted),
        "resume_count":    len(resumed),
        "halt_map":        halt_map,
    }
