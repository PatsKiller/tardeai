"""Slice 14: rebalancer flags CIO AVOID contradictions. Does not stop. Does not execute."""
from __future__ import annotations

from scripts.lib.cio_rebalancer_readonly import avoid_symbols_from_product, flag_orders_against_avoid


def test_buy_suggestion_on_avoid_is_flagged_not_dropped():
    product = {
        "action_book": {"AVOID": [{"symbol": "ARKG"}]},
        "recommendations": [{"symbol": "ARKG", "recommended_action": "AVOID"}],
    }
    orders = [{
        "action": "BUY",
        "suggested_tickers": ["ARKG", "SCHG"],
        "current_tickers": [],
        "amount_usd": 1000,
    }]
    out = flag_orders_against_avoid(orders, product)
    assert len(out) == 1
    assert out[0]["cio_avoid_contradiction"] is True
    assert "ARKG" in out[0]["cio_avoid_symbols"]
    assert out[0]["action"] == "BUY"
    assert out[0]["amount_usd"] == 1000


def test_no_avoid_leaves_orders_unflagged():
    out = flag_orders_against_avoid(
        [{"action": "BUY", "suggested_tickers": ["VTI"], "current_tickers": []}],
        {"action_book": {"AVOID": []}},
    )
    assert out[0]["cio_avoid_contradiction"] is False
    assert avoid_symbols_from_product({}) == set()
