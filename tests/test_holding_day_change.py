"""Day P&L resolution — portfolio API must match repricer holdings.json."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "lib"))

from holding_day_change import resolve_holding_day_change  # noqa: E402


def test_uses_holdings_day_change_when_price_unchanged():
    h = {"market_value": 171300.0, "day_change": -550.0, "day_change_pct": -0.32}
    chg, pct = resolve_holding_day_change(
        h, market_value=171300.0, price=34.26, stale_price=34.26, finviz_day_pct=-0.32,
    )
    assert chg == -550.0
    assert pct == -0.32


def test_cash_never_inherits_finviz_ticker_pollution():
    h = {"symbol": "CASH", "is_cash": True, "market_value": 17540.67, "shares": 17540.67}
    chg, pct = resolve_holding_day_change(
        h, market_value=17540.67, price=1.0, stale_price=1.0, finviz_day_pct=-0.75,
    )
    assert chg == 0.0
    assert pct == 0.0


def test_recalc_only_when_price_overlay_changed():
    h = {"market_value": 1000.0, "day_change": -10.0, "day_change_pct": -1.0}
    chg, _ = resolve_holding_day_change(
        h, market_value=1100.0, price=110.0, stale_price=100.0,
    )
    assert chg == -11.0