#!/usr/bin/env python3
"""Tests for broker_thesis_validity.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from broker_thesis_validity import compute_thesis_validity


def test_comfortable_inside_band():
    tv = compute_thesis_validity(100, 95, 115, 100.5, strategy_id="momentum_scalp", drift_threshold_pct=5)
    assert tv["ok"]
    assert tv["zone_status"] in ("comfortable", "approaching")
    assert tv["valid_low"] <= 100.5 <= tv["valid_high"]


def test_at_risk_above_band():
    tv = compute_thesis_validity(100, 95, 110, 108, strategy_id="momentum_scalp", drift_threshold_pct=3, min_rr=2)
    assert tv["zone_status"] in ("at_risk", "invalid", "approaching")


def test_invalid_below_stop():
    tv = compute_thesis_validity(100, 95, 115, 94, strategy_id="momentum_scalp")
    assert tv["zone_status"] == "invalid"
    assert tv["zone_color"] == "red"


if __name__ == "__main__":
    test_comfortable_inside_band()
    test_at_risk_above_band()
    test_invalid_below_stop()
    print("OK")