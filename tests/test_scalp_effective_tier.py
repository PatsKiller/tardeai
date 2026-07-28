#!/usr/bin/env python3
"""Defect 6 — persisted data_tier is honest/config-driven, defaults T0, promotion is explicit."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

pytest.importorskip("requests")   # scalp_shadow_logger's transitive import
import scalp_shadow_logger as L    # noqa: E402

LADDER = {"T0": 0.4, "T2": 1.0}


def test_defaults_to_t0():
    assert L.effective_data_tier({"data_tiers": {"dcf": LADDER}}) == "T0"

def test_empty_config_defaults_t0():
    assert L.effective_data_tier({}) == "T0"

def test_promotion_via_active_tier():
    assert L.effective_data_tier({"data_tiers": {"active_tier": "T2", "dcf": LADDER}}) == "T2"

def test_promotion_via_t2_feeds_scoring():
    assert L.effective_data_tier({"data_tiers": {"t2": {"feeds_scoring": True}, "dcf": LADDER}}) == "T2"

def test_promotion_via_top_level_t2_feeds_scoring():
    assert L.effective_data_tier({"t2": {"feeds_scoring": True}, "data_tiers": {"dcf": LADDER}}) == "T2"

def test_promotion_without_ladder_fails_closed_to_t0():
    # promoted, but the dcf/slippage ladder has no T2 → fail closed to T0 (never emit an undefined tier)
    assert L.effective_data_tier({"data_tiers": {"active_tier": "T2", "dcf": {"T0": 0.4}}}) == "T0"

def test_entitlement_or_feed_up_does_not_promote():
    # a live feed/entitlement flag is NOT promotion — only explicit config promotes
    cfg = {"data_tiers": {"dcf": LADDER}, "moomoo": {"opend_up": True}, "entitlement": "AVAILABLE_REALTIME"}
    assert L.effective_data_tier(cfg) == "T0"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
