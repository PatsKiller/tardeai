"""Daily Bars — Data Broker read model over ticker_prices (daily closes).

Registry domain ``technicals`` names ticker_prices as its table (4 writers today,
consolidation target scripts/portfolio_repricer.py; stale after 26h). Hub handlers
that need "last close for SYMBOL" or a short close series read here, not
``FROM ticker_prices``. The 2026-08-27 price-corruption scrub quarantined 92 rows
from this table; the envelope's age is the first thing a reader should look at.

Zero provider calls. Read-only.
"""
from __future__ import annotations

from typing import Any

from lib.data_broker.envelope import envelope

DOMAIN = "technicals"

LAST_CLOSE_SQL = """SELECT symbol, price_date, close_price, source, created_at
                    FROM ticker_prices WHERE upper(symbol)=%s
                    ORDER BY price_date DESC LIMIT 1"""

SERIES_SQL = """SELECT symbol, price_date, close_price, source
                FROM ticker_prices WHERE upper(symbol)=%s
                  AND price_date > CURRENT_DATE - %s
                ORDER BY price_date"""


def _f(v: Any) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def get_last_close(db_query, symbol: str, *, now=None, registry=None) -> dict[str, Any]:
    """{ok, symbol, close, price_date, <envelope>} for one symbol; close None when no row."""
    sym = str(symbol or "").upper().strip()
    row = None
    error = None
    if sym:
        try:
            row = db_query(LAST_CLOSE_SQL, (sym,), fetch="one")
        except Exception as e:  # noqa: BLE001
            error = str(e)[:200]
    close = _f(row.get("close_price")) if row else None
    price_date = row.get("price_date") if row else None
    env = envelope(DOMAIN, price_date, now=now, registry=registry,
                   source={"table": "ticker_prices", "row_source": (row or {}).get("source")})
    out = {"ok": error is None, "symbol": sym, "close": close,
           "price_date": price_date.isoformat() if hasattr(price_date, "isoformat") else price_date,
           "provider_calls": 0}
    if error:
        out["error"] = error
    out.update(env)
    return out


def get_daily_bars(db_query, symbol: str, *, days: int = 90, now=None, registry=None) -> dict[str, Any]:
    """{ok, symbol, bars: [{price_date, close}], <envelope>} — close-only daily series."""
    sym = str(symbol or "").upper().strip()
    rows: list[dict[str, Any]] = []
    error = None
    if sym:
        try:
            rows = db_query(SERIES_SQL, (sym, int(days)), fetch="all") or []
        except Exception as e:  # noqa: BLE001
            error = str(e)[:200]
    bars = []
    for r in rows:
        pd = r.get("price_date")
        bars.append({"price_date": pd.isoformat() if hasattr(pd, "isoformat") else pd, "close": _f(r.get("close_price"))})
    as_of = rows[-1].get("price_date") if rows else None
    env = envelope(DOMAIN, as_of, now=now, registry=registry, source={"table": "ticker_prices"})
    out = {"ok": error is None, "symbol": sym, "bars": bars, "n": len(bars), "provider_calls": 0}
    if error:
        out["error"] = error
    out.update(env)
    return out
