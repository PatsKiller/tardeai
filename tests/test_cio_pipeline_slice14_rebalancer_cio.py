"""Slice 14 / G-AUTH-01: rebalancer drops CIO AVOID contradictions by default.

Does not stop the job for remaining orders. Does not execute broker.
"""
from __future__ import annotations

from scripts.lib.cio_rebalancer_readonly import (
    avoid_symbols_from_product,
    drop_orders_against_avoid,
    flag_orders_against_avoid,
)


def test_buy_suggestion_on_avoid_is_dropped_by_default():
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
    assert out == []
    kept, dropped = drop_orders_against_avoid(orders, product)
    assert kept == []
    assert len(dropped) == 1
    assert dropped[0]["cio_avoid_contradiction"] is True
    assert "ARKG" in dropped[0]["cio_avoid_symbols"]
    assert dropped[0]["action"] == "BUY"
    assert dropped[0]["amount_usd"] == 1000


def test_flag_only_when_drop_contradictions_false():
    product = {
        "action_book": {"AVOID": [{"symbol": "ARKG"}]},
    }
    orders = [{
        "action": "BUY",
        "suggested_tickers": ["ARKG", "SCHG"],
        "current_tickers": [],
        "amount_usd": 1000,
    }]
    out = flag_orders_against_avoid(orders, product, drop_contradictions=False)
    assert len(out) == 1
    assert out[0]["cio_avoid_contradiction"] is True
    assert "ARKG" in out[0]["cio_avoid_symbols"]
    assert out[0]["action"] == "BUY"


def test_no_avoid_leaves_orders_unflagged():
    out = flag_orders_against_avoid(
        [{"action": "BUY", "suggested_tickers": ["VTI"], "current_tickers": []}],
        {"action_book": {"AVOID": []}},
    )
    assert len(out) == 1
    assert out[0]["cio_avoid_contradiction"] is False
    assert avoid_symbols_from_product({}) == set()
