"""Ideas census states the limited universe. No broker."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.options_universe_census import BANNER, build_universe_census


def test_fixture_universe_is_not_a_market_search():
    holdings = [
        {"symbol": "V", "shares": 130},
        {"symbol": "SCHD", "shares": 1912},
        {"symbol": "CASH", "is_cash": True, "shares": 1},
        {"symbol": "NOC", "shares": 0.23},
    ]
    convictions = [
        {"symbol": "DXCM", "source": "layer4"},
        {"symbol": "ACIO", "source": "operator_starred"},
        {"symbol": "LMT", "source": "watchlist_buy_strong_buy"},
    ]
    listed = [
        {"symbol": "V", "enterprise": {"live_eligible": False, "blocks": ["spread 34% > 12%"]}},
        {"symbol": "DXCM", "enterprise": {"blocks": ["OI 0 < 50"]}},
    ]
    census = build_universe_census(
        holdings=holdings,
        convictions=convictions,
        scored=2,
        listed=listed,
        inputs_recorded=True,
    )
    assert census["claim"] == "not_a_market_wide_search"
    assert census["banner"] == BANNER
    assert "not a market-wide" in census["banner"]
    assert census["screened"] == 6  # V, SCHD, NOC, DXCM, ACIO, LMT
    assert census["sources"]["watchlist_used"] == 1
    assert census["sources"]["watchlist_buy_strong_buy_limit"] == 40
    assert census["sources"]["holdings"] == 3
    assert census["sources"]["liquid_options_core_included"] is False
    assert census["sources"]["layer4_limit"] == 40
    assert census["scored"] == 2
    assert census["listed"] == 2
    assert census["blocked"] == 2
    assert census["ranking"].startswith("edge_score")


def test_research_memo_answers_or_says_missing():
    from scripts.lib.options_research_memo import build_research_memo
    memo = build_research_memo({
        "symbol": "DXCM",
        "strategy": "cash_secured_put",
        "dte": 35,
        "pop_pct": 73.2,
        "expected_value": 124.44,
        "max_profit": 170,
        "max_loss": 7830,
        "delta": -0.24,
        "iv_rank": 12.5,
        "oi": 0,
        "volume": 1,
        "bid": 1.2,
        "ask": 2.2,
        "edge_score": 45,
        "reasoning": "Wheel entry on a conviction name",
        "enterprise": {"blocks": ["OI 0 < 50"]},
    })
    assert memo["market_wide_search"] is False
    assert memo["cio_approved"] is False
    assert memo["thesis"]["catalyst"] == "missing"
    assert memo["thesis"]["position_size"] == "not sized"
    assert memo["thesis"]["probability_weighted_expected_return"] == 124.44
    assert memo["contract"]["gamma"] == "missing"
    assert memo["contract"]["iv_percentile"] == "missing"
    assert memo["contract"]["spread_cost"] == 1.0
    names = {row["structure"]: row["status"] for row in memo["structures"]}
    assert names["cash_secured_put"] == "selected"
    assert names["calendar_spread"] == "not_available"
    assert names["diagonal_spread"] == "not_available"
    assert names["collar"] == "not_available"
    assert memo["committee"]["cio"]["review_status"] == "unreviewed"
    assert "OI 0" in memo["committee"]["strongest_opposing_argument"]
    assert "sell" not in memo["committee"]["strongest_opposing_argument"].lower()


def test_watchlist_rows_keep_buy_and_drop_hold(monkeypatch):
    import lib.options_pipeline.universe as uni
    import options_engine as eng

    monkeypatch.setattr(uni, "_fetch_watchlist_buy_rows", lambda: [
        {"symbol": "LMT", "card_rec": "strong_buy", "synth_rec": None},
        {"symbol": "NOC", "card_rec": "hold", "synth_rec": None},
        {"symbol": "BA", "card_rec": None, "synth_rec": "buy"},
        {"symbol": "TOOLONG", "card_rec": "buy", "synth_rec": None},
    ])
    rows = eng._watchlist_buy_conviction_rows()
    assert [r["symbol"] for r in rows] == ["LMT", "BA"]
    assert rows[0]["source"] == "watchlist_buy_strong_buy"
