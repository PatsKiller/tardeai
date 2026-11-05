"""EMERGENCY slice 3 — position staleness in trading sessions, not wall-clock hours.

The Home Command Center PORTFOLIO tile rendered "positions observed 2026-10-30 20:52"
(the producer's raw UTC string) and called the book STALE every Monday before the
09:07 ET broker sync, because 48 wall-clock hours had elapsed over a weekend in
which zero trading sessions completed.

This suite pins both halves of the fix:

* ``market_session.trading_sessions_between`` counts COMPLETED sessions — a session
  is complete once its close (16:00 ET, or 13:00 ET on an early-close day) has
  passed — excluding weekends and NYSE full-closure holidays.
* ``portfolio_aggregate_contract`` publishes that count and a session-based stale
  flag from a CONFIG threshold. ``stale_after_hours`` and every field derived from
  it keep their existing meaning for other consumers.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import market_session as MS  # noqa: E402
from lib import portfolio_aggregate_contract as pac  # noqa: E402

ET = ZoneInfo("America/New_York")


def et(y, m, d, h=0, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=ET)


def utc(y, m, d, h=0, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=timezone.utc)


# ── trading_sessions_between ────────────────────────────────────────────────


def test_friday_after_close_to_sunday_is_zero_sessions():
    assert MS.trading_sessions_between(et(2026, 11, 6, 16, 52), et(2026, 11, 8, 23, 0)) == 0


def test_friday_after_close_to_monday_before_open_is_zero_sessions():
    """The live defect: ~63 wall hours, but not one session has completed."""
    assert MS.trading_sessions_between(et(2026, 11, 6, 16, 52), et(2026, 11, 9, 8, 0)) == 0


def test_friday_intraday_to_monday_before_open_is_one_completed_session():
    """Friday's own close happened after the observation, so it counts."""
    assert MS.trading_sessions_between(et(2026, 11, 6, 10, 0), et(2026, 11, 9, 8, 0)) == 1


def test_friday_after_close_to_monday_after_close_is_one_session():
    assert MS.trading_sessions_between(et(2026, 11, 6, 16, 52), et(2026, 11, 9, 16, 30)) == 1


def test_a_full_week_is_five_sessions():
    assert MS.trading_sessions_between(et(2026, 11, 2, 16, 30), et(2026, 11, 9, 16, 30)) == 5


def test_thanksgiving_is_not_a_session_but_the_early_close_friday_is():
    # 2026-11-26 is a full NYSE closure; 2026-11-27 is a 13:00 ET early close.
    assert MS.trading_sessions_between(et(2026, 11, 25, 16, 30), et(2026, 11, 27, 16, 30)) == 1


def test_early_close_counts_from_1300_not_1600():
    start = et(2026, 11, 25, 16, 30)
    assert MS.trading_sessions_between(start, et(2026, 11, 27, 12, 0)) == 0
    assert MS.trading_sessions_between(start, et(2026, 11, 27, 13, 30)) == 1


def test_same_instant_is_zero():
    assert MS.trading_sessions_between(et(2026, 11, 6, 12, 0), et(2026, 11, 6, 12, 0)) == 0


def test_reversed_inputs_are_symmetric_not_negative():
    a, b = et(2026, 11, 2, 16, 30), et(2026, 11, 9, 16, 30)
    assert MS.trading_sessions_between(a, b) == MS.trading_sessions_between(b, a) == 5


def test_live_defect_stamp_across_dst_is_zero_sessions():
    """The exact live pair: Fri 16:52 EDT observation read Mon 07:00 EST."""
    obs = datetime(2026, 10, 30, 20, 52, tzinfo=timezone.utc)
    now = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)
    assert MS.trading_sessions_between(obs, now) == 0


def test_naive_instants_are_read_as_utc():
    # 2026-11-06T21:52Z is Fri 16:52 ET; 2026-11-09T13:00Z is Mon 08:00 ET.
    start = datetime(2026, 11, 6, 21, 52)
    end = datetime(2026, 11, 9, 13, 0)
    assert MS.trading_sessions_between(start, end) == 0


