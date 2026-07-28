#!/usr/bin/env python3
"""Layer A named-setup detectors — deterministic per-setup positive/negative cases + orchestration
(multi-match retention, deterministic primary, session/window gate, fail-closed data). SHADOW; no order
path; the FSM is REUSED (not duplicated) for micro/ignition."""
from __future__ import annotations

import sys
from datetime import time
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import scalp_setup_detectors as det   # noqa: E402
import scalp_setup_registry as sreg   # noqa: E402

CFG = yaml.safe_load((ROOT / "config" / "scalp_signal_engine.yaml").read_text())
REG = sreg.load_registry()


def bar(o, h, l, c, v, m=None):
    d = {"o": o, "h": h, "l": l, "c": c, "v": v}
    if m is not None:
        d["m"] = m
    return d


# ── L2 MOMENTUM: book required, fail-closed, flip invalidates ──
def test_l2_unavailable_without_book():
    r = det.detect_l2_momentum({"bars": []}, CFG)
    assert r["state"] == det.DATA_UNAVAILABLE
    assert "L2_ENTITLEMENT_OR_BOOK_UNAVAILABLE" in r["fail_reasons"]

def test_l2_fires_on_full_fresh_book():
    book = {"catalyst_gap": True, "early_volume": True, "consolidation": True,
            "stacking": "bid", "break": True, "bid_lifting": True, "flip": False}
    r = det.detect_l2_momentum({"bars": [], "book": book}, CFG)
    assert r["state"] == det.FIRED and r["mandatory_satisfied"] == 5

def test_l2_stacking_without_break_is_armed_not_fired():
    book = {"catalyst_gap": True, "early_volume": True, "consolidation": True,
            "stacking": "bid", "break": False, "bid_lifting": False}
    r = det.detect_l2_momentum({"bars": [], "book": book}, CFG)
    assert r["state"] == det.ARMED and r["state"] != det.FIRED

def test_l2_book_flip_invalidates():
    book = {"catalyst_gap": True, "early_volume": True, "consolidation": True,
            "stacking": "bid", "break": True, "bid_lifting": True, "flip": True}
    r = det.detect_l2_momentum({"bars": [], "book": book}, CFG)
    assert r["state"] == det.INVALIDATED


# ── PREMARKET MOMENTUM: fail-closed without premarket RVOL denominator ──
def test_premarket_unavailable_without_pm_rvol_profile():
    ctx = {"bars": [bar(10, 10.2, 9.9, 10.1, 5000)], "premarket_vwap": 10.0,
           "premarket_structure": {"high": 10.05}, "premarket_rvol_tod": None}
    r = det.detect_premarket_momentum(ctx, CFG)
    assert r["state"] == det.DATA_UNAVAILABLE
    assert "PREMARKET_RVOL_PROFILE_UNAVAILABLE" in r["fail_reasons"]

def test_premarket_fires_with_full_premarket_inputs():
    ctx = {"bars": [bar(10, 10.3, 9.95, 10.25, 8000)], "premarket_vwap": 10.0,
           "premarket_structure": {"high": 10.10}, "premarket_rvol_tod": 6.0,
           "premarket_building_volume": True}
    r = det.detect_premarket_momentum(ctx, CFG)
    assert r["state"] == det.FIRED and r["mandatory_satisfied"] == 4


# ── 15M ORB: regular-session opening range only, close outside + volume ──
def _orb_bars(breakout_close, breakout_vol):
    b = [bar(10, 10.1, 9.95, 10.0, 1000, m=i) for i in range(15)]     # 09:30..09:44 range 9.95-10.10
    b.append(bar(10.0, breakout_close + 0.05, 9.98, breakout_close, breakout_vol, m=16))  # ~09:46 bar
    return b

def test_orb_fires_on_close_above_range_with_volume_and_alignment():
    ctx = {"bars": _orb_bars(10.3, 5000), "market_aligned": True}
    r = det.detect_orb_15(ctx, CFG)
    assert r["state"] == det.FIRED

def test_orb_insufficient_breakout_volume_does_not_fire():
    ctx = {"bars": _orb_bars(10.3, 500), "market_aligned": True}   # low vol
    r = det.detect_orb_15(ctx, CFG)
    assert r["state"] != det.FIRED and "insufficient_breakout_volume" in r["fail_reasons"]

