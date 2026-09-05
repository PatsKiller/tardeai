"""A weekday-only freshness check must not page for the weekend.

2026-09-05 was a Saturday. `ticker_prices` last row was Friday 15:55 — the
correct value for a Saturday evening, because the market is closed and
price_db_sync runs 07:20 Mon-Fri. The monitor paged it P1 anyway:

    [P1] ticker_prices last row 26.1h ago (max 26h)

The gate counted CALENDAR weekday hours in the lookback window. At Saturday
18:00 a 26-hour window reaches Friday 16:00, so it found 8 weekday hours and
decided the check was meaningful. Every one of those hours is after the close,
and the writer runs in the morning: it had no opportunity to produce in that
window at all. The alert fires every weekend by construction.

That is the second time this gate has been wrong in the same place. The first
(G1, 2026-08-31) asked whether TODAY was Saturday rather than whether the WINDOW
held weekday hours. This is the follow-on: weekday hours are not the same as
hours the writer could have run.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import system_freshness_monitor as m  # noqa: E402

TICKER_PRICES_MAX_AGE_H = 26


def _runs_at(when: datetime, hours: float = TICKER_PRICES_MAX_AGE_H) -> bool:
    with mock.patch.object(m, "datetime") as dt:
        dt.now.return_value = when
        return m._window_covers_a_weekday(hours)


# ── the false page this removes ─────────────────────────────────────────────

def test_saturday_evening_does_not_page_for_a_weekday_only_writer():
    """The exact alert of 2026-09-05, which was a Saturday."""
    assert _runs_at(datetime(2026, 9, 5, 18, 0)) is False


@pytest.mark.parametrize("hour", [15, 18, 21, 23])
def test_saturday_goes_quiet_once_the_window_has_passed_fridays_production(hour):
    """Not "Saturday is always quiet" — that would be wrong, and would delete
    real detection. Until roughly Saturday afternoon the 26h window still
    overlaps Friday 06:00-17:00, so a genuinely missing Friday price is still
    caught. It goes quiet only when the window no longer contains any hour the
    writer could have run, which is exactly when the false page fired (18:00)."""
    assert _runs_at(datetime(2026, 9, 5, hour, 0)) is False


@pytest.mark.parametrize("hour", [0, 6, 9, 12])
def test_saturday_morning_still_validates_fridays_data(hour):
    """The complement, and the reason this is a fix rather than a mute button."""
    assert _runs_at(datetime(2026, 9, 5, hour, 0)) is True


@pytest.mark.parametrize("hour", [0, 8, 12, 20])
def test_no_hour_of_sunday_pages(hour):
    assert _runs_at(datetime(2026, 9, 6, hour, 0)) is False


def test_early_monday_is_still_quiet_because_the_writer_may_not_have_run():
    """07:20 Monday has barely passed at 09:00. Conservative is the right
    direction for a detector whose false positives train the operator to
    ignore it."""
    assert _runs_at(datetime(2026, 9, 7, 9, 0)) is False


# ── real detection must survive ─────────────────────────────────────────────

def test_monday_afternoon_still_catches_a_genuine_failure():
    """By Monday afternoon a missing price IS a fault, and must still page."""
    assert _runs_at(datetime(2026, 9, 7, 14, 0)) is True


@pytest.mark.parametrize("day,hour", [(8, 9), (9, 12), (10, 15), (4, 18)])
def test_weekdays_still_run_the_check(day, hour):
    assert _runs_at(datetime(2026, 9, day, hour, 0)) is True


def test_a_long_window_spanning_a_full_week_always_runs():
    """A 30h+ check on a weekday must not be accidentally silenced."""
    assert _runs_at(datetime(2026, 9, 9, 12, 0), hours=30) is True


# ── the property, not the constants ─────────────────────────────────────────

def test_productive_hours_exclude_the_overnight_and_after_close_window():
    """The defect was counting 16:00-23:59 Friday as opportunity to produce."""
    assert m.PRODUCTIVE_HOUR_START >= 5
    assert m.PRODUCTIVE_HOUR_END <= 18
    assert m.PRODUCTIVE_HOUR_START < m.PRODUCTIVE_HOUR_END


def test_ticker_prices_is_still_declared_weekday_only():
    """If this flag is ever dropped the gate never applies and the weekend page
    returns by a different route."""
    checks = [c for c in m.REGISTRY if c.get("key") == "ticker_prices"]
    assert checks, "ticker_prices check disappeared"
    assert checks[0].get("weekday_only") is True


def test_the_gate_is_a_window_question_not_a_today_question():
    """G1's defect: asking whether TODAY is Saturday. A Monday-00:00 window is
    almost entirely weekend and must stay quiet even though today is a weekday."""
    assert _runs_at(datetime(2026, 9, 7, 0, 30), hours=30) is False
