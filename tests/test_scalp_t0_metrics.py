#!/usr/bin/env python3
"""M3-S2 unit tests — Tier-0 metric library, hand-computed fixtures (pure, no I/O)."""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts import scalp_t0_metrics as m  # noqa: E402


def bar(o, h, l, c, v):
    return {"o": o, "h": h, "l": l, "c": c, "v": v}


# ── CLV / bar_pressure ──────────────────────────────────────────────

def test_clv_close_at_high_is_one():
    assert m.clv(bar(9, 10, 8, 10, 100)) == 1.0


def test_clv_close_at_low_is_zero():
    assert m.clv(bar(9, 10, 8, 8, 100)) == 0.0


def test_clv_close_at_mid_is_half():
    assert m.clv(bar(9, 10, 8, 9, 100)) == 0.5


def test_clv_undefined_when_high_equals_low():
    assert m.clv(bar(5, 5, 5, 5, 100)) is None


def test_bar_pressure_all_closes_high_is_plus_one():
    bars = [bar(9, 10, 8, 10, 100), bar(9, 10, 8, 10, 50)]
    assert m.bar_pressure(bars) == pytest.approx(1.0)


def test_bar_pressure_all_closes_low_is_minus_one():
    bars = [bar(9, 10, 8, 8, 100), bar(9, 10, 8, 8, 50)]
    assert m.bar_pressure(bars) == pytest.approx(-1.0)


def test_bar_pressure_volume_weighted_cancels_to_zero():
    # equal volume: one bar +1 (close high), one bar -1 (close low) → 0
    bars = [bar(9, 10, 8, 10, 100), bar(9, 10, 8, 8, 100)]
    assert m.bar_pressure(bars) == pytest.approx(0.0)


def test_bar_pressure_volume_weights_toward_heavier_bar():
    # +1 bar has 3x the volume of the -1 bar → (1*300 + -1*100)/400 = 0.5
    bars = [bar(9, 10, 8, 10, 300), bar(9, 10, 8, 8, 100)]
    assert m.bar_pressure(bars) == pytest.approx(0.5)


def test_bar_pressure_none_when_no_volume():
    assert m.bar_pressure([bar(9, 10, 8, 9, 0)]) is None


# ── Corwin–Schultz ──────────────────────────────────────────────────

def test_corwin_schultz_identical_bars_equals_2_tanh_half_logHL():
    # analytic result: for identical consecutive bars, alpha = ln(H/L), so S = 2*tanh(ln(H/L)/2)
    b = bar(100, 102, 98, 100, 100)
    k = math.log(102 / 98)
    expected = 2.0 * math.tanh(k / 2.0)
    got = m.corwin_schultz_spread([b, b])
    assert got == pytest.approx(expected, abs=1e-9)
    assert got == pytest.approx(0.039990, abs=1e-4)   # ≈ ln(102/98) = 0.04001


def test_corwin_schultz_nonnegative_and_averaged():
    bars = [bar(100, 102, 98, 100, 100)] * 4
    s = m.corwin_schultz_spread(bars)
    assert s is not None and s >= 0


def test_corwin_schultz_none_on_single_bar():
    assert m.corwin_schultz_spread([bar(100, 102, 98, 100, 100)]) is None


# ── Abdi–Ranaldo ────────────────────────────────────────────────────

def test_abdi_ranaldo_zero_when_close_is_geometric_mid():
    # C_t = sqrt(H*L) → ln C = (lnH+lnL)/2 = eta → (c-eta)=0 → S=0
    gm = math.sqrt(110 * 90)
    bars = [bar(100, 110, 90, gm, 100), bar(100, 110, 90, gm, 100)]
    assert m.abdi_ranaldo_spread(bars) == pytest.approx(0.0, abs=1e-9)


def test_abdi_ranaldo_hand_computed_positive():
    # (c0-eta0)=0.01, (c0-eta1)=0.01 → term=1e-4, mean=1e-4, S=2*sqrt(1e-4)=0.02
    b0 = bar(100, 101, 99, 101, 100)   # c0-eta0 = ln101 - (ln101+ln99)/2 = 0.01001...
    b1 = bar(100, 101, 99, 99, 100)    # eta1 = same mid → c0-eta1 = 0.01001...
    got = m.abdi_ranaldo_spread([b0, b1])
    c0 = math.log(101); eta = (math.log(101) + math.log(99)) / 2
    expected = 2.0 * math.sqrt((c0 - eta) ** 2)
    assert got == pytest.approx(expected, abs=1e-9)
    assert got == pytest.approx(0.0200, abs=1e-3)


