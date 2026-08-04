"""Canonical quote batch helper — routes live prices through get_best_quote.

Used by portfolio_repricer, portfolio_live_monitor, and day-change helpers so
quote_last_price has one waterfall (Alpaca → Schwab → … → yfinance → Finviz cache)
instead of ad-hoc Finviz-only scrapes. Finviz enrichment fields (analyst, perf_*,
rvol) remain on the Finviz batch path; only price/prev_close/change_pct are broker-overlaid.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent


def _ensure_scripts_path() -> None:
    scripts = str(PROJECT_ROOT / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)


def quote_row_from_broker(symbol: str) -> dict[str, Any] | None:
    """Return a finviz_quote_cache-compatible row from get_best_quote, or None."""
    _ensure_scripts_path()
    from market_quote_provider import get_best_quote

    q = get_best_quote(symbol) or {}
    price = q.get("last_price")
    if price is None:
        return None
    try:
        price = float(price)
    except (TypeError, ValueError):
        return None
    if price <= 0:
        return None

    raw = q.get("raw_payload") or {}
    chg_pct = raw.get("change_pct") or raw.get("regularMarketChangePercent")
    if chg_pct is None and q.get("day_change_pct") is not None:
        chg_pct = q.get("day_change_pct")
    try:
        chg_pct = float(chg_pct) if chg_pct is not None else 0.0
    except (TypeError, ValueError):
        chg_pct = 0.0

    prev_close = raw.get("prev_close") or raw.get("regularMarketPreviousClose")
    if prev_close is None and chg_pct != -100:
        prev_close = price / (1 + chg_pct / 100)
    try:
        prev_close = float(prev_close) if prev_close is not None else price
    except (TypeError, ValueError):
        prev_close = price

    return {
        "price": round(price, 4),
        "change_pct": round(chg_pct, 4),
        "prev_close": round(prev_close, 4),
        "volume": int(q.get("day_volume") or raw.get("volume") or 0),
        "source": q.get("provider") or "broker",
        "broker_provider": q.get("provider"),
    }


def overlay_broker_prices(
    finviz_rows: dict[str, dict[str, Any]],
    symbols: list[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Merge get_best_quote prices onto Finviz enrichment rows. Mutates finviz_rows in place."""
    syms = symbols or list(finviz_rows.keys())
    for sym in syms:
        broker = quote_row_from_broker(sym)
        if not broker:
            continue
        row = finviz_rows.setdefault(sym, {})
        row["price"] = broker["price"]
        row["change_pct"] = broker["change_pct"]
        row["prev_close"] = broker["prev_close"]
        if broker.get("volume"):
            row["volume"] = broker["volume"]
        row["source"] = broker["source"]
        row["price_authority"] = "get_best_quote"
    return finviz_rows


def quote_cache_day_maps(cache: dict[str, Any]) -> tuple[dict[str, float], dict[str, float]]:
    """Extract upper-case symbol → day_pct and price maps from a quote cache dict."""
    day_pct: dict[str, float] = {}
    px: dict[str, float] = {}
    for sym, row in (cache or {}).items():
        if sym.startswith("_") or not isinstance(row, dict):
            continue
        u = str(sym).upper()
        if row.get("change_pct") is not None:
            try:
                day_pct[u] = float(row["change_pct"])
            except (TypeError, ValueError):
                pass
        if row.get("price"):
            try:
                px[u] = float(row["price"])
            except (TypeError, ValueError):
                pass
    return day_pct, px
