"""n8n-maturity B5.1 — DST-safe cron firing (design 02 §3.2 step 1, failure mode F11).

Pure and hermetic: no clock, no I/O; every instant is constructed explicitly.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib import cron_schedule as C  # noqa: E402

NY = ZoneInfo("America/New_York")
UTC = timezone.utc


def ny(*a, fold=0):
    return datetime(*a, tzinfo=NY, fold=fold)


def slots(fires):
    return [f.slot_local for f in fires]


# ---- plain windows ---------------------------------------------------------

def test_plain_window_every_15():
    fires = C.fires_between("*/15 * * * *", ny(2026, 10, 9, 10, 0), ny(2026, 10, 9, 11, 0))
    assert slots(fires) == ["20261009T1015", "20261009T1030", "20261009T1045", "20261009T1100"]
    assert all(f.at.tzinfo is not None for f in fires)
    assert fires[0].at == ny(2026, 10, 9, 10, 15)


def test_start_exclusive_end_inclusive():
    fires = C.fires_between("0 10 * * *", ny(2026, 10, 9, 10, 0), ny(2026, 10, 10, 10, 0))
    assert slots(fires) == ["20261010T1000"]
    assert C.fires_between("0 10 * * *", ny(2026, 10, 9, 9, 59), ny(2026, 10, 9, 10, 0))[0].slot_local == "20261009T1000"
    assert C.fires_between("0 10 * * *", ny(2026, 10, 9, 10, 0), ny(2026, 10, 9, 10, 0)) == []
    assert C.fires_between("0 10 * * *", ny(2026, 10, 9, 11, 0), ny(2026, 10, 9, 10, 0)) == []


def test_naive_inputs_rejected():
    with pytest.raises(ValueError):
        C.fires_between("* * * * *", datetime(2026, 10, 9, 10, 0), ny(2026, 10, 9, 11, 0))
    with pytest.raises(ValueError):
        C.fires_between("* * * * *", ny(2026, 10, 9, 10, 0), datetime(2026, 10, 9, 11, 0))
    with pytest.raises(ValueError):
        C.last_fire_at_or_before("* * * * *", datetime(2026, 10, 9, 10, 0))
    with pytest.raises(ValueError):
        C.slot_local(datetime(2026, 10, 9, 10, 0))


@pytest.mark.parametrize("expr", ["", "* * * *", "61 * * * *", "* 24 * * *", "*/0 * * * *", "a * * * *"])
def test_bad_expr_raises(expr):
    with pytest.raises(ValueError):
        C.fires_between(expr, ny(2026, 10, 9, 10, 0), ny(2026, 10, 9, 11, 0))
    with pytest.raises(ValueError):
        C.is_sub_hourly(expr)


def test_bad_tz_raises():
    with pytest.raises(ValueError):
        C.fires_between("* * * * *", ny(2026, 10, 9, 10, 0), ny(2026, 10, 9, 11, 0), tz="Mars/Olympus")


def test_dom_dow_vixie_or_rule():
    # 1st of the month OR Monday; October 2026: Thu 1st, Mondays 5,12,19,26.
    fires = C.fires_between("0 9 1 * 1", ny(2026, 9, 30, 12, 0), ny(2026, 10, 31, 12, 0))
    assert slots(fires) == ["20261001T0900", "20261005T0900", "20261012T0900",
                            "20261019T0900", "20261026T0900"]
    # Only dow restricted -> AND with '*' dom -> just weekdays.
    wk = C.fires_between("30 16 * * 1-5", ny(2026, 10, 9, 0, 0), ny(2026, 10, 13, 0, 0))
    assert slots(wk) == ["20261009T1630", "20261012T1630"]
    # dow 7 == Sunday.
    sun = C.fires_between("0 8 * * 7", ny(2026, 10, 9, 0, 0), ny(2026, 10, 12, 0, 0))
    assert slots(sun) == ["20261011T0800"]


def test_window_spanning_midnight_and_month_end():
    fires = C.fires_between("0 23,0,1 * * *", ny(2026, 10, 31, 22, 0), ny(2026, 11, 1, 0, 30))
    assert slots(fires) == ["20261031T2300", "20261101T0000"]
    eom = C.fires_between("0 0 1 * *", ny(2026, 12, 31, 12, 0), ny(2027, 1, 1, 0, 0))
    assert slots(eom) == ["20270101T0000"]


def test_utc_inputs_and_slot_is_local():
    # 14:00Z == 10:00 EDT on 2026-10-09.
    fires = C.fires_between("0 10 * * *", datetime(2026, 10, 9, 13, 0, tzinfo=UTC),
                            datetime(2026, 10, 9, 14, 0, tzinfo=UTC))
    assert slots(fires) == ["20261009T1000"]
    assert fires[0].at.astimezone(UTC) == datetime(2026, 10, 9, 14, 0, tzinfo=UTC)
    assert C.slot_local(datetime(2026, 10, 9, 14, 0, tzinfo=UTC)) == "20261009T1000"
    # Other tz respected.
    utc_fires = C.fires_between("0 10 * * *", datetime(2026, 10, 9, 9, 0, tzinfo=UTC),
                                datetime(2026, 10, 9, 10, 0, tzinfo=UTC), tz="UTC")
    assert slots(utc_fires) == ["20261009T1000"]


# ---- spring forward 2026-03-08 (02:00 EST -> 03:00 EDT) ---------------------

SPRING_LO = ny(2026, 3, 7, 12, 0)
SPRING_HI = ny(2026, 3, 8, 12, 0)


def test_spring_gap_minute_fires_once_at_first_valid_instant():
    fires = C.fires_between("30 2 * * *", SPRING_LO, SPRING_HI)
    assert slots(fires) == ["20260308T0300"]
    assert fires[0].at.astimezone(UTC) == datetime(2026, 3, 8, 7, 0, tzinfo=UTC)
    assert fires[0].at.utcoffset() == timedelta(hours=-4)


def test_spring_gap_subhourly_coalesces():
    assert slots(C.fires_between("*/15 2 * * *", SPRING_LO, SPRING_HI)) == ["20260308T0300"]


def test_spring_gap_and_0300_coalesce():
    assert slots(C.fires_between("0 3 * * *", SPRING_LO, SPRING_HI)) == ["20260308T0300"]
    assert slots(C.fires_between("30 2 * * *", SPRING_LO, SPRING_HI)) == ["20260308T0300"]
    both = C.fires_between("0,30 2,3 * * *", SPRING_LO, SPRING_HI)
    assert slots(both) == ["20260308T0300", "20260308T0330"]


def test_spring_every_minute_has_no_gap_slots():
    fires = C.fires_between("* * * * *", ny(2026, 3, 8, 1, 0), ny(2026, 3, 8, 4, 0))
    keys = slots(fires)
    assert not any(k.startswith("20260308T02") for k in keys)
    assert len(keys) == len(set(keys)) == 120  # 01:01..01:59, 03:00..04:00
    assert keys[59] == "20260308T0300"


# ---- fall back 2026-11-01 (02:00 EDT -> 01:00 EST) --------------------------

FALL_LO = ny(2026, 10, 31, 12, 0)
FALL_HI = ny(2026, 11, 1, 12, 0)


def test_fall_fold_fires_once_on_fold0():
    fires = C.fires_between("30 1 * * *", FALL_LO, FALL_HI)
    assert slots(fires) == ["20261101T0130"]
    assert fires[0].at.astimezone(UTC) == datetime(2026, 11, 1, 5, 30, tzinfo=UTC)  # EDT


def test_fall_hourly_across_fold():
    fires = C.fires_between("0 * * * *", ny(2026, 11, 1, 0, 30), ny(2026, 11, 1, 3, 0))
    assert slots(fires) == ["20261101T0100", "20261101T0200", "20261101T0300"]


def test_fall_subhourly_two_not_four():
    assert slots(C.fires_between("*/30 1 * * *", FALL_LO, FALL_HI)) == ["20261101T0100", "20261101T0130"]


def test_fall_window_inside_fold1_never_fires():
    # Window entirely within the second (EST) 01:xx hour: fold-1 minutes never fire.
    lo = ny(2026, 11, 1, 1, 0, fold=1)
    hi = ny(2026, 11, 1, 1, 59, fold=1)
    assert lo.astimezone(UTC) == datetime(2026, 11, 1, 6, 0, tzinfo=UTC)
    assert C.fires_between("*/10 * * * *", lo, hi) == []
    # A window ending inside fold 1 still includes the fold-0 fires after the naive end.
    got = C.fires_between("40 1 * * *", ny(2026, 11, 1, 0, 0), ny(2026, 11, 1, 1, 10, fold=1))
    assert slots(got) == ["20261101T0140"]


# ---- is_sub_hourly ----------------------------------------------------------

@pytest.mark.parametrize("expr,expected", [
    ("*/15 * * * *", True), ("0,30 9 * * *", True), ("* 3 * * *", True),
    ("0 * * * *", False), ("30 9 * * 1-5", False), ("5 */2 * * *", False),
])
def test_is_sub_hourly(expr, expected):
    assert C.is_sub_hourly(expr) is expected


# ---- last_fire_at_or_before -------------------------------------------------

def test_last_fire_inclusive_and_basic():
    f = C.last_fire_at_or_before("0 10 * * *", ny(2026, 10, 9, 10, 0))
    assert f.slot_local == "20261009T1000"
    f = C.last_fire_at_or_before("0 10 * * *", ny(2026, 10, 9, 9, 59))
    assert f.slot_local == "20261008T1000"


def test_last_fire_across_dst_boundaries():
    f = C.last_fire_at_or_before("30 2 * * *", ny(2026, 3, 8, 3, 30))
    assert f.slot_local == "20260308T0300"
    f = C.last_fire_at_or_before("30 2 * * *", ny(2026, 3, 8, 1, 0))
    assert f.slot_local == "20260307T0230"
    # In the EST repeat of 01:xx the last fire is the EDT 01:30 (fold 0), not a second one.
    f = C.last_fire_at_or_before("30 1 * * *", ny(2026, 11, 1, 1, 45, fold=1))
    assert f.slot_local == "20261101T0130"
    assert f.at.astimezone(UTC) == datetime(2026, 11, 1, 5, 30, tzinfo=UTC)


def test_last_fire_none_beyond_lookback():
    # Feb 29 only: nothing within 8 days of 2026-10-09.
    assert C.last_fire_at_or_before("0 0 29 2 *", ny(2026, 10, 9, 0, 0)) is None
    # Weekly lane is found within the default lookback.
    assert C.last_fire_at_or_before("0 6 * * 0", ny(2026, 10, 9, 0, 0)).slot_local == "20261004T0600"


# ---- existing API unchanged -------------------------------------------------

def test_next_run_unchanged():
    assert C.next_run("*/15 * * * *", datetime(2026, 10, 9, 10, 7)) == datetime(2026, 10, 9, 10, 15)
    assert C.next_run_any(["bad", "0 11 * * *"], datetime(2026, 10, 9, 10, 7)) == datetime(2026, 10, 9, 11, 0)
