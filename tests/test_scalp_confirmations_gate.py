#!/usr/bin/env python3
"""Layer B (confirmation overlays) + Layer C (universal execution-quality gate).
Confirmations are independent of setup identity and NEVER authorize a fire alone; the gate can veto any
setup with canonical outputs and never auto-markets."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import scalp_confirmations as sconf   # noqa: E402
import scalp_execution_gate as sgate  # noqa: E402

CFG = yaml.safe_load((ROOT / "config" / "scalp_signal_engine.yaml").read_text())
CONF = yaml.safe_load((ROOT / "config" / "scalp_confirmations.yaml").read_text())
OV, GATE = CONF["overlays"], CONF["gate"]


def bar(o, h, l, c, v):
    return {"o": o, "h": h, "l": l, "c": c, "v": v}


# ── Layer B: confirmations ──
def _uptrend(vol_last=6000):
    # >=12 rising bars above VWAP (so the 9-period EMA is evaluable); last bar high volume
    b = [bar(100 + i * 0.5, 100.6 + i * 0.5, 99.9 + i * 0.5, 100.5 + i * 0.5, 1000) for i in range(11)]
    b.append(bar(105.5, 106.2, 105.4, 106.1, vol_last))
    return b

def test_confirmations_are_directional_and_labeled():
    r = sconf.compute_confirmations({"bars": _uptrend(), "market_aligned": True, "catalyst_weight": 0.8}, CFG, OV)
    assert r["direction"] == "up"
    assert "VWAP_ALIGNED" in r["labels"] and "EMA_ALIGNED" in r["labels"]
    assert "MARKET_ALIGNED" in r["labels"] and "CATALYST_CONFIRMED" in r["labels"]
    assert "VOLUME_CONFIRMED" in r["labels"]
    assert r["confirmation_pass_count"] >= 4

def test_one_min_confluence_appears_with_enough_aligned_but_never_authorizes_fire():
    r = sconf.compute_confirmations({"bars": _uptrend(), "market_aligned": True, "catalyst_weight": 0.8}, CFG, OV)
    assert "ONE_MIN_CONFLUENCE" in r["labels"]
    assert r["authorizes_fire"] is False          # confirmations never fire on their own in v1

def test_l2_confirmed_only_from_actual_book():
    up = {"bars": _uptrend(), "book": {"stacking": "bid"}}
    assert "L2_CONFIRMED" in sconf.compute_confirmations(up, CFG, OV)["labels"]
    nobook = sconf.compute_confirmations({"bars": _uptrend()}, CFG, OV)
    assert "L2_CONFIRMED" not in nobook["labels"]   # not inferred without a book

def test_low_volume_is_not_volume_confirmed():
    r = sconf.compute_confirmations({"bars": _uptrend(vol_last=100)}, CFG, OV)
    assert "VOLUME_CONFIRMED" not in r["labels"]


# ── Layer C: universal execution gate ──
def _ok_ctx(**over):
    ctx = {"price": 10.0, "bar_volume": 8000, "spread_bps": 20, "data_tier": "T0", "data_age_sec": 5}
    ctx.update(over)
    return ctx

def test_gate_passes_on_clean_liquidity():
    r = sgate.evaluate_gate(_ok_ctx(), CFG, GATE)
    assert r["passed"] and r["result"] == "PASS" and r["labels"] == ["LIQUIDITY_SPREAD_PASS"]
    assert r["price_control"]["method"] == "LIMIT"     # never a market order

def test_gate_vetoes_wide_spread():
    r = sgate.evaluate_gate(_ok_ctx(spread_bps=500), CFG, GATE)
    assert not r["passed"] and "SPREAD_TOO_WIDE" in r["labels"] and "LIQUIDITY_SPREAD_FAIL" in r["labels"]

def test_gate_vetoes_stale_data():
    r = sgate.evaluate_gate(_ok_ctx(data_age_sec=10_000), CFG, GATE)
    assert not r["passed"] and "DATA_STALE" in r["reasons"]

def test_gate_vetoes_insufficient_volume():
    r = sgate.evaluate_gate(_ok_ctx(bar_volume=10), CFG, GATE)
    assert not r["passed"] and "INSUFFICIENT_VOLUME" in r["reasons"]

def test_gate_vetoes_halt():
    r = sgate.evaluate_gate(_ok_ctx(halted=True), CFG, GATE)
    assert not r["passed"] and "HALTED" in r["reasons"]

def test_gate_vetoes_participation_too_high():
    r = sgate.evaluate_gate(_ok_ctx(hypothetical_shares=5000), CFG, GATE)  # 5000/8000 = 62% > 10%
    assert not r["passed"] and "PARTICIPATION_TOO_HIGH" in r["reasons"]

def test_gate_price_control_unavailable_without_price():
    r = sgate.evaluate_gate(_ok_ctx(price=None), CFG, GATE)
    assert not r["passed"] and "PRICE_CONTROL_UNAVAILABLE" in r["reasons"]
    assert r["price_control"]["available"] is False


# ── Defect 2: deterministic minimum-stop floor (pure validator, config-driven) ──
def _sv(**kw):
    kw.setdefault("cfg", GATE)
    return sgate.validate_stop_reference(**kw)

def test_stop_floor_config_version_present():
    assert GATE["stop_floor"]["version"] == "scalp-stop-floor-v1"
    assert GATE["stop_floor"]["min_stop_ticks"] == 2

def test_stop_atai_5bp_below_tick_floor_vetoes():
    # ATAI-like: entry 7.18, stop 7.1764 → ~0.0036 (~5bp). Below the 2-tick floor (0.02) → VETO.
    r = _sv(entry_ref=7.18, stop_ref=7.1764, atr_1m=0.05, spread_bps=8, price=7.18)
    assert r["stop_validation"] == "VETO"
    assert "STOP_DISTANCE_BELOW_TICK_FLOOR" in r["reason_codes"]
    assert r["stop_distance_bps"] < 10

def test_stop_nuai_85bp_passes_with_supporting_evidence():
    # NUAI-like: entry 4.36, stop 4.3229 → ~0.0371 (~85bp). Clears tick/spread/vol floors → PASS.
    r = _sv(entry_ref=4.36, stop_ref=4.3229, atr_1m=0.08, spread_bps=12, price=4.36)
    assert r["stop_validation"] == "PASS"
    assert r["reason_codes"] == ["STOP_VALIDATION_PASS"]
    assert 80 < r["stop_distance_bps"] < 90

def test_stop_at_or_above_entry_is_direction_invalid():
    r = _sv(entry_ref=10.0, stop_ref=10.0, atr_1m=0.1, spread_bps=10, price=10.0)
    assert r["stop_validation"] == "VETO" and "STOP_DIRECTION_INVALID" in r["reason_codes"]

def test_stop_missing_reference_vetoes():
    r = _sv(entry_ref=10.0, stop_ref=None, atr_1m=0.1, spread_bps=10, price=10.0)
    assert r["stop_validation"] == "VETO" and "STOP_REFERENCE_MISSING" in r["reason_codes"]

def test_stop_missing_atr_still_validates_on_tick_and_spread():
    # No ATR → volatility floor skipped; a comfortably wide stop still PASSes on tick/spread floors.
    r = _sv(entry_ref=10.0, stop_ref=9.80, atr_1m=None, spread_bps=10, price=10.0)
    assert r["volatility_floor"] is None and r["stop_validation"] == "PASS"

def test_stop_missing_spread_still_validates_on_tick():
    r = _sv(entry_ref=10.0, stop_ref=9.90, atr_1m=0.02, spread_bps=None, price=10.0)
    assert r["spread_floor"] is None and r["stop_validation"] == "PASS"

def test_stop_sub_dollar_uses_finer_increment():
    # price < $1 → 0.0001 increment; a 3-tick stop (0.0003) clears the finer tick floor (0.0002) — it
    # would FAIL under the $1 penny rule (0.02), proving the sub-dollar increment is applied.
    r = _sv(entry_ref=0.50, stop_ref=0.4997, atr_1m=0.00005, spread_bps=None, price=0.50)
    assert r["price_increment"] == 0.0001 and r["tick_floor"] == 0.0002 and r["stop_validation"] == "PASS"

def test_stop_wide_spread_raises_floor_and_vetoes():
    # Wide spread dominates: spread_floor = 1.5 * (300bp * 10) = 1.5 * 0.30 = 0.45 > 0.10 actual → VETO.
    r = _sv(entry_ref=10.0, stop_ref=9.90, atr_1m=0.02, spread_bps=300, price=10.0)
    assert r["stop_validation"] == "VETO" and "STOP_DISTANCE_BELOW_SPREAD_FLOOR" in r["reason_codes"]

def test_stop_ordinary_valid_stop_passes():
    r = _sv(entry_ref=25.0, stop_ref=24.75, atr_1m=0.15, spread_bps=6, price=25.0)
    assert r["stop_validation"] == "PASS"

def test_stop_validator_never_modifies_inputs():
    r = _sv(entry_ref=7.18, stop_ref=7.1764, atr_1m=0.05, spread_bps=8, price=7.18)
    # the validator reports a required distance but NEVER rewrites the supplied entry/stop
    assert r["actual_stop_distance"] == round(7.18 - 7.1764, 6)
    assert "entry_ref" not in r and "stop_ref" not in r

def test_stop_fail_closed_when_no_floor_establishable():
    # Even with price None, entry still yields a tick floor via the fallback increment → not fail-closed.
    r = _sv(entry_ref=5.0, stop_ref=4.9, atr_1m=None, spread_bps=None, price=None, price_increment=None)
    assert r["tick_floor"] is not None
    # But if EVERY floor multiplier is disabled, no defensible floor exists → fail CLOSED to VETO.
    r2 = sgate.validate_stop_reference(
        entry_ref=5.0, stop_ref=4.9, atr_1m=None, spread_bps=None, price=None, price_increment=None,
        cfg={"stop_floor": {"min_stop_ticks": None, "min_stop_spread_multiple": None,
                            "min_stop_atr_multiple": None}})
    assert r2["stop_validation"] == "VETO" and "STOP_FLOOR_INPUT_UNAVAILABLE" in r2["reason_codes"]

def test_gate_includes_stop_validation_when_refs_present():
    ctx = _ok_ctx(entry_ref=7.18, stop_ref=7.1764, atr_1m=0.05)
    r = sgate.evaluate_gate(ctx, CFG, GATE)
    assert r["stop_validation"]["stop_validation"] == "VETO"     # gate carries the stop result…
    assert r["passed"] is True                                   # …but liquidity gate PASS is unaffected

def test_gate_omits_stop_validation_without_refs():
    r = sgate.evaluate_gate(_ok_ctx(), CFG, GATE)
    assert r["stop_validation"] is None                          # not computed without entry/stop refs


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
