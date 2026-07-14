"""Canonical per-holding day P&L for portfolio API — matches repricer holdings.json."""
from __future__ import annotations

from typing import Any, Optional


def resolve_holding_day_change(
    holding: dict,
    *,
    market_value: float,
    price: float,
    stale_price: float,
    finviz_day_pct: Optional[float] = None,
) -> tuple[float, Any]:
    """Return (day_change, day_change_pct) aligned with portfolio_repricer when price unchanged."""
    if holding.get("is_cash") or (holding.get("symbol") or "").upper() == "CASH":
        return 0.0, 0.0

    h_day = holding.get("day_change")
    h_day_pct = holding.get("day_change_pct")
    h_mv = float(holding.get("market_value") or 0)

    day_pct = h_day_pct
    if (day_pct is None or float(day_pct or 0) == 0) and finviz_day_pct is not None:
        day_pct = finviz_day_pct

    price_changed = (
        price > 0
        and stale_price > 0
        and abs(price - stale_price) > max(0.005, abs(stale_price) * 1e-6)
    )

    if h_day is not None and not price_changed:
        return float(h_day), day_pct if day_pct is not None else h_day_pct

    if price_changed and h_day is not None and h_mv > 0 and market_value > 0:
        return round(float(h_day) * (market_value / h_mv), 2), day_pct

    if day_pct is not None and market_value:
        return round(market_value * float(day_pct) / 100, 2), day_pct

    return float(h_day or 0), day_pct if day_pct is not None else h_day_pct