"""LQ-20261107-1253 amendments 3/4 + 1260/1261 — the Last-updated strip.  Synthetic clocks only."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from lib import since_close_card as card  # noqa: E402
from lib import since_close_stamp as st  # noqa: E402

ET = ZoneInfo("America/New_York")


def et(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=ET)


SUN = et(2026, 11, 8, 18, 0)  # Sunday evening; last close Fri 11-06
TUE = et(2026, 11, 10, 11, 0)  # trading day, session open


def _stamp(now, clocks):
    return st.build_stamp(now=now, window=card.window(now), clocks=clocks)


def _chip(s, key):
    return next(c for c in s["sources"] if c["key"] == key)


def test_chip_carries_the_source_clock_not_the_build_time():
    s = _stamp(SUN, {"stops": et(2026, 11, 6, 20, 55), "news": SUN - timedelta(minutes=20)})
    stops = _chip(s, "stops")
    assert stops["at_text"] == "Fri 11-06 · 8:55 PM ET"
    assert stops["warn"] and stops["warn_text"] == "⚠ 1 day old"
    assert s["updated_text"] == "Sun 11-08 · 6:00 PM ET"
    assert _chip(s, "news")["warn"] is False


def test_older_than_24h_is_amber_and_counts_days():
    s = _stamp(TUE, {"positions": TUE - timedelta(days=3, hours=2)})
    c = _chip(s, "positions")
    assert c["warn"] and c["warn_text"] == "⚠ 3 days old"


def test_before_the_last_close_is_amber_even_under_24h():
    # Mon 15:00 snapshot read Tue 11:00 is 20 h old, but Mon's 16:00 close is later -> amber
    s = _stamp(TUE, {"news": et(2026, 11, 9, 15, 0)})
    c = _chip(s, "news")
    assert c["warn"] and c["warn_text"] == "⚠ 20 h old"


def test_prices_when_closed_read_the_close_not_amber():
    s = _stamp(SUN, {"prices": et(2026, 11, 6, 16, 5)})
    c = _chip(s, "prices")
    assert c["age_text"] == "Fri close" and c["warn"] is False
    assert "market closed" in c["note"]


def test_prices_amber_when_no_quote_from_the_last_session_day():
    s = _stamp(SUN, {"prices": et(2026, 11, 5, 16, 5)})
    assert _chip(s, "prices")["warn"] is True


def test_missing_source_is_a_stated_gap():
    s = _stamp(TUE, {})
    c = _chip(s, "market_risk")
    assert c["warn"] and c["warn_text"] == "⚠ not available" and c["at"] is None
    assert s["any_warn"] is True


def test_cio_clock_reads_generated_at():
    assert st.cio_clock({"generated_at": "2026-11-08T22:00:00Z"}) == "2026-11-08T22:00:00Z"
    assert st.cio_clock(None) is None
    assert st.cio_clock({}) is None


def test_next_refresh_trading_day_slots():
    assert st.next_refresh(et(2026, 11, 10, 5, 0)) == et(2026, 11, 10, 6, 0)
    assert st.next_refresh(et(2026, 11, 10, 6, 1)) == et(2026, 11, 10, 8, 30)
    assert st.next_refresh(et(2026, 11, 10, 9, 31)) == et(2026, 11, 10, 9, 45)
    assert st.next_refresh(et(2026, 11, 10, 16, 20)) == et(2026, 11, 10, 18, 0)
    assert st.next_refresh(et(2026, 11, 10, 23, 30)) == et(2026, 11, 11, 0, 0)


def test_next_refresh_weekend_is_two_hourly():
    assert st.next_refresh(et(2026, 11, 8, 17, 51)) == et(2026, 11, 8, 18, 0)
    assert st.next_refresh(et(2026, 11, 8, 18, 1)) == et(2026, 11, 8, 20, 0)


def test_schedule_lists_the_nine_fixed_slots_and_four_cio_slots():
    sch = _stamp(TUE, {})["schedule"]
    assert sch["trading_day"] is True
    assert [f["text"] for f in sch["fixed"]] == ["6:00 AM", "8:30 AM", "9:15 AM", "9:45 AM", "10:30 AM", "12:00 PM", "2:00 PM", "3:30 PM", "4:15 PM"]
    assert len(sch["cio"]) == 4 and sch["grace_min"] == 30 and sch["check_every_min"] == 15
    wk = _stamp(SUN, {})["schedule"]
    assert wk["trading_day"] is False and len(wk["fixed"]) == 12 and wk["cio"] == []


def test_missed_fixed_slot_needs_30_min_grace_market_hours_and_no_build_since():
    built_0830 = et(2026, 11, 10, 8, 31)
    assert st.missed_slot(et(2026, 11, 10, 10, 10), built_0830) is None  # 9:45 is 25 min ago, inside grace
    assert st.missed_slot(et(2026, 11, 10, 10, 20), built_0830) == et(2026, 11, 10, 9, 45)  # 35 min, nothing built since
    assert st.missed_slot(et(2026, 11, 10, 10, 20), et(2026, 11, 10, 9, 46)) is None  # built after the slot
    assert st.missed_slot(et(2026, 11, 10, 8, 40), et(2026, 11, 10, 6, 1)) is None  # 8:30 is before market hours
    assert st.missed_slot(et(2026, 11, 8, 12, 0), et(2026, 11, 8, 2, 0)) is None  # weekend


def test_fetch_clocks_isolates_a_failing_read():
    class Cur:
        def __init__(self, c):
            self.c = c

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, sql):
            if "stop_last_known" in sql:
                raise RuntimeError("no such table")
            self.sql = sql

        def fetchone(self):
            return (datetime(2026, 11, 8, 17, 30, tzinfo=ET),)

    class Conn:
        rolled = 0

        def cursor(self):
            return Cur(self)

        def rollback(self):
            Conn.rolled += 1

    out = st.fetch_clocks(Conn())
    assert out["stops"] is None and out["news"] is not None and Conn.rolled == 1


def test_snapshot_carries_the_stamp_with_real_clocks():
    tick = {"_meta": {"generated_at": "2026-11-08T22:00:00Z"}, "tickers": {"AAA": {"held": True, "quote": {"price": 10.0, "change_pct": 1.0}}}}
    snap = card.build_snapshot(
        now=SUN, ticker_snapshot=tick, articles=[], futures=None, llm=None,
        source_clocks={"stops": et(2026, 11, 6, 20, 55)}, cio_brief={"generated_at": "2026-11-08T21:00:00Z", "stop_advice": []},
    )
    s = snap["stamp"]
    assert _chip(s, "cio_brief")["at"] == "2026-11-08T21:00:00Z"
    assert _chip(s, "stops")["warn"] is True
    assert snap["cio_brief"]["stop_advice"] == []