def test_orb_excludes_premarket_bars_from_range():
    bars = [bar(9, 9.5, 8.5, 9.0, 1000, m=-30)] + _orb_bars(10.3, 5000)   # a premarket bar (m<0)
    r = det.detect_orb_15({"bars": bars, "market_aligned": True}, CFG)
    # range must be the regular 9.95-10.10, not widened by the premarket 8.5-9.5 bar
    assert r["evidence"]["opening_range"]["low"] >= 9.9

def test_orb_market_misalignment_refuses_when_required():
    ctx = {"bars": _orb_bars(10.3, 5000), "market_aligned": False}
    r = det.detect_orb_15(ctx, CFG)
    assert r["state"] != det.FIRED and "market_not_aligned" in r["fail_reasons"]


# ── VWAP REVERSION vs PULLBACK: never mislabel ──
def test_vwap_reversion_fires_when_stretched_and_reverting():
    b = [bar(100, 100.1, 99.9, 100.0, 1000) for _ in range(14)]
    b.append(bar(100, 100.7, 100.0, 100.65, 200))    # prev: stretched well above vwap~100
    b.append(bar(100.65, 100.66, 100.3, 100.35, 300))  # cur: reverting down toward vwap
    r = det.detect_vwap_reversion({"bars": b}, CFG)
    assert r["state"] == det.FIRED and r["evidence"]["stretched"]

def test_ordinary_pullback_is_not_labeled_reversion():
    b = [bar(100, 100.1, 99.9, 100.0, 1000) for _ in range(14)]
    b.append(bar(100, 100.15, 99.98, 100.1, 200))    # only ~0.5 ATR from vwap — not stretched
    b.append(bar(100.1, 100.12, 100.0, 100.05, 300))
    r = det.detect_vwap_reversion({"bars": b}, CFG)
    assert r["state"] != det.FIRED and "not_stretched_from_vwap" in r["fail_reasons"]

def test_vwap_pullback_continuation_fires():
    # uptrend, pullback toward vwap on declining volume, then resume
    b = [bar(100, 100.6, 99.9, 100.5, 3000), bar(100.5, 101.1, 100.4, 101.0, 3000),
         bar(101.0, 101.6, 100.9, 101.5, 3000), bar(101.5, 101.7, 101.2, 101.3, 1200),
         bar(101.3, 101.4, 101.0, 101.1, 800), bar(101.1, 101.6, 101.0, 101.55, 2600)]
    r = det.detect_vwap_pullback({"bars": b, "trend": "up"}, CFG)
    assert r["state"] == det.FIRED

def test_vwap_pullback_rising_pullback_volume_refuses():
    b = [bar(100, 100.6, 99.9, 100.5, 1000), bar(100.5, 101.1, 100.4, 101.0, 1000),
         bar(101.0, 101.6, 100.9, 101.5, 1000), bar(101.5, 101.7, 101.2, 101.3, 3000),
         bar(101.3, 101.4, 101.0, 101.1, 5000), bar(101.1, 101.6, 101.0, 101.55, 2600)]
    r = det.detect_vwap_pullback({"bars": b, "trend": "up"}, CFG)
    assert r["state"] != det.FIRED and "pullback_volume_not_declining" in r["fail_reasons"]


# ── MICRO PULLBACK / IGNITION reuse the FSM (controlled result) ──
def _mock_fsm(monkeypatch, fired_on_current=True, reject_reason=None):
    def fake_run(bars, cfg):
        cur = len(bars) - 1
        events = []
        if fired_on_current:
            events = [{"fire_idx": cur, "outcome": "TRIGGERED", "entry": 5.0, "stop": 4.9, "r_dollars": 0.1}]
        elif reject_reason:
            events = [{"fire_idx": cur, "outcome": "REJECT", "reason": reject_reason}]
        return {"events": events, "trace": ["ARMED"], "macd_hist_5m": None}
    monkeypatch.setattr(det.tfsm, "run_trigger_engine", fake_run)
    monkeypatch.setattr(det.tfsm, "triggered_fires",
                        lambda res: [e for e in res["events"] if e.get("outcome") == "TRIGGERED"])

def test_micro_pullback_fires_on_fsm_trigger(monkeypatch):
    _mock_fsm(monkeypatch, fired_on_current=True)
    r = det.detect_micro_pullback({"bars": [bar(5, 5.1, 4.9, 5.05, 100)] * 3}, CFG)
    assert r["state"] == det.FIRED and r["evidence"]["fsm_reused"] is True

