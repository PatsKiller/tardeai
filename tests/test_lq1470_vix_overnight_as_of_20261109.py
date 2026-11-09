"""ANCHOR: LQ1470_VIX_OVERNIGHT_AS_OF_20261109. LQ-20261107-1470.

An overnight $VIX leg observed at 04:00 ET must not be stamped 16:00 ET. That future close made the
Home volatility card UNKNOWN before the open ("VIX stale (newest 2026-11-09T21:00Z)" at 04:25 ET).
A real daily close still uses the 16:00 ET close instant. Staleness limits are unchanged. No database.
"""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from scripts.lib.market_risk import reader as rd
from scripts.lib.market_risk.policy import load_policy
from scripts.lib.market_risk.scoring import staleness

ET = ZoneInfo("America/New_York")


def et(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=ET)


def _at(raw: str) -> datetime:
    return datetime.fromisoformat(raw)


class _Reader:
    def __init__(self, leg):
        self._leg = leg

    def vix_complex(self, *, end):
        return {"vix": self._leg}


def _rows(leg, end):
    reader = rd.PgReader(lambda: None)
    reader.vix_complex = _Reader(leg).vix_complex
    return reader._vix_complex_bar_rows(end=end)


def test_an_overnight_print_at_0400_et_is_not_stamped_at_the_close():
    end = et(2026, 11, 9, 4, 25)
    observed = et(2026, 11, 9, 4, 0)
    rows = _rows(
        {
            "value": 18.4,
            "source": "market_quotes_extended:schwab",
            "value_source": "schwab",
            "as_of": observed.isoformat(),
            "fresh": True,
            "session": "overnight",
        },
        end,
    )
    assert len(rows) == 1
    stamped = _at(rows[0]["as_of"])
    assert stamped == observed
    assert stamped <= end
    assert stamped != rd._close_instant(date(2026, 11, 9))
    assert rows[0]["symbol"] == "^VIX"
    assert rows[0]["close"] == 18.4


def test_a_pre_close_print_without_a_session_keeps_its_own_time():
    end = et(2026, 11, 9, 4, 25)
    observed = et(2026, 11, 9, 4, 0)
    rows = _rows(
        {
            "value": 18.1,
            "source": "market_quotes_extended:schwab",
            "value_source": "schwab",
            "as_of": observed.isoformat(),
            "fresh": True,
        },
        end,
    )
    assert len(rows) == 1
    assert _at(rows[0]["as_of"]) == observed


def test_a_fred_daily_close_keeps_the_close_instant():
    end = et(2026, 11, 9, 4, 25)
    rows = _rows(
        {
            "value": 17.2,
            "source": "fred_economic_series",
            "value_source": "fred",
            "as_of": "2026-11-06",
            "fresh": True,
            "session": "close",
        },
        end,
    )
    assert len(rows) == 1
    assert _at(rows[0]["as_of"]) == rd._close_instant(date(2026, 11, 6))
    assert rows[0]["date"] == "2026-11-06"


def test_a_timestamp_at_the_close_keeps_the_close_instant():
    end = et(2026, 11, 9, 4, 25)
    close = et(2026, 11, 6, 16, 0)
    rows = _rows(
        {
            "value": 17.4,
            "source": "market_quotes_extended:schwab",
            "value_source": "schwab",
            "as_of": close.isoformat(),
            "fresh": True,
            "session": "overnight",
            "carried_from": "2026-11-06",
        },
        end,
    )
    assert len(rows) == 1
    assert _at(rows[0]["as_of"]) == rd._close_instant(date(2026, 11, 6))


def test_a_close_that_has_not_happened_is_not_returned_as_fresh():
    end = et(2026, 11, 9, 4, 25)
    rows = _rows(
        {
            "value": 19.0,
            "source": "fred_economic_series",
            "value_source": "fred",
            "as_of": "2026-11-09",
            "fresh": True,
            "session": "close",
        },
        end,
    )
    assert rows == [] or _at(rows[0]["as_of"]) > end


def test_an_overnight_print_after_the_read_is_not_clamped_to_end():
    end = et(2026, 11, 9, 4, 25)
    rows = _rows(
        {
            "value": 18.9,
            "source": "market_quotes_extended:schwab",
            "value_source": "schwab",
            "as_of": et(2026, 11, 9, 5, 0).isoformat(),
            "fresh": True,
            "session": "overnight",
        },
        end,
    )
    assert rows == [] or _at(rows[0]["as_of"]) > end


def test_an_old_overnight_print_is_still_stale_at_the_policy_limit():
    policy = load_policy()
    hours = float(policy["volatility"]["stale_after_hours"])
    assert hours == 32
    _age, why = staleness(et(2026, 11, 2, 4, 0), et(2026, 11, 9, 4, 25), policy["decay"], hours)
    assert why is not None
