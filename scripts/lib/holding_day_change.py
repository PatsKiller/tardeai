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

    pct_num = float(day_pct) if day_pct is not None else None

    # The stored dollar day_change is only trustworthy when it is CONSISTENT with the
    # day %: either the % is ~0 (genuinely flat) OR the stored $ is materially non-zero.
    # A stored $0 sitting next to a non-zero % (fresh from Finviz) is a stale/never-priced
    # dollar value — the repricer wrote 0 because prev_price == new_price at write time,
    # while Finviz carries the real intraday %. In that case fall through and recompute
    # the $ from the %; otherwise the portfolio day total silently drops those positions.
    stored_consistent = (
        h_day is not None
        and (abs(float(h_day)) > 0.005 or pct_num is None or abs(pct_num) < 0.01)
    )

    if stored_consistent and not price_changed:
        return float(h_day), day_pct if day_pct is not None else h_day_pct

    if price_changed and h_day is not None and abs(float(h_day)) > 0.005 and h_mv > 0 and market_value > 0:
        return round(float(h_day) * (market_value / h_mv), 2), day_pct

    # Accurate $ from %: day$ = MV − MV/(1+pct/100) = MV·pct/(100+pct). Matches the
    # repricer convention (e.g. QCOM stored 175.17 = MV·pct/(100+pct), not MV·pct/100).
    if pct_num is not None and market_value:
        prev_mv = market_value / (1.0 + pct_num / 100.0) if (1.0 + pct_num / 100.0) != 0 else market_value
        return round(market_value - prev_mv, 2), day_pct

    return float(h_day or 0), day_pct if day_pct is not None else h_day_pct