def test_micro_pullback_no_chase_reject_does_not_fire(monkeypatch):
    _mock_fsm(monkeypatch, fired_on_current=False, reject_reason="no_chase")
    r = det.detect_micro_pullback({"bars": [bar(5, 5.1, 4.9, 5.05, 100)] * 3}, CFG)
    assert r["state"] != det.FIRED and "reject:no_chase" in r["fail_reasons"]

def test_ignition_requires_trigger_and_ign_lane(monkeypatch):
    _mock_fsm(monkeypatch, fired_on_current=True)
    fired = det.detect_ignition_breakout({"bars": [bar(5, 5.1, 4.9, 5.05, 100)] * 3, "ign_lane": "IGN_60", "ign_score": 62}, CFG)
    assert fired["state"] == det.FIRED
    below = det.detect_ignition_breakout({"bars": [bar(5, 5.1, 4.9, 5.05, 100)] * 3, "ign_lane": "BELOW", "ign_score": 30}, CFG)
    assert below["state"] != det.FIRED and "ign_below_lane" in below["fail_reasons"]


# ── orchestration: multi-match, deterministic primary, session gate, lane != setup ──
def _force(monkeypatch, **states):
    """Monkeypatch chosen detectors to return a fixed state; others return SCANNING."""
    def make(setup_id, st, sat):
        return lambda ctx, cfg: det._res(setup_id, st, sat[0], sat[1])
    for sid in list(det._DETECTORS):
        st = states.get(sid, det.SCANNING)
        sat = (5, 5) if st == det.FIRED else (0, 5)
        monkeypatch.setitem(det._DETECTORS, sid, make(sid, st, sat))

def test_detect_retains_all_matches_and_multi_flag(monkeypatch):
    _force(monkeypatch, SCALP_ORB_15_BREAKOUT_V1=det.FIRED, SCALP_MICRO_PULLBACK_V1=det.FIRED)
    out = det.detect_setups({"bars": []}, CFG, time(10, 0), REG)
    assert set(out["matched_setup_ids"]) == {"SCALP_ORB_15_BREAKOUT_V1", "SCALP_MICRO_PULLBACK_V1"}
    assert out["multi_setup"] is True and out["setup_state"] == det.FIRED

def test_primary_is_deterministic_by_registry_rules(monkeypatch):
    # ORB (family rank 60) beats MICRO (45) at equal tier/criteria
    _force(monkeypatch, SCALP_ORB_15_BREAKOUT_V1=det.FIRED, SCALP_MICRO_PULLBACK_V1=det.FIRED)
    out = det.detect_setups({"bars": []}, CFG, time(10, 0), REG)
    assert out["primary_setup_id"] == "SCALP_ORB_15_BREAKOUT_V1"
    assert out["primary_setup_label"] == "15M ORB"

def test_session_gate_downgrades_fire_outside_window(monkeypatch):
    # ORB "fires" but at 11:00, outside its 09:45-10:30 window → OUTSIDE_WINDOW, not matched
    _force(monkeypatch, SCALP_ORB_15_BREAKOUT_V1=det.FIRED)
    out = det.detect_setups({"bars": []}, CFG, time(11, 0), REG)
    assert "SCALP_ORB_15_BREAKOUT_V1" not in out["matched_setup_ids"]
    assert out["setup_evidence"]["SCALP_ORB_15_BREAKOUT_V1"]["state"] == det.OUTSIDE_WINDOW

def test_noon_cutoff_blocks_new_fire(monkeypatch):
    _force(monkeypatch, SCALP_IGNITION_BREAKOUT_V1=det.FIRED)
    out = det.detect_setups({"bars": []}, CFG, time(12, 30), REG)
    assert out["matched_setup_ids"] == []

def test_row_carries_registry_hash_and_lane_is_not_setup(monkeypatch):
    _force(monkeypatch, SCALP_MICRO_PULLBACK_V1=det.FIRED)
    out = det.detect_setups({"bars": []}, CFG, time(10, 0), REG)
    assert out["registry_hash"].startswith("sha256:")
    assert "IGN_60" not in out["matched_setup_ids"]      # a lane is never a setup id


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
