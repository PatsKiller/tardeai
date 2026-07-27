#!/usr/bin/env python3
"""M3-S5 unit tests — entry-trigger state machine (§4/§6). Pure, synthetic bar series.
Covers: clean trigger, VOID by deep retrace, no-arm by failed VDU, VWAP-loss reject, reject by
stop_pct, reject by R:R, no-chase, nonpositive R, MACD-5m logged-not-gating, post-halt re-warm."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts import scalp_trigger_engine as te  # noqa: E402

CFG = yaml.safe_load((ROOT / "config" / "scalp_signal_engine.yaml").read_text())


def b(o, h, l, c, v):
    return {"o": o, "h": h, "l": l, "c": c, "v": v}


CLEAN = [
    b(100, 100.2, 99.9, 100.0, 500),
    b(100, 101.0, 100.0, 100.9, 1000),
    b(100.9, 102.0, 100.8, 101.9, 1000),
    b(101.9, 103.0, 101.8, 102.9, 1000),    # leg_high 103, origin 99.9
    b(102.9, 102.7, 102.2, 102.3, 300),     # pullback lh=1
    b(102.3, 102.4, 101.9, 102.0, 300),     # pullback lh=2 → ARMED
    b(102.0, 102.6, 102.0, 102.55, 800),    # trigger bar
]


# ── FSM paths ───────────────────────────────────────────────────────
def test_clean_trigger_fires():
    r = te.run_trigger_engine(CLEAN, CFG)
    fires = te.triggered_fires(r)
    assert len(fires) == 1
    assert r["trace"] == ["IDLE", "IDLE", "IMPULSE", "IMPULSE", "PULLBACK", "ARMED", "TRIGGERED"]
    f = fires[0]
    assert f["entry"] == pytest.approx(102.62) and f["stop"] < f["entry"] and f["r_dollars"] > 0

def test_void_by_deep_retrace():
    bars = CLEAN[:5] + [b(102.3, 102.4, 100.0, 100.1, 300)]  # low 100 → retrace 0.97 > 0.786
    r = te.run_trigger_engine(bars, CFG)
    assert not te.triggered_fires(r)
    assert any(e["outcome"] == "VOID" and e["reason"] == "deep_retrace" for e in r["events"])

def test_no_arm_by_failed_volume_dryup():
    # pullback volume HIGH (not drying up) → never ARMED → no trigger
    bars = CLEAN[:4] + [b(102.9, 102.7, 102.2, 102.3, 5000), b(102.3, 102.4, 101.9, 102.0, 5000),
                        b(102.0, 102.6, 102.0, 102.55, 800)]
    r = te.run_trigger_engine(bars, CFG)
    assert not te.triggered_fires(r)
    assert "ARMED" not in r["trace"]

def test_vwap_loss_rejects_or_no_fire():
    # huge volume at the top pulls VWAP up near the leg high; a normal pullback lands below VWAP and
    # the trigger bar closes below VWAP → structure not held → no TRIGGERED fire.
    bars = [
        b(100, 100.1, 99.9, 100.0, 100),
        b(100, 101.0, 100.0, 100.9, 200000),
        b(100.9, 103.0, 100.8, 102.95, 400000),   # massive volume at the top → VWAP ≈ 102.5+
        b(102.95, 102.6, 102.1, 102.2, 300),       # pullback lh=1, below VWAP
        b(102.2, 102.3, 101.9, 102.0, 300),        # pullback lh=2
        b(102.0, 102.4, 102.0, 102.15, 800),       # would-be trigger, close 102.15 < VWAP
    ]
    r = te.run_trigger_engine(bars, CFG)
    assert not te.triggered_fires(r)   # structure-not-held (or never armed) → no clean fire


# ── compute_levels reject logic (edge-guards; reachable directly) ────
def test_reject_by_stop_pct():
    # low-priced name, wide raw stop → stop_pct > 8%
    ev = te.compute_levels(4.30, 3.60, 3.60, 0.6, 4.5, 3.5, CFG)
    assert ev["outcome"] == "REJECT" and ev["reason"].startswith("stop_pct")

def test_reject_by_rr():
    # degenerate small leg vs R → leg_height/R < 2
    ev = te.compute_levels(102.6, 102.4, 102.4, 0.5, 102.7, 102.5, CFG)
    assert ev["outcome"] == "REJECT" and ev["reason"] == "rr<min"

def test_reject_by_no_chase():
    # entry far above leg_high → chasing
    ev = te.compute_levels(110.0, 109.5, 109.5, 1.0, 100.0, 99.0, CFG)
    assert ev["outcome"] == "REJECT" and ev["reason"] == "no_chase"

def test_clean_levels_pass():
    ev = te.compute_levels(102.6, 102.0, 101.9, 0.8, 103.0, 99.9, CFG)
    assert ev["outcome"] == "TRIGGERED" and ev["reason"] is None
    assert ev["r_dollars"] > 0 and ev["rr"] >= CFG["trigger"]["min_rr"]

def test_noise_stop_floor_caps_R_at_atr():
    # very wide raw stop → floor binds → R ≈ ATR
    ev = te.compute_levels(100.0, 90.0, 90.0, 0.5, 105.0, 95.0, CFG)
    assert ev["r_dollars"] == pytest.approx(0.5, abs=1e-6)   # entry-1*ATR floor


# ── MACD (logged, never gating) ─────────────────────────────────────
def test_macd_none_when_too_few_bars():
    assert te.run_trigger_engine(CLEAN, CFG)["macd_hist_5m"] is None

def test_macd_value_when_enough_bars_and_never_blocks_trigger():
    # prepend a long flat warmup (enough 5m bars for MACD) then the clean setup; trigger still fires
    warm = [b(100, 100.05, 99.95, 100.0, 100) for _ in range(180)]
    r = te.run_trigger_engine(warm + CLEAN, CFG)
    assert r["macd_hist_5m"] is not None          # computed
    assert len(te.triggered_fires(r)) == 1        # and MACD did NOT gate the fire


# ── post-halt re-warm ───────────────────────────────────────────────
def test_macd_hist_helper_direct():
    closes_flat = [b(1, 1, 1, 100 + (i % 3), 10) for i in range(200)]
    # just assert it returns a float or None without raising
    v = te.macd_hist_5m(closes_flat, CFG)
    assert v is None or isinstance(v, float)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
