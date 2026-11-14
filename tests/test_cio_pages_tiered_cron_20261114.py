"""cio-pages-product's tiered dispatch.cron keeps every served cio.pages row inside its own limits (release 3).

Lead ruling 2026-11-14T07:18:50Z (TIERED). ``cio_pages.limits_for`` has two tiers: market hours (09:30-16:15 ET
Mon-Fri) are 120/360/1800 s; off-hours are 3600/9000/14400 s, capped at the next open + 60/150 s. A flat */30
breaks the market contract (STALE 6 min after each build, hard expiry equal to the cadence), so the lane fires */2 in
market hours and */30 outside them.

The walk: one synthetic week (Mon 2026-11-16 00:00 to Sun 2026-11-22 23:59 ET, no DST change), minute by minute.
Fires come from the dispatcher's own DST-safe ``cron_schedule.fires_between``. A fire lands as a row ``lag``
seconds later, with its limits frozen by ``limits_for(built_at)``, as the builder does. At the start and at the
last second of every minute, the newest landed row must:
  * never be hard-expired (so the page is never UNKNOWN or grey), and
  * in market minutes, be at most 360 s old (never STALE). The one exception is the designed open band
    (REVIEW-3102 R2): the pre-open row stays valid on its own capped limits until the first market build lands.

Holidays: there is no exchange-holiday calendar. ``limits_for`` treats a weekday holiday as market hours, so the
lane builds */2 that day. That is accepted (the cost of a busy day, never a grey page) and is pinned below.
"""
from __future__ import annotations

import bisect
import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from scripts.lib import cron_schedule
from scripts.lib.cc_products import cio_pages
from scripts.lib.cc_products import product_builder as pb

ROOT = Path(__file__).resolve().parents[1]
ET = ZoneInfo("America/New_York")
LANE_ID = "cio-pages-product"
WEEK_START = datetime(2026, 11, 16, 0, 0, tzinfo=ET)  # a Monday; no DST transition in this week
WEEK_END = WEEK_START + timedelta(days=7)
#: Seconds from the cron minute to the stored row: cron lag + build. Builds measured 17-35 s on 2026-11-14.
LAGS_S = (30, 95)
MARKET_STALE_S = 360


def _lane() -> dict:
    doc = json.loads((ROOT / "config" / "lane_registry.json").read_text())
    lanes = doc["lanes"] if isinstance(doc, dict) and "lanes" in doc else doc
    rows = [r for r in (lanes if isinstance(lanes, list) else lanes.values()) if r.get("lane_id") == LANE_ID]
    assert len(rows) == 1, rows
    return rows[0]


def _crons() -> list[str]:
    return list(_lane()["dispatch"]["cron"])


def _rows(crons: list[str], lag_s: int) -> list[tuple[datetime, dict]]:
    start = WEEK_START - timedelta(days=1)  # Sunday's fires seed Monday 00:00
    fires = sorted({f.at for e in crons for f in cron_schedule.fires_between(e, start, WEEK_END, "America/New_York")})
    out = []
    for at in fires:
        built = at + timedelta(seconds=lag_s)
        out.append((built, cio_pages.limits_for(built)))
    return out


def _violations(crons: list[str], lag_s: int) -> list[str]:
    rows = _rows(crons, lag_s)
    built = [b for b, _ in rows]
    bad: list[str] = []
    t = WEEK_START
    while t < WEEK_END:
        for probe in (t, t + timedelta(seconds=59)):
            i = bisect.bisect_right(built, probe) - 1
            if i < 0:
                bad.append(f"{probe:%a %H:%M:%S} no row")
                continue
            b, lim = rows[i]
            age = (probe - b).total_seconds()
            if age >= lim["hard_expiry_s"]:
                bad.append(f"{probe:%a %H:%M:%S} hard-expired (age {age:.0f}s >= {lim['hard_expiry_s']}s)")
            elif pb.is_market_hours(probe) and age > MARKET_STALE_S:
                pre_open_band = not pb.is_market_hours(b) and age < lim["hard_expiry_s"] \
                    and probe.astimezone(ET).hour == 9 and probe.astimezone(ET).minute < 33
                if not pre_open_band:
                    bad.append(f"{probe:%a %H:%M:%S} market STALE (age {age:.0f}s > {MARKET_STALE_S}s)")
        t += timedelta(minutes=1)
    return bad


@pytest.mark.parametrize("lag_s", LAGS_S)
def test_registry_tiered_cron_keeps_every_minute_of_the_week_inside_limits(lag_s):
    bad = _violations(_crons(), lag_s)
    assert bad == [], f"{len(bad)} violations, first: {bad[:5]}"


def test_mutant_flat_every_30_minutes_fails_the_walk():
    bad = _violations(["*/30 * * * *"], 30)
    assert any("market STALE" in v for v in bad), bad[:5]


