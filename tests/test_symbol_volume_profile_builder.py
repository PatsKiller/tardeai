#!/usr/bin/env python3
"""M3-S1 unit tests — pure volume-profile aggregation core (no I/O, no network, no DB)."""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.symbol_volume_profile_builder import (  # noqa: E402
    minute_of_session, session_cum_incr, median_profile, build_profile_from_sessions,
)

ET = ZoneInfo("America/New_York")


def test_minute_of_session_open_is_zero():
    assert minute_of_session(datetime(2026, 7, 24, 9, 30, tzinfo=ET)) == 0


def test_minute_of_session_last_regular_minute():
    assert minute_of_session(datetime(2026, 7, 24, 15, 59, tzinfo=ET)) == 389


def test_minute_of_session_premarket_negative():
    assert minute_of_session(datetime(2026, 7, 24, 9, 0, tzinfo=ET)) == -30


def test_minute_of_session_postmarket_ge_390():
    assert minute_of_session(datetime(2026, 7, 24, 16, 0, tzinfo=ET)) == 390


def test_session_cum_is_monotonic_nondecreasing():
    cum, incr = session_cum_incr({0: 100, 1: 50, 3: 25}, n_minutes=5)
    assert cum == [100, 150, 150, 175, 175]      # missing minute 2 carries forward
    assert incr == [100, 50, 0, 25, 0]
    assert all(cum[i] <= cum[i + 1] for i in range(len(cum) - 1))


def test_session_cum_empty_session_all_zero():
    cum, incr = session_cum_incr({}, n_minutes=4)
    assert cum == [0, 0, 0, 0]
    assert incr == [0, 0, 0, 0]


def test_session_cum_final_equals_total_volume():
    mv = {0: 10, 5: 20, 9: 70}
    cum, _ = session_cum_incr(mv, n_minutes=10)
    assert cum[-1] == 100


def test_median_profile_odd_count():
    # three sessions, cumulative arrays; median per minute
    s = [[10, 20], [30, 40], [20, 100]]
    i = [[10, 10], [30, 10], [20, 80]]
    med_cum, med_incr = median_profile(s, i)
    assert med_cum == [20, 40]        # median(10,30,20)=20 ; median(20,40,100)=40
    assert med_incr == [20, 10]


def test_median_profile_even_count_averages_middle():
    s = [[10, 0], [30, 0]]
    med_cum, _ = median_profile(s, [[10, 0], [30, 0]])
    assert med_cum[0] == 20           # median of 2 values = mean


def test_median_profile_empty_returns_empty():
    assert median_profile([], []) == ([], [])


def test_build_pipeline_end_to_end_median_and_monotonic():
    # two synthetic sessions over 4 minutes
    sessions = [
        {0: 100, 1: 100, 2: 100, 3: 100},   # cum 100,200,300,400
        {0: 200, 1: 0, 2: 200, 3: 0},        # cum 200,200,400,400
    ]
    med_cum, med_incr = build_profile_from_sessions(sessions, n_minutes=4)
    assert med_cum == [150, 200, 350, 400]   # per-minute median of the two cum arrays
    assert all(med_cum[k] <= med_cum[k + 1] for k in range(3))  # still monotonic
    assert med_incr == [150, 50, 150, 50]


def test_build_pipeline_u_shape_incremental():
    # heavier volume at open and close than midday → U-shape in incremental
    sessions = []
    for _ in range(3):
        mv = {m: 1000 for m in range(390)}
        for m in list(range(0, 30)) + list(range(360, 390)):
            mv[m] = 5000                      # open/close bursts
        sessions.append(mv)
    _, med_incr = build_profile_from_sessions(sessions, n_minutes=390)
    open_avg = sum(med_incr[:30]) / 30
    mid_avg = sum(med_incr[180:210]) / 30
    close_avg = sum(med_incr[-30:]) / 30
    assert open_avg > mid_avg and close_avg > mid_avg


# ── G2.2 freshness contract (staleness accessor refuses stale/thin denominators) ──

import pytest  # noqa: E402
import yaml as _yaml  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from scripts.symbol_volume_profile_builder import (  # noqa: E402
    trading_sessions_between, get_profile_denominator, ProfileUnavailable,
)

_CFG = _yaml.safe_load((ROOT / "config" / "scalp_signal_engine.yaml").read_text())
_NOW = datetime(2026, 7, 27, 21, 0, tzinfo=timezone.utc)   # Monday


class _FakeCursor:
    def __init__(self, row): self._row = row
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def execute(self, *a, **k): pass
    def fetchone(self): return self._row


class _FakeConn:
    def __init__(self, row): self._row = row
    def cursor(self): return _FakeCursor(self._row)


def test_trading_sessions_between_counts_weekdays():
    assert trading_sessions_between(datetime(2026, 7, 20, tzinfo=timezone.utc), _NOW) == 5

def test_trading_sessions_between_same_day_zero():
    assert trading_sessions_between(datetime(2026, 7, 27, tzinfo=timezone.utc), _NOW) == 0

def test_denominator_fresh_and_populated_returns_value():
    row = (500000.0, 20, datetime(2026, 7, 27, 14, tzinfo=timezone.utc))
    val, meta = get_profile_denominator(_FakeConn(row), "AAPL", 60, _CFG, now=_NOW)
    assert val == 500000.0 and meta["reason"] == "ok"

def test_denominator_stale_by_age_refuses():
    row = (500000.0, 20, datetime(2026, 7, 20, 14, tzinfo=timezone.utc))  # 5 sessions old > 3
    val, meta = get_profile_denominator(_FakeConn(row), "AAPL", 60, _CFG, now=_NOW)
    assert val is None and meta["reason"].startswith("stale")

def test_denominator_under_populated_refuses():
    row = (500000.0, 10, datetime(2026, 7, 27, 14, tzinfo=timezone.utc))  # 10 < 15
    val, meta = get_profile_denominator(_FakeConn(row), "AAPL", 60, _CFG, now=_NOW)
    assert val is None and meta["reason"].startswith("under_populated")

def test_denominator_absent_symbol_refuses():
    val, meta = get_profile_denominator(_FakeConn(None), "NOPE", 60, _CFG, now=_NOW)
    assert val is None and meta["reason"] == "absent"

def test_denominator_raise_mode_blocks_silent_consumption():
    row = (500000.0, 10, datetime(2026, 7, 27, tzinfo=timezone.utc))
    with pytest.raises(ProfileUnavailable):
        get_profile_denominator(_FakeConn(row), "AAPL", 60, _CFG, now=_NOW, raise_on_refuse=True)


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
