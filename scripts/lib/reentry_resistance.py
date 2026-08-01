"""Closed-session resistance intelligence for Re-Entry.

Computes an auditable resistance level from ticker_prices without treating an
intraday cross as a hold. Results are persisted in ui_prefs for the dashboard and
refreshed by the existing 20-minute Watch alert pass.
"""
from __future__ import annotations

import datetime as dt
import json
from typing import Any, Callable

CACHE_KEY = "portfolio.reentry.resistance.v1"
MANDATE_KEY = "portfolio.reentry.mandates.v4"
ROTATION_KEY = "portfolio.reentry.rotation-links.v1"
TOLERANCE_PCT = 0.5
LOOKBACK = 20
TEST_LOOKBACK = 60


def _dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _pref(ex: Callable[..., Any], key: str) -> dict[str, Any]:
    row = ex("SELECT value FROM ui_prefs WHERE key=%s", (key,), fetch="one") or {}
    return _dict(row.get("value"))


def _f(value: Any) -> float | None:
    try:
        number = float(value)
        return number if number == number else None
    except (TypeError, ValueError):
        return None


def _series(ex: Callable[..., Any], symbol: str, days: int = 180) -> list[tuple[dt.date, float]]:
    rows = ex(
        """SELECT price_date, close_price FROM ticker_prices
           WHERE upper(symbol)=%s AND price_date > CURRENT_DATE - %s
             AND close_price IS NOT NULL
           ORDER BY price_date""",
        (symbol.upper(), days), fetch="all",
    ) or []
    by_date: dict[dt.date, float] = {}
    for row in rows:
        date_value = row.get("price_date")
        close = _f(row.get("close_price"))
        if close is None or close <= 0 or date_value is None:
            continue
        if isinstance(date_value, dt.datetime):
            date_value = date_value.date()
        elif not isinstance(date_value, dt.date):
            try:
                date_value = dt.date.fromisoformat(str(date_value)[:10])
            except Exception:
                continue
        by_date[date_value] = close
    return sorted(by_date.items())


def compute_resistance(series: list[tuple[dt.date, float]]) -> dict[str, Any]:
    """Return stable breakout/hold evidence from daily closes.

    An active hold begins only when a close exceeds the prior 20-session maximum
    by more than the tolerance and every later close remains at or above that
    breakout level within tolerance. If no active hold exists, resistance is the
    maximum of the prior 20 closes and hold count remains zero.
    """
    if len(series) < LOOKBACK + 1:
        return {
            "state": "UNAVAILABLE",
            "resistance": None,
            "distance_pct": None,
            "hold_days": None,
            "hold_start": None,
            "tests": None,
            "as_of": series[-1][0].isoformat() if series else None,
            "reason": f"need at least {LOOKBACK + 1} closed sessions",
        }
    dates = [row[0] for row in series]
    closes = [row[1] for row in series]
    latest = closes[-1]
    active_index = None
    active_level = None
    first = max(LOOKBACK, len(series) - TEST_LOOKBACK)
    for index in range(first, len(series)):
        level = max(closes[index - LOOKBACK:index])
        breakout = closes[index] > level * (1 + TOLERANCE_PCT / 100)
        held = all(close >= level * (1 - TOLERANCE_PCT / 100) for close in closes[index:])
        if breakout and held:
            active_index = index
            active_level = level
            break
    if active_level is None:
        resistance = max(closes[-LOOKBACK - 1:-1])
        hold_days = 0
        hold_start = None
    else:
        resistance = active_level
        hold_days = len(series) - active_index
        hold_start = dates[active_index].isoformat()
    distance_pct = (latest - resistance) / resistance * 100 if resistance else None
    if distance_pct is None:
        state = "UNAVAILABLE"
    elif abs(distance_pct) <= TOLERANCE_PCT:
        state = "TESTING"
    elif distance_pct > 0:
        state = "ABOVE"
    else:
        state = "BELOW"
    recent = closes[-TEST_LOOKBACK:]
    tests = sum(1 for close in recent if abs((close - resistance) / resistance * 100) <= TOLERANCE_PCT)
    return {
        "state": state,
        "resistance": round(resistance, 4),
        "current_close": round(latest, 4),
        "distance_pct": round(distance_pct, 3) if distance_pct is not None else None,
        "hold_days": hold_days,
        "hold_start": hold_start,
        "tests": tests,
        "as_of": dates[-1].isoformat(),
        "tolerance_pct": TOLERANCE_PCT,
        "method": "active breakout over prior 20-session max; closed-session hold only",
    }


