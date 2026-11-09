"""LQ-20261107-1669: the headline VIX is intraday-fresh or it says STALE.

Under the flat 26 h line, a 03:45 ET overnight print read as FRESH all through Monday's session (10.46 h at 14:15 ET).
Operator order 2026-11-09 14:50 ET: VIX refreshes every 15 min across the whole weekday (overnight, pre-market,
regular, after-hours), and anything older than 30 min is STALE with its time. The continuous span runs from 18:00 ET the
evening before a trading day to 20:00 ET on it; weekends and holidays keep the off-hours line. Synthetic values only.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lib import vix_headline as vh  # noqa: E402

ET = ZoneInfo("America/New_York")


def _rec(as_of: str, source: str = "market_quotes_extended:schwab", session: str = "overnight") -> dict:
    return {"vix": {"value": 20.0, "source": source, "as_of": as_of, "session": session}}


def _at(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=ET)


def _head(as_of: str, now: str, **kw) -> dict:
    return vh.from_record(_rec(as_of, **kw), now=_at(now), stale_after_hours=26.0)


def test_an_overnight_print_is_stale_once_the_session_opens():
    h = _head("2026-11-09T03:45:01-05:00", "2026-11-09T14:20:00")
    assert h["vix_state"] == "STALE"
    assert h["vix_stale"] is True
    assert "predates" in h["vix_reason"] and "09:30" in h["vix_reason"]
    assert h["vix_fresh_rule"] == "continuous_30m"
    assert h["vix"] == 20.0  # the value stays visible, labelled


def test_a_print_inside_30_min_is_fresh_in_every_weekday_session():
    for obs, now in (("2026-11-09T03:20:00-05:00", "2026-11-09T03:45:00"),   # overnight
                     ("2026-11-09T07:50:00-05:00", "2026-11-09T08:15:00"),   # pre-market
                     ("2026-11-09T14:10:00-05:00", "2026-11-09T14:20:00"),   # regular
                     ("2026-11-09T16:14:00-05:00", "2026-11-09T16:40:00"),   # after-hours
                     ("2026-11-08T18:05:00-05:00", "2026-11-08T18:30:00")):  # Sunday evening before Monday
        h = _head(obs, now)
        assert (h["vix_state"], h["vix_fresh_rule"]) == ("FRESH", "continuous_30m"), (obs, now, h)


def test_a_print_past_30_min_is_stale_with_its_time_in_every_weekday_session():
    for obs, now in (("2026-11-09T02:00:00-05:00", "2026-11-09T02:45:00"),
                     ("2026-11-09T05:00:00-05:00", "2026-11-09T07:00:00"),
                     ("2026-11-09T13:30:00-05:00", "2026-11-09T14:20:00"),
                     ("2026-11-09T16:15:00-05:00", "2026-11-09T19:45:00")):
        h = _head(obs, now)
        assert h["vix_state"] == "STALE", (obs, now, h)
        assert h["vix_stale_after_hours"] == 0.5
        hhmm = obs[11:16]
        assert f"last print {hhmm} ET" in h["vix_reason"] or "predates" in h["vix_reason"], h["vix_reason"]


def test_the_31st_minute_is_stale_and_the_30th_is_not():
    assert _head("2026-11-09T11:00:00-05:00", "2026-11-09T11:30:00")["vix_state"] == "FRESH"
    assert _head("2026-11-09T11:00:00-05:00", "2026-11-09T11:31:00")["vix_state"] == "STALE"


def test_weekend_holiday_and_friday_night_keep_the_off_hours_line():
    assert _head("2026-11-06T16:14:00-05:00", "2026-11-07T12:00:00")["vix_fresh_rule"] == "off_hours"
    assert _head("2026-11-06T16:14:00-05:00", "2026-11-06T21:00:00")["vix_state"] == "FRESH"  # Friday 21:00
    # Thanksgiving 2026-11-26 is not a trading day: the prior close stays fresh under 26 h.
    h = _head("2026-11-25T16:14:00-05:00", "2026-11-26T14:00:00")
    assert (h["vix_state"], h["vix_fresh_rule"]) == ("FRESH", "off_hours")
    # ... and the evening before a holiday is not the continuous span either.
    assert _head("2026-11-25T16:14:00-05:00", "2026-11-25T19:00:00")["vix_fresh_rule"] == "continuous_30m"
    assert _head("2026-11-25T16:14:00-05:00", "2026-11-25T21:00:00")["vix_fresh_rule"] == "off_hours"


def test_yesterdays_fred_close_is_stale_in_session():
    rec = {"vix": {"value": 20.0, "source": "fred_economic_series", "value_source": "fred", "as_of": "2026-11-06"}}
    h = vh.from_record(rec, now=_at("2026-11-09T11:00:00"), stale_after_hours=26.0)
    assert h["vix_state"] == "STALE"
    assert h["vix_source"] == "fred_economic_series:VIXCLS"


def test_the_session_line_is_configurable_through_vix_headline():
    def q(sql, params=None):
        if "fred_economic_series" in sql:
            return []
        return [("$VIX", 20.0, "regular", "2026-11-09", _at("2026-11-09T14:12:00"), None, "schwab")]

    cfg = dict(vh.vc.load_config())
    cfg["session_fresh_after_minutes"] = 5
    h = vh.vix_headline(db_query=q, now=_at("2026-11-09T14:20:00"), cfg=cfg)
    assert h["vix_stale_after_hours"] == round(5 / 60, 4)
    assert h["vix_fresh_rule"] == "continuous_5m"
    assert h["vix_state"] == "STALE", h
