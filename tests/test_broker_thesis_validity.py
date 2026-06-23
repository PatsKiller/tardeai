#!/usr/bin/env python3
"""Tests for broker_thesis_validity.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from datetime import datetime, timedelta, timezone

from broker_thesis_validity import attach_thesis_validity, compute_thesis_validity


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


def test_stale_db_price_skips_live_rr():
    old = (datetime.now(timezone.utc) - timedelta(minutes=45)).isoformat()
    row = {
        "proposed_entry": 100,
        "proposed_stop": 95,
        "proposed_target1": 115,
        "current_price": 101,
        "updated_at": old,
        "strategy_id": "momentum_scalp",
    }
    attach_thesis_validity(row)
    tv = row["thesis_validity"]
    assert row["price_stale"] is True
    assert tv["zone_status"] == "stale_price"
    assert tv["current_rr"] is None
    assert tv["current_price"] == 101


def test_fresh_refresh_bypasses_stale():
    row = {
        "proposed_entry": 100,
        "proposed_stop": 95,
        "proposed_target1": 115,
        "current_price": 101,
        "updated_at": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
        "refreshed_at": datetime.now(timezone.utc).isoformat()[:19],
        "quote_provider": "schwab",
        "strategy_id": "momentum_scalp",
    }
    attach_thesis_validity(row)
    assert row["price_stale"] is False
    assert row["thesis_validity"]["current_rr"] is not None


if __name__ == "__main__":
    test_comfortable_inside_band()
    test_at_risk_above_band()
    test_invalid_below_stop()
    test_stale_db_price_skips_live_rr()
    test_fresh_refresh_bypasses_stale()
    print("OK")