# ── portfolio_aggregate_contract: session fields ────────────────────────────

# The live defect shape: a Friday after-close observation, read on Monday morning.
OBS_FRI_AFTER_CLOSE = "2026-10-30T20:52:00+00:00"  # Fri 2026-10-30 16:52 ET


def _agg(now: datetime) -> dict:
    return pac.build_portfolio_aggregate(
        aggregate_value=1000.0,
        account_summaries={
            "schwab_taxable": {
                "total_value": 1000.0,
                "holdings_count": 3,
                "as_of": OBS_FRI_AFTER_CLOSE,
            }
        },
        data_as_of=None,
        data_as_of_account=None,
        now=now,
    )


def test_monday_before_the_sync_is_not_stale_by_sessions():
    """THE BUG: 63.1 wall hours → the old rule said STALE, but 0 sessions completed."""
    agg = _agg(utc(2026, 11, 2, 12, 0))  # Mon 07:00 EST, before the 09:07 sync
    assert agg["position_observation_oldest_age_sessions"] == 0
    assert agg["position_observation_stale_after_sessions"] == 1
    assert agg["position_observation_stale"] is False
    # The hours clock and every existing consequence of it are untouched.
    assert agg["position_observation_oldest_age_hours"] == pytest.approx(63.13, abs=0.01)
    assert agg["coverage"]["stale_after_hours"] == 48.0
    assert agg["freshness_state"] == "STALE"


def test_one_full_session_missed_is_stale_by_sessions():
    agg = _agg(utc(2026, 11, 2, 21, 30))  # Mon 16:30 ET, after the close
    assert agg["position_observation_oldest_age_sessions"] == 1
    assert agg["position_observation_stale"] is True


def test_threshold_comes_from_config_not_code(tmp_path, monkeypatch):
    cfg = tmp_path / "clock.json"
    cfg.write_text(
        json.dumps({"schema": "PortfolioObservationClock@v1", "stale_after_sessions": 2}),
        encoding="utf-8",
    )
    monkeypatch.setattr(pac, "OBSERVATION_CLOCK_CONFIG", cfg)

    agg = _agg(utc(2026, 11, 2, 21, 30))  # one completed session
    assert agg["position_observation_stale_after_sessions"] == 2
    assert agg["coverage"]["stale_after_sessions"] == 2
    assert agg["position_observation_stale"] is False


def test_missing_config_yields_no_session_decision(tmp_path, monkeypatch):
    monkeypatch.setattr(pac, "OBSERVATION_CLOCK_CONFIG", tmp_path / "absent.json")
    agg = _agg(utc(2026, 11, 2, 21, 30))
    assert agg["position_observation_stale_after_sessions"] is None
    assert agg["position_observation_stale"] is None


@pytest.mark.parametrize("value", [True, "1", -1, 0, 1.5, None])
def test_invalid_threshold_refuses_a_session_decision(tmp_path, monkeypatch, value):
    cfg = tmp_path / "clock.json"
    cfg.write_text(json.dumps({"stale_after_sessions": value}), encoding="utf-8")
    monkeypatch.setattr(pac, "OBSERVATION_CLOCK_CONFIG", cfg)

    agg = _agg(utc(2026, 11, 2, 21, 30))
    assert agg["position_observation_stale_after_sessions"] is None
    assert agg["position_observation_stale"] is None


def test_undated_book_gets_no_session_age_or_decision():
    agg = pac.build_portfolio_aggregate(
        aggregate_value=1.0,
        account_summaries={"x": {"total_value": 0.0, "as_of": ""}},
    )
    assert agg["position_observation_oldest_age_sessions"] is None
    assert agg["position_observation_stale"] is None


def test_shipped_config_sets_the_threshold():
    """The repo's own config must carry the threshold — no code default."""
    doc = json.loads(pac.OBSERVATION_CLOCK_CONFIG.read_text(encoding="utf-8"))
    assert doc["schema"] == "PortfolioObservationClock@v1"
    assert isinstance(doc["stale_after_sessions"], int)
    assert not isinstance(doc["stale_after_sessions"], bool)
    assert doc["stale_after_sessions"] >= 1
