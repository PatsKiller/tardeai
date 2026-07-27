#!/usr/bin/env python3
"""M3-S3 unit tests — IGN ignition scorer (§3.2/§3.3). Pure, no I/O. Sub-scores at zero /
saturation / midpoint, the σ_20bar floor guard, composite, lanes, RVOL_tod + proxy."""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts import scalp_ignition_scorer as s  # noqa: E402

CFG = yaml.safe_load((ROOT / "config" / "scalp_signal_engine.yaml").read_text())
IGN = CFG["ignition"]
NOTIF = CFG["notifications"]


# ── v_rvol ──────────────────────────────────────────────────────────
def test_v_rvol_zero_at_ref():
    assert s.v_rvol(2.0, IGN) == pytest.approx(0.0)

def test_v_rvol_saturates_at_20x():
    assert s.v_rvol(20.0, IGN) == pytest.approx(1.0)

def test_v_rvol_midpoint():
    # log10(rvol/2)=0.5 → rvol = 2*10^0.5 = 6.3246
    assert s.v_rvol(2.0 * 10 ** 0.5, IGN) == pytest.approx(0.5, abs=1e-9)

def test_v_rvol_below_ref_clamps_zero():
    assert s.v_rvol(1.0, IGN) == 0.0

def test_v_rvol_none_is_zero():
    assert s.v_rvol(None, IGN) == 0.0


# ── v_burst + σ floor guard ─────────────────────────────────────────
def test_v_burst_zero_when_at_mean():
    assert s.v_burst(100, 100, 50, IGN) == pytest.approx(0.0)

def test_v_burst_saturates_at_z6():
    # z=6 → clamp(6/6)=1 ; (v-100)/50 = 6 → v = 400
    assert s.v_burst(400, 100, 50, IGN) == pytest.approx(1.0)

def test_v_burst_midpoint_z3():
    assert s.v_burst(400, 100, 100, IGN) == pytest.approx(0.5)

def test_v_burst_sigma_floor_guard_prevents_blowup():
    # σ=0 must NOT divide by zero; floor = max(0, 0.1*μ, eps) = max(0,10,1)=10
    # (130-100)/10 = 3 → 0.5
    assert s.v_burst(130, 100, 0, IGN) == pytest.approx(0.5)

def test_v_burst_sigma_none_uses_floor():
    assert s.v_burst(130, 100, None, IGN) == pytest.approx(0.5)

def test_v_burst_dead_window_no_crash():
    # μ=0, σ=0 → σ_eff = eps = 1 ; v=3 → z=3 → 0.5, no exception
    assert s.v_burst(3, 0, 0, IGN) == pytest.approx(0.5)

def test_sigma_effective_takes_max():
    assert s.sigma_effective(100, 3, IGN) == 10.0   # max(3, 0.1*100=10, 1)
    assert s.sigma_effective(100, 50, IGN) == 50.0
    assert s.sigma_effective(0, 0, IGN) == 1.0       # eps floor


# ── v_cat ───────────────────────────────────────────────────────────
def test_v_cat_fresh_full_tier_is_one():
    assert s.v_cat(1.0, 0.0, IGN) == pytest.approx(1.0)

def test_v_cat_decays_at_halflife():
    assert s.v_cat(1.0, 90.0, IGN) == pytest.approx(math.exp(-1.0), abs=1e-9)

def test_v_cat_zero_tier_or_none():
    assert s.v_cat(0.0, 0.0, IGN) == 0.0
    assert s.v_cat(None, 0.0, IGN) == 0.0

def test_v_cat_negative_age_treated_zero():
    assert s.v_cat(0.7, -5, IGN) == pytest.approx(0.7)


# ── v_disp ──────────────────────────────────────────────────────────
def test_v_disp_zero_at_vwap():
    assert s.v_disp(100.0, 100.0, 1.0, 4, IGN) == 0.0

def test_v_disp_midpoint():
    # (101-100)/(2*1*sqrt(1)) = 1/2 = 0.5
    assert s.v_disp(101.0, 100.0, 1.0, 1, IGN) == pytest.approx(0.5)

def test_v_disp_saturates():
    assert s.v_disp(200.0, 100.0, 1.0, 1, IGN) == 1.0

def test_v_disp_zero_atr_is_zero():
    assert s.v_disp(101.0, 100.0, 0.0, 4, IGN) == 0.0