def test_mutant_without_the_post_close_restamp_fails_the_walk():
    crons = [c for c in _crons() if c != "16,30 16 * * 1-5"]
    assert len(crons) == len(_crons()) - 1
    bad = _violations(crons, 30)
    assert any("hard-expired" in v for v in bad), bad[:5]


def test_mutant_without_the_market_close_tail_fails_the_walk():
    crons = [c for c in _crons() if c != "0-14/2 16 * * 1-5"]
    assert len(crons) == len(_crons()) - 1
    bad = _violations(crons, 30)
    assert any("16:0" in v and "market STALE" in v for v in bad), bad[:5]


def test_market_and_off_hours_tiers_are_the_ones_the_walk_assumes():
    market = cio_pages.limits_for(datetime(2026, 11, 17, 11, 0, tzinfo=ET))
    assert (market["cadence_s"], market["stale_after_s"], market["hard_expiry_s"]) == (120, 360, 1800)
    sat = cio_pages.limits_for(datetime(2026, 11, 21, 12, 0, tzinfo=ET))
    assert (sat["cadence_s"], sat["stale_after_s"], sat["hard_expiry_s"]) == (3600, 9000, 14400)


def test_weekday_holiday_is_treated_as_market_hours_so_the_lane_builds_every_2_minutes():
    thanksgiving_noon = datetime(2026, 11, 26, 12, 0, tzinfo=ET)
    assert pb.is_market_hours(thanksgiving_noon)
    lim = cio_pages.limits_for(thanksgiving_noon)
    assert (lim["stale_after_s"], lim["hard_expiry_s"]) == (360, 1800)
    fires = [f for e in _crons() for f in cron_schedule.fires_between(
        e, thanksgiving_noon - timedelta(minutes=10), thanksgiving_noon, "America/New_York")]
    assert len(fires) == 5


def test_scheduler_cadence_mirrors_the_first_dispatch_cron_and_schedules_declare_every_tier():
    lane = _lane()
    assert lane["scheduler"]["cadence"] == lane["dispatch"]["cron"][0]
    assert lane["dispatch"]["mode"] == "live"
    assert lane["scheduler"]["schedules"] == lane["dispatch"]["cron"]
    assert lane["expected_cadence_hours"] == 0.5
    note = lane["note"]
    for text in ("120 s", "360 s", "1800 s", "3600 s", "9000 s", "14400 s"):
        assert text in note, text


def _margin_violations(crons: list[str]) -> list[str]:
    """The REVIEW-3105 / LQ-3096 margins (tests/test_cc_products_builder_lanes_lq3008_20261113.py): the gap to the next fire
    is at most half the stored stale window and a quarter of the hard expiry; for an open-clamped row (stale < 360 s), strictly
    inside stale and at most half the hard expiry."""
    from datetime import timezone
    fires = sorted({f.at for e in crons for f in cron_schedule.fires_between(e, WEEK_START, WEEK_END, "America/New_York")},
                   key=lambda x: x.astimezone(timezone.utc))
    bad = []
    for a, b in zip(fires, fires[1:]):
        gap = (b.astimezone(timezone.utc) - a.astimezone(timezone.utc)).total_seconds()
        lim = cio_pages.limits_for(a)
        stale, hard = lim["stale_after_s"], lim["hard_expiry_s"]
        ok = (gap < stale and gap * 2 <= hard) if stale < 360 else (gap <= stale / 2 and gap * 4 <= hard)
        if not ok:
            bad.append(f"{a.astimezone(ET):%a %H:%M} gap {gap:.0f} stale {stale} hard {hard}")
    return bad


def test_pre_open_fires_converge_inside_the_open_clamped_margins():
    assert _margin_violations(_crons()) == []
    fires = {f.at.astimezone(ET).strftime("%H:%M") for e in _crons()
             for f in cron_schedule.fires_between(e, WEEK_START, WEEK_START + timedelta(days=1), "America/New_York")}
    assert {"07:30", "08:00", "09:28", "09:30"} <= fires and "07:45" not in fires


def test_mutant_single_0900_pre_open_fire_breaks_the_margins():
    """The list as first ruled (*/30 through 08:59 plus one 09:00 fire) passes the minute walk but not the margins:
    08:00, 08:30 and 09:00 each store an open-clamped hard expiry shorter than four gaps."""
    crons = [c for c in _crons() if c not in ("*/30 0-7,17-23 * * 1-5", "0,20,38,51 8 * * 1-5",
                                              "1,8,14,18,21,23,25,26,28 9 * * 1-5")]
    crons += ["*/30 0-8,17-23 * * 1-5", "0 9 * * 1-5"]
    assert _violations(crons, 30) == []
    bad = _margin_violations(crons)
    assert any(v.startswith("Mon 09:00") for v in bad) and any(v.startswith("Mon 08:00") for v in bad), bad[:5]
