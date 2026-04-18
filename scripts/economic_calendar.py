"""economic_calendar.py — Economic & earnings calendar for Trade AI v11.

Fetches via FMP:
  - Economic events (Fed decisions, CPI, NFP, PPI, GDP, etc.)
  - Earnings calendar (companies reporting today or tomorrow)

Flags any tickers in the current watchlist that are reporting earnings.
"""
from __future__ import annotations
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
import requests


# ── Helpers ───────────────────────────────────────────────────────────────────

def _env(k: str) -> str:
    return os.getenv(k, "").strip()

def _date_range(offset_days: int = 1) -> tuple[str, str]:
    today = datetime.now(timezone.utc).date()
    future = today + timedelta(days=offset_days)
    return str(today), str(future)

def _impact_label(impact: str) -> str:
    mapping = {"High": "🔴 HIGH", "Medium": "🟡 MED", "Low": "⚪ LOW"}
    return mapping.get(impact or "", "⚪ LOW")


# ── FMP fetchers ──────────────────────────────────────────────────────────────

def fetch_economic_events(days_ahead: int = 1) -> List[Dict[str, Any]]:
    """Fetch macro events (Fed, CPI, NFP, etc.) for today and upcoming days."""
    key = _env("FMP_API_KEY")
    if not key:
        return []
    try:
        from_date, to_date = _date_range(days_ahead)
        url = "https://financialmodelingprep.com/stable/economic-calendar"
        resp = requests.get(url, params={
            "from": from_date, "to": to_date, "apikey": key
        }, timeout=10)
        resp.raise_for_status()
        events = []
        for item in resp.json() or []:
            events.append({
                "date":       item.get("date", ""),
                "event":      item.get("event", ""),
                "country":    item.get("country", "US"),
                "impact":     _impact_label(item.get("impact", "")),
                "actual":     item.get("actual", "—"),
                "forecast":   item.get("estimate", "—"),
                "previous":   item.get("previous", "—"),
            })
        # Sort by date, high-impact first
        events.sort(key=lambda e: (e["date"], 0 if "HIGH" in e["impact"] else 1))
        return events
    except Exception:
        return []


def fetch_earnings_calendar(days_ahead: int = 1) -> List[Dict[str, Any]]:
    """Fetch earnings reports for today and tomorrow."""
    key = _env("FMP_API_KEY")
    if not key:
        return []
    try:
        from_date, to_date = _date_range(days_ahead)
        url = "https://financialmodelingprep.com/stable/earnings-calendar"
        resp = requests.get(url, params={
            "from": from_date, "to": to_date, "apikey": key
        }, timeout=10)
        resp.raise_for_status()
        earnings = []
        for item in resp.json() or []:
            eps_est  = item.get("epsEstimated")
            rev_est  = item.get("revenueEstimated")
            earnings.append({
                "symbol":       item.get("symbol", ""),
                "company":      item.get("name", ""),
                "date":         item.get("date", ""),
                "time":         item.get("time", "bmo"),   # bmo / amc
                "eps_est":      f"${eps_est:.2f}" if eps_est is not None else "—",
                "revenue_est":  f"${rev_est/1e9:.1f}B" if rev_est else "—",
            })
        return earnings
    except Exception:
        return []


# ── Watchlist cross-reference ─────────────────────────────────────────────────

def flag_earnings_in_watchlist(
    scored_tickers: List[Dict[str, Any]],
    earnings: List[Dict[str, Any]],
) -> List[str]:
    """Return list of symbols in scored_tickers that are reporting earnings."""
    watchlist_syms = {t["symbol"] for t in scored_tickers}
    return [e["symbol"] for e in earnings if e["symbol"] in watchlist_syms]


# ── Main call ─────────────────────────────────────────────────────────────────

def get_calendar(scored_tickers: Optional[List[Dict]] = None) -> Dict[str, Any]:
    """Fetch full calendar and optionally cross-reference against watchlist.

    Returns:
      {
        economic_events     : list of event dicts
        earnings            : list of earnings dicts
        watchlist_earnings  : list of symbols reporting earnings (if tickers passed)
        high_impact_events  : list of HIGH-impact economic events only
      }
    """
    economic   = fetch_economic_events(days_ahead=2)
    earnings   = fetch_earnings_calendar(days_ahead=1)
    high_impact = [e for e in economic if "HIGH" in e.get("impact", "")]
    watchlist_e = flag_earnings_in_watchlist(scored_tickers or [], earnings)

    return {
        "economic_events":    economic,
        "earnings":           earnings,
        "watchlist_earnings": watchlist_e,
        "high_impact_events": high_impact,
    }
