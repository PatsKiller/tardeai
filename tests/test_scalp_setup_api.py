#!/usr/bin/env python3
"""Scalp setup API contract — read-only, GET-only, zero-authority, backward compatible. The registry
endpoint exposes the 7 named setups + hash; setup-events fails closed to empty without a DB."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from active_trader.read_http import dispatch, ACTIVE_TRADER_PREFIX  # noqa: E402
from active_trader.read_api import ReadOnlyActiveTraderAPI          # noqa: E402

API = ReadOnlyActiveTraderAPI()


def test_setups_endpoint_returns_registry_read_only():
    status, body = dispatch(API, "GET", f"{ACTIVE_TRADER_PREFIX}/scalp/setups")
    assert status == 200
    assert body["read_only"] is True and body["write"] is False
    assert all(body["authority"][k] is False for k in body["authority"])
    reg = body["setup_registry"]
    assert reg["write_authority"] is False
    ids = {s["setup_id"] for s in reg["setups"]}
    assert {"SCALP_L2_MOMENTUM_V1", "SCALP_VWAP_PULLBACK_V1", "SCALP_VWAP_REVERSION_V1",
            "SCALP_ORB_15_BREAKOUT_V1", "SCALP_MICRO_PULLBACK_V1", "SCALP_PREMARKET_MOMENTUM_V1",
            "SCALP_IGNITION_BREAKOUT_V1"} <= ids
    assert reg["registry_hash"].startswith("sha256:")


def test_setup_events_endpoint_fails_closed_to_empty():
    status, body = dispatch(API, "GET", f"{ACTIVE_TRADER_PREFIX}/scalp/setup-events", {"limit": "10"})
    assert status == 200 and body["read_only"] is True
    assert isinstance(body["events"], list)          # empty ok when no DB / before migration
    assert body["count"] == len(body["events"])
    assert "MANUAL PAPER ONLY" in body["note"]


def test_scalp_endpoints_are_get_only():
    for suffix in ("scalp/setups", "scalp/setup-events"):
        status, body = dispatch(API, "POST", f"{ACTIVE_TRADER_PREFIX}/{suffix}")
        assert status == 405 and body["write"] is False


def test_backward_compatible_existing_endpoints_unchanged():
    for suffix in ("health", "status", "sessions", "near-ready"):
        status, _ = dispatch(API, "GET", f"{ACTIVE_TRADER_PREFIX}/{suffix}")
        assert status == 200
    # the discovery index advertises the new endpoints
    _, root = dispatch(API, "GET", ACTIVE_TRADER_PREFIX)
    assert any("scalp/setups" in e for e in root["endpoints"])


def test_lane_is_not_a_setup_in_api():
    _, body = dispatch(API, "GET", f"{ACTIVE_TRADER_PREFIX}/scalp/setups")
    ids = {s["setup_id"] for s in body["setup_registry"]["setups"]}
    for lane in ("IGN_60", "IGN_ACCEL", "TRIGGER"):
        assert lane not in ids


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
