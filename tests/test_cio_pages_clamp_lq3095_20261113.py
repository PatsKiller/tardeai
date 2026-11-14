"""LQ-20261113-3095 (N1 of REVIEW-3091): an off-hours cio.pages row never stays OK/STALE past the next 09:30 ET weekday open."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from scripts.lib.cc_products import cio_pages
from tests import test_cio_pages_off_hours_tier_lq3082_20261113 as t

ET = ZoneInfo("America/New_York")


def et(y, m, d, h, mi, s=0):
    return datetime(y, m, d, h, mi, s, tzinfo=ET)


def _open_after(now):
    # independent oracle: walk forward minute by minute is too slow; walk days
    d = now.astimezone(ET).date()
    while True:
        c = et(d.year, d.month, d.day, 9, 30)
        if d.weekday() < 5 and c > now:
            return c
        d += timedelta(days=1)


CASES = [
    et(2026, 11, 12, 9, 29),          # Thu 09:29
    et(2026, 11, 12, 9, 29, 30),
    et(2026, 11, 12, 18, 0),          # Thu evening
    et(2026, 11, 13, 18, 0),          # Fri evening -> Monday
    et(2026, 11, 13, 16, 15),         # Fri close
    et(2026, 11, 14, 12, 0),          # Saturday
    et(2026, 11, 15, 23, 59),         # Sunday night
    et(2026, 11, 2, 18, 0),           # Mon 2 Nov evening (DST ended 1 Nov)
    et(2026, 3, 6, 18, 0),            # Fri before the 8 Mar spring-forward
]


@pytest.mark.parametrize("now", CASES)
def test_no_limit_extends_past_the_next_open(now):
    lim = cio_pages.limits_for(now)
    deadline = _open_after(now)
    assert now + timedelta(seconds=lim["cadence_s"]) <= deadline          # the next build is due by the open
    assert now + timedelta(seconds=lim["stale_after_s"]) <= deadline + timedelta(seconds=60)
    assert now + timedelta(seconds=lim["hard_expiry_s"]) <= deadline + timedelta(seconds=150)
    assert lim["stale_after_s"] < lim["hard_expiry_s"]                    # REVIEW-3102 R2: a STALE band exists


def test_0929_build_goes_stale_a_minute_after_the_open_and_unknown_150_s_after_it():
    lim = cio_pages.limits_for(et(2026, 11, 12, 9, 29))
    assert (lim["cadence_s"], lim["stale_after_s"], lim["hard_expiry_s"]) == (60, 120, 210)


def test_the_open_grace_covers_one_cadence_plus_cron_lag_and_the_build_timeout_is_not_the_bound():
    assert (cio_pages.OPEN_STALE_S, cio_pages.OPEN_GRACE_S) == (60, 150)
    assert cio_pages.OPEN_GRACE_S >= cio_pages.CADENCE_S and cio_pages.OPEN_STALE_S < cio_pages.OPEN_GRACE_S


def test_friday_evening_is_capped_by_the_off_hours_tier_not_by_monday():
    lim = cio_pages.limits_for(et(2026, 11, 13, 18, 0))
    assert (lim["cadence_s"], lim["stale_after_s"], lim["hard_expiry_s"]) == (3600, 9000, 14400)


def test_market_hours_are_untouched():
    lim = cio_pages.limits_for(et(2026, 11, 12, 9, 30))
    assert (lim["cadence_s"], lim["stale_after_s"], lim["hard_expiry_s"]) == (120, 360, 1800)


def test_stored_row_is_clamped_at_a_0929_build(tmp_path):
    row, hot = t._build(tmp_path, et(2026, 11, 12, 9, 29).astimezone(timezone.utc))
    assert (row["stale_after_s"], row["hard_expiry_s"]) == (120, 210)
    assert 0 < hot.sets[0][2] <= 210


def test_stored_row_friday_evening_not_beyond_monday_open(tmp_path):
    built = et(2026, 11, 13, 21, 0).astimezone(timezone.utc)
    row, _ = t._build(tmp_path, built)
    assert row["built_at"] + timedelta(seconds=row["hard_expiry_s"]) <= _open_after(built) + timedelta(seconds=150)


def test_seconds_to_next_open_over_a_weekend_and_dst():
    assert cio_pages.seconds_to_next_open(et(2026, 11, 13, 18, 0)) == 63.5 * 3600
    # 7 Mar 18:00 EST -> Mon 9 Mar 09:30 EDT: one hour shorter in real seconds
    assert cio_pages.seconds_to_next_open(et(2026, 3, 6, 18, 0)) == (63.5 - 1) * 3600
