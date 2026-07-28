#!/usr/bin/env python3
"""ActiveTrader permission queue: read-only, honest, and account unbound."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from active_trader.read_http import dispatch, ACTIVE_TRADER_PREFIX  # noqa: E402
from active_trader.read_api import ReadOnlyActiveTraderAPI, _map_ignition_row_to_signal  # noqa: E402

API = ReadOnlyActiveTraderAPI()
HONEST_STATES = {"API_UNAVAILABLE", "EMPTY_LIVE_QUEUE", "DATA_STALE", "LIVE_DATA"}


def test_permission_queue_read_only_zero_authority_and_unbound():
    status, body = dispatch(API, "GET", f"{ACTIVE_TRADER_PREFIX}/permission-queue")
    assert status == 200
    assert body["read_only"] is True and body["write"] is False and body["auto_route"] is False
    assert body["mode"] == "REVIEW_ONLY"
    assert body["account_binding_state"] == "UNBOUND"
    assert body["account_capability_source"] == "NOT_CONFIGURED"
    assert body["accounts"] == []
    assert all(value is False for value in body["authority"].values())


def test_permission_queue_strips_legacy_environment_categories():
    _, body = dispatch(API, "GET", f"{ACTIVE_TRADER_PREFIX}/permission-queue")
    assert body["posture"] == {
        "account_binding": "UNBOUND",
        "account_capability_source": "NOT_CONFIGURED",
        "execution_routes": False,
        "order_path": False,
        "final_submit_present": False,
        "automation": "none_wired",
    }
    for signal in body["signals"]:
        assert signal["mode"] == "REVIEW_ONLY"
        assert "executionEligibility" not in signal


def test_data_state_is_honest_and_distinct_never_sample():
    _, body = dispatch(API, "GET", f"{ACTIVE_TRADER_PREFIX}/permission-queue")
    assert body["data_state"] in HONEST_STATES
    assert body["is_sample"] is False
    assert "scalp_ignition_events" in body["source"] and "trade_ai_scans" in body["source"]
    assert "live_scan" not in body
    assert "engine_status" in body
    assert "registry_hash" in body and "generated_at" in body


def test_signal_projection_bare_trigger_stays_a_lane_event_not_a_named_setup():
    row = {
        "id": 42, "symbol": "TBPH", "lane": "TRIGGER", "ign_score": 71, "setup_state": None,
        "primary_setup_id": None, "primary_setup_label": None, "matched_setup_labels": None,
        "matched_setup_ids": None, "market_session": "REGULAR", "data_tier": "T0", "dcf": 0.4,
        "rvol_tod": 8.4, "profile_source": "per_symbol", "entry_ref": 16.98, "stop_ref": 16.97,
        "r_dollars": 0.13, "stop_dist_bps": 380, "gate_result": "PASS",
        "gate_reasons": {"rr": 2.8}, "subscores": {"v_rvol": 0.88, "v_burst": 0.81},
        "confirmation_labels": ["VWAP_ALIGNED"], "setup_fail_reasons": None,
    }
    signal = _map_ignition_row_to_signal(row)
    assert signal["state"] == "TRIGGERED"
    assert signal["lane"] == "TRIGGER"
    assert signal["primarySetupLabel"] != "IGNITION BREAKOUT"
    assert signal["displayEventLabel"] == "IGN TRIGGER — SETUP UNCLASSIFIED"
    assert signal["setupIdentityState"] == "UNRESOLVED"
    assert "primarySetupId" not in signal
    assert signal["matchedSetupLabels"] == [] and "matchedSetupIds" not in signal
    assert signal["subscores"]["v_rvol"] == 88
    assert signal["entryRef"] == 16.98 and signal["stopBps"] == 380 and signal["legToR"] == 2.8
    assert "submitOrder" not in signal and "orderIntent" not in signal


def test_signal_projection_canonical_ignition_requires_its_setup_id():
    row = {
        "id": 43, "symbol": "TBPH", "lane": "TRIGGER", "ign_score": 71, "setup_state": "FIRED",
        "primary_setup_id": "SCALP_IGNITION_BREAKOUT_V1", "primary_setup_label": "IGNITION BREAKOUT",
        "matched_setup_ids": ["SCALP_IGNITION_BREAKOUT_V1"], "matched_setup_labels": ["IGNITION BREAKOUT"],
        "registry_hash": "sha256:abc", "gate_result": "PASS", "entry_ref": 16.98, "stop_ref": 16.90,
        "gate_reasons": {"stop_validation": {"stop_validation": "PASS"}}, "subscores": {},
    }
    signal = _map_ignition_row_to_signal(row)
    assert signal["primarySetupLabel"] == "IGNITION BREAKOUT"
    assert signal["setupIdentityState"] == "RESOLVED"
    assert signal["primarySetupId"] == "SCALP_IGNITION_BREAKOUT_V1"


def test_signal_projection_canonical_vwap_pullback_stays_itself():
    row = {
        "id": 44, "symbol": "AAA", "lane": "IGN_60", "ign_score": 60, "setup_state": "FIRED",
        "primary_setup_id": "SCALP_VWAP_PULLBACK_V1", "primary_setup_label": "VWAP PULLBACK",
        "matched_setup_labels": ["VWAP PULLBACK"], "gate_result": "PASS", "subscores": {},
    }
    signal = _map_ignition_row_to_signal(row)
    assert signal["primarySetupLabel"] == "VWAP PULLBACK"
    assert signal["setupIdentityState"] == "RESOLVED"


def test_signal_projection_missing_gate_defers_never_passes():
    row = {
        "id": 45, "symbol": "BBB", "lane": "IGN_60", "ign_score": 60, "setup_state": "FIRED",
        "primary_setup_id": "SCALP_VWAP_PULLBACK_V1", "primary_setup_label": "VWAP PULLBACK",
        "gate_result": None, "subscores": {}, "entry_ref": 5.0, "stop_ref": 4.9,
        "registry_hash": "sha256:x",
    }
    signal = _map_ignition_row_to_signal(row)
    assert signal["gateDecision"] == "DEFER"


def test_signal_projection_scanner_style_row_never_acquires_setup_identity():
    row = {
        "id": 46, "symbol": "CCC", "lane": "IGN_45", "ign_score": 45, "setup_state": None,
        "primary_setup_id": None, "primary_setup_label": None, "subscores": {},
    }
    signal = _map_ignition_row_to_signal(row)
    assert signal["setupIdentityState"] == "UNRESOLVED"
    assert "primarySetupId" not in signal and signal["matchedSetupLabels"] == []
    assert signal["displayEventLabel"] == "IGN_45"


def test_signal_projection_veto_row_carries_reason():
    row = {
        "id": 7, "symbol": "X", "lane": "IGN_60", "ign_score": 61,
        "setup_state": "INVALIDATED", "gate_result": "VETO", "subscores": {},
        "setup_fail_reasons": {"g": "SPREAD_TOO_WIDE"},
    }
    signal = _map_ignition_row_to_signal(row)
    assert signal["state"] == "VETOED" and signal["vetoReason"] == "SPREAD_TOO_WIDE"


def test_get_only():
    status, body = dispatch(API, "POST", f"{ACTIVE_TRADER_PREFIX}/permission-queue")
    assert status == 405 and body["write"] is False


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
