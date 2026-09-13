"""economic_calendar.py — Economic & earnings calendar for Trade AI v11.

Earnings calendar from symbol_profiles (the store of record, yfinance-fed).
Macro events: no declared provider since FMP was retired 2026-09-13 — returns [].

Flags any tickers in the current watchlist that are reporting earnings.
"""
from __future__ import annotations
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional


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


# ── Fetchers ──────────────────────────────────────────────────────────────────
# FMP was retired 2026-09-13 (paid-only; HTTP 403/429 since July). Earnings dates
# now come from the store of record, symbol_profiles.next_earnings_date (written by
# earnings_enrich.py from yfinance). No macro-events calendar provider is declared
# in config/data_source_authority.json, so fetch_economic_events returns the empty,
# honest answer and the caller renders a declared gap — never a stale list.

def _db_rows(sql: str, params: tuple) -> List[Dict[str, Any]]:
    try:
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from session13_db import get_conn  # type: ignore
        import psycopg2.extras
        with get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                return [dict(r) for r in cur.fetchall()]
    except Exception:
        return []


def fetch_economic_events(days_ahead: int = 1) -> List[Dict[str, Any]]:
    """Macro events: no provider declared (FMP retired 2026-09-13). Declared gap."""
    return []


def fetch_earnings_calendar(days_ahead: int = 1) -> List[Dict[str, Any]]:
    """Companies reporting between today and today+days_ahead, from symbol_profiles."""
    from_date, to_date = _date_range(days_ahead)
    rows = _db_rows(
        """SELECT symbol, company_name, next_earnings_date::text AS date, last_eps_estimate
             FROM symbol_profiles
            WHERE next_earnings_date BETWEEN %s::date AND %s::date
            ORDER BY next_earnings_date, symbol""",
        (from_date, to_date),
    )
    out = []
    for r in rows:
        eps = r.get("last_eps_estimate")
        out.append({
            "symbol": r.get("symbol", ""),
            "company": r.get("company_name") or "",
            "date": r.get("date") or "",
            "time": "",
            "eps_est": f"${float(eps):.2f}" if eps is not None else "—",
            "revenue_est": "—",
            "source": "symbol_profiles",
        })
    return out


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
