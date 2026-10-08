"""OHLC Bars — Data Broker read model for daily candles (Investment Command Center chart, operator 2026-10-08).

market_ohlcv_bars (timeframe 'daily', ~1,210 symbols, ~247 bars each, written by market_data_snapshot_loader) had
no reader. Falls back to ticker_prices closes (line chart) when a symbol has no candles. Zero provider calls.
"""
from __future__ import annotations

from typing import Any

from lib.data_broker.envelope import envelope

DOMAIN = "technicals"
BARS_SQL = """SELECT bar_time, open, high, low, close, volume FROM market_ohlcv_bars
               WHERE upper(symbol) = %s AND timeframe = 'daily' AND bar_time > now() - (%s || ' days')::interval
               ORDER BY bar_time"""
CLOSES_SQL = """SELECT price_date, close_price FROM ticker_prices
                 WHERE upper(symbol) = %s AND price_date > CURRENT_DATE - %s ORDER BY price_date"""


def _f(v: Any) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _d(v: Any) -> str | None:
    return v.date().isoformat() if hasattr(v, "date") and callable(v.date) else (
        v.isoformat() if hasattr(v, "isoformat") else (str(v)[:10] if v else None))


def get_daily_ohlc(db_query, symbol: str, *, days: int = 180, now=None, registry=None) -> dict[str, Any]:
    """{ok, symbol, kind: candles|closes|none, bars: [{time, open, high, low, close, volume}], <envelope>}."""
    sym = str(symbol or "").upper().strip()
    bars: list[dict[str, Any]] = []
    kind = "none"
    try:
        rows = db_query(BARS_SQL, (sym, str(int(days)))) or []
        bars = [{"time": _d(r.get("bar_time")), "open": _f(r.get("open")), "high": _f(r.get("high")),
                 "low": _f(r.get("low")), "close": _f(r.get("close")), "volume": _f(r.get("volume"))}
                for r in rows if _f(r.get("close")) is not None]
        kind = "candles" if bars else kind
        if not bars:
            rows = db_query(CLOSES_SQL, (sym, int(days))) or []
            bars = [{"time": _d(r.get("price_date")), "close": _f(r.get("close_price"))}
                    for r in rows if _f(r.get("close_price")) is not None]
            kind = "closes" if bars else "none"
        err = None
    except Exception as e:  # noqa: BLE001
        err = str(e)[:200]
    out = {"ok": err is None, "symbol": sym, "kind": kind, "bars": bars, "n": len(bars), "provider_calls": 0}
    if err:
        out["error"] = err
    out.update(envelope(DOMAIN, bars[-1]["time"] if bars else None, now=now, registry=registry,
                        source={"table": "market_ohlcv_bars" if kind == "candles" else "ticker_prices"}))
    return out
