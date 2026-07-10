#!/usr/bin/env python3
"""Off-hours watchlist / Hermes top-N prioritization helpers."""
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "lib"))
import watchlist_priority as wp  # noqa: E402

ET = ZoneInfo("America/New_York")


def test_off_hours_weekend():
    sat = datetime(2026, 7, 4, 12, 0, tzinfo=ET)
    assert wp.is_off_hours_et(sat) is True


def test_off_hours_overnight():
    tue_1am = datetime(2026, 7, 7, 1, 0, tzinfo=ET)
    assert wp.is_off_hours_et(tue_1am) is True


def test_market_hours_intraday():
    tue_11am = datetime(2026, 7, 7, 11, 0, tzinfo=ET)
    assert wp.is_off_hours_et(tue_11am) is False


def test_off_hours_top_n_auto_cap(monkeypatch):
    monkeypatch.setattr(wp, "is_off_hours_et", lambda now=None: True)
    assert wp.off_hours_top_n(None) == wp.WATCHLIST_TOP_N


def test_off_hours_top_n_explicit_passthrough(monkeypatch):
    monkeypatch.setattr(wp, "is_off_hours_et", lambda now=None: True)
    assert wp.off_hours_top_n(50) == 50


def test_rank_in_scope():
    assert wp.rank_in_scope(150) is True
    assert wp.rank_in_scope(201) is False
    assert wp.rank_in_scope(None) is False


def test_rank_alert_worthy_suppresses_tail():
    assert wp.rank_alert_worthy(3435, 3475) is False


def test_rank_alert_worthy_top_n():
    assert wp.rank_alert_worthy(180, 220) is True


def test_rank_alert_worthy_crossing_into_top_n():
    assert wp.rank_alert_worthy(195, 250) is True


def test_watchlist_top_n_default_is_200():
    assert wp.WATCHLIST_TOP_N == 200


def test_is_buy_side_rating():
    assert wp.is_buy_side_rating("STRONG_BUY") is True
    assert wp.is_buy_side_rating("START") is True
    assert wp.is_buy_side_rating("HOLD") is False


def test_is_rated_verdict_all_cio_tiers():
    assert wp.is_rated_verdict("STRONG_BUY") is True
    assert wp.is_rated_verdict("ADD_ON_PULLBACK") is True
    assert wp.is_rated_verdict("HOLD") is True
    assert wp.is_rated_verdict("AVOID") is True
    assert wp.is_rated_verdict("TRIM") is True
    assert wp.is_rated_verdict("RESEARCH_MORE") is True
    assert wp.is_rated_verdict("") is False


def test_daily_priority_params_include_hold_and_avoid():
    params = wp.daily_priority_sql_params(holdings=["AAPL"])
    rated = params[2]
    assert "HOLD" in rated
    assert "AVOID" in rated
    assert "ADD_ON_PULLBACK" in rated


def test_rank_in_scope_daily_priority_symbol():
    daily = {"AAPL", "MSFT"}
    assert wp.rank_in_scope(5000, symbol="AAPL", daily_symbols=daily) is True
    assert wp.rank_in_scope(5000, symbol="TAIL", daily_symbols=daily) is False


def test_rank_alert_worthy_daily_priority_symbol():
    daily = {"NVDA"}
    assert wp.rank_alert_worthy(4000, 4100, symbol="NVDA", daily_symbols=daily) is True


def test_sql_daily_priority_exists_has_proposals_and_buy():
    sql = wp.sql_daily_priority_exists("j.symbol")
    assert "paper_trade_proposals" in sql
    assert "watchlist_final_synthesis" in sql