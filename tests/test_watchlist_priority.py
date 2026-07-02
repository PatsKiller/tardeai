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