def test_spread_estimate_is_max_of_cs_and_ar():
    bars = [bar(100, 101, 99, 101, 100), bar(100, 101, 99, 99, 100)]
    cs = m.corwin_schultz_spread(bars)
    ar = m.abdi_ranaldo_spread(bars)
    assert m.spread_estimate(bars) == pytest.approx(max(cs, ar))


# ── Amihud ──────────────────────────────────────────────────────────

def test_amihud_hand_computed():
    # bar0 seeds prev_close=100; bar1: r=|110-100|/100=0.1, $vol=110*100=11000 → 0.1/11000
    bars = [bar(100, 100, 100, 100, 100), bar(100, 111, 100, 110, 100)]
    assert m.amihud_illiq(bars) == pytest.approx(0.1 / 11000.0, rel=1e-9)


def test_amihud_larger_for_thinner_dollar_volume():
    thin = [bar(100, 100, 100, 100, 10), bar(100, 111, 100, 110, 10)]
    thick = [bar(100, 100, 100, 100, 10000), bar(100, 111, 100, 110, 10000)]
    assert m.amihud_illiq(thin) > m.amihud_illiq(thick)


def test_amihud_none_when_no_returns():
    assert m.amihud_illiq([bar(100, 100, 100, 100, 100)]) is None


# ── Effort vs Result (Wyckoff) ──────────────────────────────────────

def test_evr_bar_midpoint():
    # (|1|/1) / (200/100) = 1 / 2 = 0.5
    assert m.evr_bar(1.0, 1.0, 200.0, 100.0) == pytest.approx(0.5)


def test_evr_bar_absorption_low_value_on_high_volume():
    # big volume (4x avg), tiny result → very low EvR = absorption
    assert m.evr_bar(0.1, 1.0, 400.0, 100.0) == pytest.approx(0.025)


def test_evr_bar_high_value_on_result_without_volume():
    # big result, below-average volume → high EvR = genuine move
    assert m.evr_bar(3.0, 1.0, 50.0, 100.0) == pytest.approx(6.0)


def test_evr_bar_none_on_zero_atr_or_zero_volma():
    assert m.evr_bar(1.0, 0.0, 100.0, 100.0) is None
    assert m.evr_bar(1.0, 1.0, 100.0, 0.0) is None


def test_atr_simple_true_range_mean():
    # bars with TR: first bar TR = h-l = 2; second uses prev close
    bars = [bar(10, 11, 9, 10, 100), bar(10, 12, 10, 11, 100)]
    # TR0 = 11-9 = 2 ; TR1 = max(12-10, |12-10|, |10-10|) = 2 → mean = 2
    assert m.atr(bars, period=14) == pytest.approx(2.0)


def test_effort_vs_result_series_last_value_matches_manual():
    bars = [bar(10, 11, 9, 10, 100)] * 5 + [bar(10, 12, 8, 10, 400)]
    series = m.effort_vs_result(bars, atr_period=14, vol_period=20)
    # last bar: ΔP=|10-10|=0 → result 0 → EvR 0
    assert series[-1] == pytest.approx(0.0)


def test_effort_vs_result_body_move_produces_positive():
    bars = [bar(10, 11, 9, 10, 100)] * 5 + [bar(10, 12, 9, 12, 100)]
    series = m.effort_vs_result(bars, atr_period=14, vol_period=20)
    assert series[-1] is not None and series[-1] > 0


# ── bundle / empties ────────────────────────────────────────────────

def test_compute_all_keys_present_and_empty_safe():
    out = m.compute_all([])
    assert out["n_bars"] == 0
    for k in ("bar_pressure", "corwin_schultz_spread", "abdi_ranaldo_spread", "spread_estimate", "amihud_illiq", "evr_last"):
        assert out[k] is None


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
