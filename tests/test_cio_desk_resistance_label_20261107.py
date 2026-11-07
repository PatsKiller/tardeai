"""LQ-20261107-83 — the CIO answer must date a close to a session and must not call a broken
level "resistance".

Two defects, both read live in the V answer of 2026-11-07:

1. ``portfolio_repricer`` runs every 15 minutes, all day. At 00:15 ET on **Saturday 2026-11-07**
   it wrote ``ticker_prices`` row ``(V, 2026-11-07, 422.65)`` — Friday's close stamped with a date
   that has no session — and the subject brief then said "close Nov 07". A close may only be
   stamped after the regular close of a NYSE trading day.
2. The re-entry resistance cache had V in state ``ABOVE`` (breakout held since 2026-10-09, 25
   sessions), and ``_subject_takeaway`` rendered it as "price is 11.3% above resistance $375.07",
   which reads as a level overhead when it is in fact a floor already broken through.

Every fixture is synthetic; no database, no provider call.
"""

from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

ET = ZoneInfo("America/New_York")

import lib.cio_operator_desk_loop as desk  # noqa: E402
import portfolio_repricer  # noqa: E402


# --------------------------------------------------------------------------- producer gate
def test_saturday_0015_stamps_fridays_session_not_saturday():
    """The exact run that wrote the phantom row: Sat 2026-11-07 00:15 ET holds Friday's close."""
    assert portfolio_repricer.close_session_date(
        datetime(2026, 11, 7, 0, 15, tzinfo=ET)) == date(2026, 11, 6)


def test_trading_day_before_the_bell_holds_the_previous_close():
    """08:00 ET Friday: the price in hand is Thursday's close, so Thursday is the session."""
    assert portfolio_repricer.close_session_date(
        datetime(2026, 11, 6, 8, 0, tzinfo=ET)) == date(2026, 11, 5)


def test_open_session_writes_no_close():
    """09:30-16:05 ET on a Friday is an intraday mark, not a close."""
    assert portfolio_repricer.close_session_date(datetime(2026, 11, 6, 9, 30, tzinfo=ET)) is None
    assert portfolio_repricer.close_session_date(datetime(2026, 11, 6, 12, 0, tzinfo=ET)) is None
    assert portfolio_repricer.close_session_date(datetime(2026, 11, 6, 16, 0, tzinfo=ET)) is None


def test_trading_day_after_the_close_stamps_today():
    assert portfolio_repricer.close_session_date(
        datetime(2026, 11, 6, 16, 10, tzinfo=ET)) == date(2026, 11, 6)


def test_market_holiday_holds_previous_session():
    """Thanksgiving 2026-11-26: a weekday with no NYSE session — the last close is Wednesday's."""
    assert portfolio_repricer.close_session_date(
        datetime(2026, 11, 26, 16, 10, tzinfo=ET)) == date(2026, 11, 25)


def test_sync_writes_nothing_while_the_session_is_open(monkeypatch):
    """The write itself is gated — old code reached psycopg2 and stamped CURRENT_DATE."""

    class _Boom:
        def connect(self, *a, **k):  # noqa: ANN002, ANN003
            raise AssertionError("ticker_prices write attempted while the session was open")

    monkeypatch.setitem(sys.modules, "psycopg2", _Boom())
    monkeypatch.setattr(portfolio_repricer, "close_session_date", lambda now=None: None)
    portfolio = {"holdings": [{"symbol": "V", "shares": 1, "price": 422.65}]}
    # Must return cleanly without touching the writer.
    assert portfolio_repricer._sync_ticker_prices(portfolio, root=ROOT) is None


# --------------------------------------------------------------------------- reader gate
def _fake_daily_bars(bars):
    class _Mod:
        @staticmethod
        def get_daily_bars(_db, _sym, days=45, **_k):
            return {"bars": bars, "stale": False}

    return _Mod


def test_saturday_bar_cannot_be_the_subject_close(monkeypatch):
    """Old behaviour: the Saturday row won and the brief read "close Nov 07"."""
    mod = _fake_daily_bars([
        {"price_date": "2026-11-05", "close": 418.0},
        {"price_date": "2026-11-06", "close": 422.65},
        {"price_date": "2026-11-07", "close": 422.65},  # phantom Saturday row
    ])
    monkeypatch.setattr("lib.data_broker.daily_bars", mod, raising=False)
    monkeypatch.setitem(sys.modules, "lib.data_broker.daily_bars", mod)
    facts = desk.subject_price_facts(["V"])
    assert facts["V"]["price_date"] == "2026-11-06"
    assert facts["V"]["close"] == 422.65


def test_session_bars_keeps_real_sessions():
    bars = [{"price_date": "2026-11-06", "close": 1.0},
            {"price_date": "2026-11-07", "close": 2.0},
            {"price_date": "2026-11-09", "close": 3.0}]
    assert [b["price_date"] for b in desk._session_bars(bars)] == ["2026-11-06", "2026-11-09"]


# --------------------------------------------------------------------------- answer wording
def _takeaway(resistance, close=422.65):
    row = {"resistance": resistance, "stop": 390.0}
    price = {"close": close, "price_date": "2026-11-06"}
    return desk._subject_takeaway("V", price, row, None, [])


def test_broken_level_is_not_called_resistance():
    """state ABOVE = breakout held; the old text said "above resistance $375.07"."""
    text = _takeaway({"level": 375.07, "state": "ABOVE", "as_of": "2026-11-06"})
    assert "broken resistance $375.07" in text
    assert "above resistance $" not in text


def test_a_level_below_the_price_is_broken_even_without_a_state():
    text = _takeaway(375.07)
    assert "broken resistance $375.07" in text


def test_true_overhead_resistance_still_reads_as_resistance():
    text = _takeaway({"level": 500.0, "state": "BELOW", "as_of": "2026-11-06"})
    assert "below resistance $500.00" in text
    assert "broken" not in text
