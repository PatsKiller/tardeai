"""LQ-20261107-1669 + LQ-20261107-2600: the headline VIX is session-fresh or it says STALE.

Under the flat 26 h line, a 03:45 ET overnight print read as FRESH all through Monday's session (10.46 h at 14:15 ET).
Operator order 2026-11-09 14:50 ET set the minute line for the trading day. LQ-20261107-2600 then measured what the
source can actually do: market_quotes:schwab:$VIX holds 15-min prints 03:15..16:15 ET on 11-11 and 11-12 and NOTHING
between 16:15 and 03:15, while the writer lane fired every 15 min all evening (105/105 RUN_DONE) and its 18:00
receipt reads the 16:15 print and names ``cboe_not_calculating``. The wall-clock line therefore flagged the source's
normal evening as a stall.

The rule now follows the configured printing window (config/market_regime_vix_complex.yaml): inside
[start_et, official close + settlement offset) the minute line applies; outside it the newest print any source could
carry is the last settlement, so reaching it is current-for-session and predating it is STALE (a missed settle
write). The settlement rule's own cases live in test_vix_headline_settled_lq2600_20261112.py. Synthetic values only.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lib import vix_headline as vh  # noqa: E402
from lib.market_regime import vix_complex as vc  # noqa: E402

ET = ZoneInfo("America/New_York")
# The shipped window, not an hour in the module: a config change is what the rule must follow.
WINDOW = vh.parse_printing_window(vc.load_config()["printing_window"])


def _rec(as_of: str, source: str = "market_quotes_extended:schwab", session: str = "overnight") -> dict:
    return {"vix": {"value": 20.0, "source": source, "as_of": as_of, "session": session}}


def _at(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=ET)


def _head(as_of: str, now: str, **kw) -> dict:
    return vh.from_record(_rec(as_of, **kw), now=_at(now), stale_after_hours=26.0, printing_window=WINDOW)


def test_an_overnight_print_is_stale_once_the_session_opens():
    h = _head("2026-11-09T03:45:01-05:00", "2026-11-09T14:20:00")
    assert h["vix_state"] == "STALE"
    assert h["vix_stale"] is True
    assert "predates" in h["vix_reason"] and "09:30" in h["vix_reason"]
    assert h["vix_fresh_rule"] == "continuous_30m"
    assert h["vix"] == 20.0  # the value stays visible, labelled


def test_a_print_inside_30_min_is_fresh_in_every_printing_session():
    for obs, now in (("2026-11-09T03:20:00-05:00", "2026-11-09T03:45:00"),   # first overnight prints
                     ("2026-11-09T07:50:00-05:00", "2026-11-09T08:15:00"),   # pre-market
                     ("2026-11-09T14:10:00-05:00", "2026-11-09T14:20:00"),   # regular
                     ("2026-11-09T15:50:00-05:00", "2026-11-09T16:10:00")):  # into the settlement
        h = _head(obs, now)
        assert (h["vix_state"], h["vix_fresh_rule"]) == ("FRESH", "continuous_30m"), (obs, now, h)


def test_a_print_past_30_min_is_stale_with_its_time_while_the_source_prints():
    for obs, now in (("2026-11-09T05:00:00-05:00", "2026-11-09T07:00:00"),
                     ("2026-11-09T13:30:00-05:00", "2026-11-09T14:20:00")):
        h = _head(obs, now)
        assert h["vix_state"] == "STALE", (obs, now, h)
        assert h["vix_stale_after_hours"] == 0.5
        hhmm = obs[11:16]
        assert f"last print {hhmm} ET" in h["vix_reason"], h["vix_reason"]


def test_the_31st_minute_is_stale_and_the_30th_is_not():
    assert _head("2026-11-09T11:00:00-05:00", "2026-11-09T11:30:00")["vix_state"] == "FRESH"
    assert _head("2026-11-09T11:00:00-05:00", "2026-11-09T11:31:00")["vix_state"] == "STALE"


def test_the_settlement_print_is_fresh_after_the_close():
    # LQ-2600: 16:15 is Cboe's settlement and the evening has no newer print to have.
    h = _head("2026-11-09T16:15:01-05:00", "2026-11-09T19:45:00")
    assert (h["vix_state"], h["vix_fresh_rule"]) == ("FRESH", "settled")
    assert h["vix_stale_after_hours"] is None  # the minute line cannot judge a settled print
    assert h["vix_expected_print"] == "2026-11-09T16:15:00-05:00"
    # A pre-window print after a settlement is current too: nothing prints before 03:15.
    h = _head("2026-11-09T02:00:00-05:00", "2026-11-09T02:45:00")
    assert (h["vix_state"], h["vix_fresh_rule"]) == ("FRESH", "settled")


def test_a_missed_settlement_stays_stale_after_the_close():
    h = _head("2026-11-09T16:00:00-05:00", "2026-11-09T19:45:00")
    assert h["vix_state"] == "STALE"
    assert "predates the 11-09 16:15 ET settlement; no print since" in h["vix_reason"], h["vix_reason"]
    # A 16:14 print is not the settlement either: the last print is 1 min short of it.
    assert _head("2026-11-09T16:14:00-05:00", "2026-11-09T16:40:00")["vix_state"] == "STALE"
    # Weekend: Friday's 16:00 print is still not Friday's settlement.
    h = _head("2026-11-06T16:00:00-05:00", "2026-11-07T12:00:00")
    assert h["vix_state"] == "STALE" and "11-06 16:15 ET settlement" in h["vix_reason"], h["vix_reason"]


def test_weekend_and_holiday_hold_the_last_settlement():
    h = _head("2026-11-06T16:15:01-05:00", "2026-11-07T12:00:00")  # Saturday noon
    assert (h["vix_state"], h["vix_fresh_rule"], h["vix_expected_print"]) == (
        "FRESH", "settled", "2026-11-06T16:15:00-05:00")
    # Sunday evening before Monday: still Friday's settlement, current-for-session.
    h = _head("2026-11-08T18:05:00-05:00", "2026-11-08T18:30:00")
    assert (h["vix_state"], h["vix_fresh_rule"]) == ("FRESH", "settled"), h
    # Thanksgiving 2026-11-26 is not a trading day: Wednesday's settlement is the newest print.
    h = _head("2026-11-25T16:15:01-05:00", "2026-11-26T14:00:00")
    assert (h["vix_state"], h["vix_fresh_rule"]) == ("FRESH", "settled")


def test_yesterdays_fred_close_is_stale_in_session():
    rec = {"vix": {"value": 20.0, "source": "fred_economic_series", "value_source": "fred", "as_of": "2026-11-06"}}
    h = vh.from_record(rec, now=_at("2026-11-09T11:00:00"), stale_after_hours=26.0, printing_window=WINDOW)
    assert h["vix_state"] == "STALE"
    assert h["vix_source"] == "fred_economic_series:VIXCLS"


def test_the_session_line_is_configurable_through_vix_headline():
    def q(sql, params=None):
        if "fred_economic_series" in sql:
            return []
        return [("$VIX", 20.0, "regular", "2026-11-09", _at("2026-11-09T14:12:00"), None, "schwab")]

    cfg = dict(vc.load_config())
    cfg["session_fresh_after_minutes"] = 5
    h = vh.vix_headline(db_query=q, now=_at("2026-11-09T14:20:00"), cfg=cfg)
    assert h["vix_stale_after_hours"] == round(5 / 60, 4)
    assert h["vix_fresh_rule"] == "continuous_5m"
    assert h["vix_state"] == "STALE", h


def test_the_printing_window_is_config_and_a_missing_one_is_named_never_guessed():
    def q(sql, params=None):
        return [] if "fred_economic_series" in sql else [
            ("$VIX", 20.0, "regular", "2026-11-09", _at("2026-11-09T02:35:00"), None, "schwab")]

    cfg = dict(vc.load_config())
    cfg["printing_window"] = {"start_et": "02:30", "settlement_after_close_minutes": 15}
    h = vh.vix_headline(db_query=q, now=_at("2026-11-09T02:45:00"), cfg=cfg)
    assert (h["vix_state"], h["vix_fresh_rule"]) == ("FRESH", "continuous_30m"), h

    cfg.pop("printing_window")
    h = vh.vix_headline(db_query=q, now=_at("2026-11-09T02:45:00"), cfg=cfg)
    assert (h["vix"], h["vix_state"]) == (None, "UNAVAILABLE")
    assert h["vix_reason"].startswith("vix_complex config:"), h["vix_reason"]