def _symbols(ex: Callable[..., Any]) -> list[str]:
    symbols = {str(symbol).upper() for symbol in _pref(ex, MANDATE_KEY) if symbol}
    for link in _pref(ex, ROTATION_KEY).values():
        if not isinstance(link, dict):
            continue
        for key in ("sourceSymbol", "destinationSymbol"):
            value = str(link.get(key) or "").upper().strip()
            if value:
                symbols.add(value)
    rows = ex(
        """SELECT DISTINCT upper(symbol) AS symbol FROM trade_transactions
           WHERE trade_date >= CURRENT_DATE - 365
             AND symbol IS NOT NULL
             AND NOT (lower(coalesce(account,'')) LIKE '%paper%'
                      OR lower(coalesce(account,'')) LIKE '%sim%'
                      OR lower(coalesce(account,'')) LIKE '%sandbox%'
                      OR lower(coalesce(account,'')) LIKE '%test%')
             AND (lower(coalesce(action,'')) IN
                    ('sell','sold','assigned','assignment','expired','exercise','exercised','close','closed')
                  OR lower(coalesce(action,'')) LIKE 'sell%')
           ORDER BY 1 LIMIT 1500""",
        fetch="all",
    ) or []
    symbols.update(str(row.get("symbol") or "").upper() for row in rows if row.get("symbol"))
    return sorted(symbol for symbol in symbols if symbol)


def _attach_live_quote(symbol: str, row: dict[str, Any]) -> dict[str, Any]:
    """Attach broker live quote metadata without changing closed-session authority."""
    try:
        import sys
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent.parent
        scripts = str(root / "scripts")
        if scripts not in sys.path:
            sys.path.insert(0, scripts)
        from market_quote_provider import get_best_quote
        q = get_best_quote(symbol) or {}
        price = _f(q.get("last_price"))
        if price and price > 0:
            row["live_price"] = round(price, 4)
            row["live_as_of"] = q.get("quote_timestamp")
            row["live_source"] = q.get("provider") or "get_best_quote"
    except Exception:
        pass
    return row


def refresh_resistance_cache(ex: Callable[..., Any]) -> dict[str, Any]:
    generated_at = dt.datetime.now(dt.timezone.utc).isoformat()
    symbols = _symbols(ex)
    # Data Broker: ensure daily closes exist for exit/mandate universe before compute.
    try:
        import sys
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent.parent
        scripts = str(root / "scripts")
        if scripts not in sys.path:
            sys.path.insert(0, scripts)
        from price_db_sync import ensure_price_history
        ensure_price_history(symbols, min_rows=LOOKBACK + 5, yfinance_cap=min(40, len(symbols)))
    except Exception:
        pass
    values: dict[str, Any] = {}
    for symbol in symbols:
        try:
            row = compute_resistance(_series(ex, symbol))
        except Exception as error:
            row = {
                "state": "UNAVAILABLE",
                "resistance": None,
                "distance_pct": None,
                "hold_days": None,
                "hold_start": None,
                "tests": None,
                "as_of": None,
                "reason": str(error)[:160],
            }
        values[symbol] = _attach_live_quote(symbol, row)
    payload = {
        "version": "reentry_resistance_v1",
        "generated_at": generated_at,
        "symbol_count": len(values),
        "symbols": values,
    }
    ex(
        """INSERT INTO ui_prefs (key, value, updated_at)
           VALUES (%s,%s::jsonb,NOW())
           ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=NOW()""",
        (CACHE_KEY, json.dumps(payload)), fetch=None,
    )
    return payload
