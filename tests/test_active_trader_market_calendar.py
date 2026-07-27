"""Stage 5 harness — exchange-calendar tests (deterministic, no network)."""
import datetime as dt
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from active_trader import market_calendar as cal  # noqa: E402


def _c():
    return cal.NyseCalendar()


def test_normal_weekday_qualifies():
    s = _c().session_for_date(dt.date(2026, 7, 24))       # Friday
    assert s.is_session and s.qualifies_for_observation() and not s.is_early_close


def test_weekend_not_a_session():
    assert not _c().session_for_date(dt.date(2026, 7, 25)).is_session   # Saturday
    assert not _c().is_session(dt.date(2026, 7, 26))                    # Sunday


def test_full_holidays():
    c = _c()
    # New Year's, MLK (Mon), Good Friday, Juneteenth, Independence(observed 7/3), Christmas
    for d in (dt.date(2026, 1, 1), dt.date(2026, 1, 19), dt.date(2026, 4, 3),
              dt.date(2026, 6, 19), dt.date(2026, 7, 3), dt.date(2026, 12, 25)):
        assert not c.is_session(d), d


def test_no_weekday_only_inference():
    # MLK day 2026-01-19 is a Monday but NOT a session — proves we don't assume weekday==market
    assert dt.date(2026, 1, 19).weekday() == 0
    assert not _c().is_session(dt.date(2026, 1, 19))


def test_early_close_days_labeled_and_still_qualify():
    c = _c()
    for d in (dt.date(2026, 11, 27), dt.date(2026, 12, 24), dt.date(2027, 11, 26)):
        s = c.session_for_date(d)
        assert s.is_session and s.is_early_close
        # early close is 13:00 > 10:05 required completion -> still qualifies
        assert s.qualifies_for_observation()
        assert dt.datetime.fromisoformat(s.close_time).hour == 13


def test_dst_awareness_offsets_differ():
    c = _c()
    summer = dt.datetime.fromisoformat(c.session_for_date(dt.date(2026, 7, 24)).open_time)
    winter = dt.datetime.fromisoformat(c.session_for_date(dt.date(2026, 1, 2)).open_time)
    assert summer.utcoffset() == dt.timedelta(hours=-4)   # EDT
    assert winter.utcoffset() == dt.timedelta(hours=-5)   # EST
    assert summer.hour == 9 and summer.minute == 30       # tz-aware 09:30 local both


def test_next_session_and_next_observation_session():
    c = _c()
    # Friday 2026-07-24 -> next session is Monday 2026-07-27 (skips weekend)
    nxt = c.next_session(dt.datetime(2026, 7, 24, 12, 0, tzinfo=cal.ZoneInfo(cal.MARKET_TZ)))
    assert nxt.local_date == "2026-07-27"
    obs = c.next_observation_session(dt.datetime(2026, 7, 3, 12, 0, tzinfo=cal.ZoneInfo(cal.MARKET_TZ)))
    assert obs.qualifies_for_observation()


def test_unsupported_year_fails_closed():
    c = _c()
    with pytest.raises(cal.UnsupportedYearError):
        c.session_for_date(dt.date(2025, 6, 1))
    with pytest.raises(cal.UnsupportedYearError):
        c.is_session(dt.date(2028, 6, 1))


def test_calendar_metadata_present():
    s = _c().session_for_date(dt.date(2027, 3, 1))
    assert s.calendar_version == cal.CALENDAR_VERSION
    assert s.source and s.source_retrieved_at and s.supported_year