# ── v_liq ───────────────────────────────────────────────────────────
def test_v_liq_zero_at_ref():
    # price*vol_5m = 50000 → 0
    assert s.v_liq(10.0, 5000.0, IGN) == pytest.approx(0.0)

def test_v_liq_near_one_at_2_5m():
    # price*vol = 2.5M → log10(50)/1.7 ≈ 0.999
    assert s.v_liq(10.0, 250000.0, IGN) == pytest.approx(math.log10(50) / 1.7, abs=1e-9)

def test_v_liq_zero_below_ref():
    assert s.v_liq(1.0, 100.0, IGN) == 0.0


# ── v_rs / percentile ───────────────────────────────────────────────
def test_percentile_rank_max_is_one():
    assert s.percentile_rank(0.10, [0.01, 0.05, 0.10]) == pytest.approx(1.0)

def test_percentile_rank_min_fraction():
    assert s.percentile_rank(0.01, [0.01, 0.05, 0.10]) == pytest.approx(1 / 3)

def test_percentile_rank_empty_is_zero():
    assert s.percentile_rank(0.5, []) == 0.0

def test_v_rs_none_is_zero():
    assert s.v_rs(None, [0.1, 0.2], IGN) == 0.0


# ── composite + lanes ───────────────────────────────────────────────
def test_composite_all_ones_is_100():
    subs = {k: 1.0 for k in IGN["weights"]}
    assert s.composite_ign(subs, IGN) == pytest.approx(100.0)

def test_composite_all_zero_is_zero():
    subs = {k: 0.0 for k in IGN["weights"]}
    assert s.composite_ign(subs, IGN) == 0.0

def test_weights_sum_to_one():
    assert sum(IGN["weights"].values()) == pytest.approx(1.0)

def test_classify_lanes():
    assert s.classify_lane(80, NOTIF) == s.LANE_75
    assert s.classify_lane(65, NOTIF) == s.LANE_60
    assert s.classify_lane(50, NOTIF) == s.LANE_45
    assert s.classify_lane(10, NOTIF) == s.LANE_BELOW

def test_classify_lane_accel_fires_at_any_level():
    # ΔIGN >= 15 from prev → accel regardless of absolute level
    assert s.classify_lane(30, NOTIF, prev_ign=10) == s.LANE_ACCEL


# ── RVOL_tod + proxy ────────────────────────────────────────────────
def test_rvol_tod_basic():
    assert s.rvol_tod(300000, 100000) == pytest.approx(3.0)

def test_rvol_tod_none_when_no_profile():
    assert s.rvol_tod(300000, 0) is None
    assert s.rvol_tod(300000, None) is None

def test_rvol_tod_proxy():
    # cum / (adv * frac) = 300000 / (2_000_000 * 0.05) = 3.0
    assert s.rvol_tod_proxy(300000, 2_000_000, 0.05) == pytest.approx(3.0)

def test_rvol_tod_proxy_missing_inputs_none():
    assert s.rvol_tod_proxy(300000, None, 0.05) is None
    assert s.rvol_tod_proxy(300000, 2_000_000, 0) is None


# ── end-to-end score ────────────────────────────────────────────────
def test_score_end_to_end_ranges_and_lane():
    inputs = {
        "rvol_tod": 6.3246, "v_1m": 400, "mu_20": 100, "sigma_20": 100,
        "tier_weight": 1.0, "age_min": 0.0, "price": 101.0, "vwap": 100.0,
        "atr_1m": 1.0, "n_bars": 1, "vol_5m": 250000.0,
        "rs_value": 0.1, "universe_rs": [0.01, 0.05, 0.1],
    }
    out = s.score(inputs, CFG)
    assert 0 <= out["ign"] <= 100
    for v in out["subscores"].values():
        assert 0.0 <= v <= 1.0
    assert out["lane"] in (s.LANE_75, s.LANE_60, s.LANE_45, s.LANE_BELOW, s.LANE_ACCEL)

def test_score_all_max_inputs_approaches_100():
    inputs = {
        "rvol_tod": 100, "v_1m": 100000, "mu_20": 100, "sigma_20": 100,
        "tier_weight": 1.0, "age_min": 0.0, "price": 1000.0, "vwap": 1.0,
        "atr_1m": 0.01, "n_bars": 1, "vol_5m": 1e9,
        "rs_value": 1.0, "universe_rs": [0.0, 0.5, 1.0],
    }
    out = s.score(inputs, CFG)
    assert out["ign"] == pytest.approx(100.0, abs=0.5)
    assert out["lane"] == s.LANE_75


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
