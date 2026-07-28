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


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
