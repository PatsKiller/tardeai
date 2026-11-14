"""LQ-20261107 H4 — the route's freshness limit follows the lane's registered cadence, not one fixed number.

Synthetic only: no DB, no lane run, no file written.  The weekend expression the limit is derived from is
``config/lane_registry.json`` lane ``since-close-snapshot`` ``dispatch.cron = ["0 */2 * * 1-5", "0 */6 * * 0,6"]``:
a non-trading day fires every 6 h (00, 06, 12, 18 ET), so a 3 h or 4 h limit calls a healthy snapshot stale for
hours of every cycle -- and the API then disagrees with the strip, which used a different constant.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from lib import since_close_card as card  # noqa: E402

ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")


def et(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=ET)


SUN = et(2026, 11, 8, 12, 30)  # Sunday: a non-trading day, six-hourly cadence
TUE = et(2026, 11, 10, 11, 0)  # Tuesday: a trading day


def _snap(now, age):
    gen = (now - age).astimezone(UTC).isoformat().replace("+00:00", "Z")
    return {"generated_at": gen, "window": card.window(now)}


def test_staleness_limit_follows_the_day_class():
    assert card.staleness_limit(SUN) == timedelta(hours=6, minutes=30)  # 0 */6 + the card's 30 min grace
    assert card.staleness_limit(TUE) == timedelta(hours=3)              # 2-hourly rebuild + slack


def test_weekend_snapshot_is_fresh_between_registered_fires():
    # 12:00 build read at 16:30 ET is 4.5 h old: healthy at a 6 h cadence, and the old 3 h limit called it stale
    assert card.freshness(_snap(SUN, timedelta(hours=4, minutes=30)), now=SUN)["stale"] is False


def test_weekend_snapshot_past_one_cadence_plus_grace_is_stale():
    now = et(2026, 11, 8, 19, 0)
    assert card.freshness(_snap(now, timedelta(hours=7)), now=now)["stale"] is True
    assert card.freshness(_snap(now, timedelta(hours=6, minutes=10)), now=now)["stale"] is False


def test_trading_day_limit_is_unchanged_and_an_explicit_max_age_still_wins():
    snap = _snap(TUE, timedelta(hours=4))
    assert card.freshness(snap, now=TUE)["stale"] is True
    assert card.freshness(snap, now=TUE, max_age=timedelta(hours=5))["stale"] is False


def test_wrong_window_is_stale_regardless_of_age():
    # a Friday-window snapshot read on Sunday is the wrong session, however young it claims to be
    now = SUN
    snap = {"generated_at": (now - timedelta(minutes=5)).astimezone(UTC).isoformat(), "window": {"session_date": "2026-11-05"}}
    f = card.freshness(snap, now=now)
    assert f["window_current"] is False and f["stale"] is True
