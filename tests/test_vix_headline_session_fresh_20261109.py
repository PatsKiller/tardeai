"""LQ-20261107-1669: the headline VIX is intraday-fresh or it says STALE.

The only VIX store is the Schwab off-hours lane (``market_quotes_extended``), which has no regular-session print. Under
the flat 26 h line, a 03:45 ET overnight print read as FRESH all through Monday's session (10.46 h at 14:15 ET). After
today's open a print that predates the open is STALE, and in session an intraday print ages out at
``rth_fresh_after_minutes``. Synthetic values only.
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
    assert h["vix_fresh_rule"] == "rth_intraday"
    assert h["vix"] == 20.0  # the value stays visible, labelled


def test_a_recent_intraday_print_is_fresh_in_session():
    h = _head("2026-11-09T14:10:00-05:00", "2026-11-09T14:20:00", session="regular")
    assert h["vix_state"] == "FRESH"
    assert h["vix_fresh_rule"] == "rth_intraday"


def test_an_intraday_print_past_the_rth_line_is_stale():
    h = _head("2026-11-09T13:30:00-05:00", "2026-11-09T14:20:00", session="regular")
    assert h["vix_state"] == "STALE"
    assert h["vix_fresh_rule"] == "rth_intraday"
    assert h["vix_stale_after_hours"] == round(20 / 60, 4)


def test_premarket_keeps_the_overnight_print_fresh():
    h = _head("2026-11-09T03:45:01-05:00", "2026-11-09T07:00:00")
    assert h["vix_state"] == "FRESH"
    assert h["vix_fresh_rule"] == "off_hours"


def test_after_the_close_a_pre_open_print_stays_stale_and_a_session_print_is_fresh():
    h = _head("2026-11-09T03:45:01-05:00", "2026-11-09T17:30:00")
    assert (h["vix_state"], h["vix_fresh_rule"]) == ("STALE", "session_open")
    assert _head("2026-11-09T16:14:00-05:00", "2026-11-09T17:30:00", session="regular")["vix_state"] == "FRESH"


def test_weekend_and_holiday_keep_the_26h_line():
    assert _head("2026-11-06T16:14:00-05:00", "2026-11-07T12:00:00")["vix_state"] == "FRESH"
    # Thanksgiving 2026-11-26 is not a trading day: the prior close stays fresh under 26 h.
    assert _head("2026-11-25T16:14:00-05:00", "2026-11-26T14:00:00")["vix_state"] == "FRESH"


def test_yesterdays_fred_close_is_stale_in_session():
    rec = {"vix": {"value": 20.0, "source": "fred_economic_series", "value_source": "fred", "as_of": "2026-11-06"}}
    h = vh.from_record(rec, now=_at("2026-11-09T11:00:00"), stale_after_hours=26.0)
    assert h["vix_state"] == "STALE"
    assert h["vix_source"] == "fred_economic_series:VIXCLS"


def test_the_rth_line_is_configurable_through_vix_headline():
    def q(sql, params=None):
        if "fred_economic_series" in sql:
            return []
        return [("$VIX", 20.0, "regular", "2026-11-09", _at("2026-11-09T14:12:00"), None, "schwab")]

    cfg = dict(vh.vc.load_config())
    cfg["rth_fresh_after_minutes"] = 5
    h = vh.vix_headline(db_query=q, now=_at("2026-11-09T14:20:00"), cfg=cfg)
    assert h["vix_stale_after_hours"] == round(5 / 60, 4)
    assert h["vix_state"] == "STALE", h
