#!/usr/bin/env python3
"""M3-S4 unit tests — outcome-backfill math and rollup deciles (pure, no I/O)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.scalp_shadow_outcome_backfill import compute_outcomes  # noqa: E402
from scripts.scalp_shadow_rollup import p_at_1r_by_band, is_monotonic_nondecreasing, cohort_of  # noqa: E402


def bar(off, h, l, c):
    return {"off": off, "h": h, "l": l, "c": c}


# ── compute_outcomes ────────────────────────────────────────────────
def test_hit_1r_target_first():
    o = compute_outcomes(100, 99, [bar(1, 100.5, 99.5, 100.2), bar(2, 101.0, 100.0, 101.0)])
    assert o["hit_1r_first"] is True and o["time_to_1r_sec"] == 120

def test_hit_1r_stop_first():
    o = compute_outcomes(100, 99, [bar(1, 100.5, 98.9, 99.0)])
    assert o["hit_1r_first"] is False

def test_same_bar_touch_is_conservative_stop_first():
    o = compute_outcomes(100, 99, [bar(1, 101.0, 98.0, 100.0)])  # touches both target & stop
    assert o["hit_1r_first"] is False

def test_unresolved_within_30m_is_none():
    o = compute_outcomes(100, 99, [bar(1, 100.5, 99.5, 100.0), bar(2, 100.4, 99.6, 100.0)])
    assert o["hit_1r_first"] is None

def test_mfe_mae_by_horizon():
    bars = [bar(5, 102, 99.5, 101), bar(15, 103, 98.0, 100)]
    o = compute_outcomes(100, 99, bars)
    assert o["mfe_5m"] == pytest.approx(2.0)     # max high(102) - entry
    assert o["mae_5m"] == pytest.approx(0.5)     # entry - min low(99.5)
    assert o["mfe_15m"] == pytest.approx(3.0)    # includes 103
    assert o["mae_15m"] == pytest.approx(2.0)    # includes 98.0

def test_r_multiple_30m():
    o = compute_outcomes(100, 99, [bar(30, 100.5, 99.5, 100.5)])  # R=1, close 100.5 → +0.5R
    assert o["r_multiple_30m"] == pytest.approx(0.5)

def test_mae_floored_at_zero_when_never_adverse():
    # price only goes up → adverse excursion is 0, not negative
    o = compute_outcomes(100, 99, [bar(5, 103, 100.5, 102)])
    assert o["mae_5m"] == 0.0 and o["mfe_5m"] == pytest.approx(3.0)

def test_nonpositive_R_returns_all_none():
    o = compute_outcomes(100, 100, [bar(1, 101, 99, 100)])
    assert o["hit_1r_first"] is None and o["mfe_5m"] is None

def test_empty_post_bars():
    o = compute_outcomes(100, 99, [])
    assert all(v is None for v in o.values())


# ── rollup deciles ──────────────────────────────────────────────────
def test_p_at_1r_by_band_basic():
    evs = [{"ign": 75, "hit": True}, {"ign": 72, "hit": False}, {"ign": 45, "hit": True}]
    bands = p_at_1r_by_band(evs)
    d = {b["band"]: b for b in bands}
    assert d["70-80"]["n"] == 2 and d["70-80"]["p_at_1r"] == pytest.approx(0.5)
    assert d["40-50"]["n"] == 1 and d["40-50"]["p_at_1r"] == pytest.approx(1.0)

def test_p_at_1r_excludes_unresolved():
    evs = [{"ign": 75, "hit": None}, {"ign": 75, "hit": True}]
    bands = p_at_1r_by_band(evs)
    assert bands[0]["n"] == 1

def test_monotonicity_helper():
    assert is_monotonic_nondecreasing([{"p_at_1r": 0.2}, {"p_at_1r": 0.4}, {"p_at_1r": 0.4}])
    assert not is_monotonic_nondecreasing([{"p_at_1r": 0.5}, {"p_at_1r": 0.3}])

def test_cohort_mapping_never_pools():
    assert cohort_of("per_symbol") == "profiled"
    assert cohort_of("universe_proxy") == "proxy"
    assert cohort_of("none") == "proxy"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
