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

def test_stale_zero_dollar_recomputed_from_finviz_pct():
    """The bug: a stored day_change of $0 next to a NON-ZERO % (fresh Finviz) was
    trusted, dropping the position from the portfolio day total. It must recompute
    the $ from the % instead (accurate MV·pct/(100+pct) form)."""
    h = {"symbol": "SCHG", "market_value": 265715.0, "day_change": 0.0, "day_change_pct": 0.35}
    chg, pct = resolve_holding_day_change(
        h, market_value=265715.0, price=34.18, stale_price=34.18, finviz_day_pct=0.35,
    )
    assert abs(chg - 926.76) < 1.0, f"expected ~926.76, got {chg}"
    assert pct == 0.35


def test_genuinely_flat_position_stays_zero():
    h = {"symbol": "AMANX", "market_value": 4960.0, "day_change": 0.0, "day_change_pct": 0.0}
    chg, pct = resolve_holding_day_change(
        h, market_value=4960.0, price=78.27, stale_price=78.27, finviz_day_pct=0.0,
    )
    assert chg == 0.0 and pct == 0.0


def test_negative_day_recomputed_from_pct():
    h = {"symbol": "V", "market_value": 72229.0, "day_change": 0.0, "day_change_pct": -1.32}
    chg, _ = resolve_holding_day_change(
        h, market_value=72229.0, price=358.56, stale_price=358.56, finviz_day_pct=-1.32,
    )
    assert -970 < chg < -960, f"expected ~-966, got {chg}"
