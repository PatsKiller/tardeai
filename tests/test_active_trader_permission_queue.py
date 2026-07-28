#!/usr/bin/env python3
"""ActiveTrader permission-queue API — read-only, zero-authority, honest distinct data states, and a
faithful scalp_ignition_events → ScalpSignal projection (lane ≠ setup; no order fields)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from active_trader.read_http import dispatch, ACTIVE_TRADER_PREFIX          # noqa: E402
from active_trader.read_api import (ReadOnlyActiveTraderAPI,                # noqa: E402
                                    _map_ignition_row_to_signal, _ACTIVE_TRADER_ACCOUNTS)

API = ReadOnlyActiveTraderAPI()
HONEST_STATES = {"API_UNAVAILABLE", "EMPTY_LIVE_QUEUE", "DATA_STALE", "LIVE_DATA"}


def test_permission_queue_read_only_zero_authority():
    status, body = dispatch(API, "GET", f"{ACTIVE_TRADER_PREFIX}/permission-queue")
    assert status == 200
    assert body["read_only"] is True and body["write"] is False and body["auto_route"] is False
    assert body["mode"] == "MANUAL_PAPER_TEST_ONLY"
    assert all(v is False for v in body["authority"].values())


def test_data_state_is_honest_and_distinct_never_sample():
    _, body = dispatch(API, "GET", f"{ACTIVE_TRADER_PREFIX}/permission-queue")
    assert body["data_state"] in HONEST_STATES        # error/empty/live never collapsed
    assert body["is_sample"] is False                 # server NEVER returns a reference sample
    # actionable queue draws from BOTH engines (IGN TRIGGER + scanner GO); never a scanner dump
    assert "scalp_ignition_events" in body["source"] and "trade_ai_scans" in body["source"]
    assert "live_scan" not in body                     # no scanner dump in the queue payload
    assert "engine_status" in body                     # compact engine status instead
    assert "registry_hash" in body and "generated_at" in body


def test_posture_no_order_or_live_session():
    _, body = dispatch(API, "GET", f"{ACTIVE_TRADER_PREFIX}/permission-queue")
    p = body["posture"]
    assert p["order_path"] is False and p["live_routing"] is False
    assert p["live_session_enabled"] is False and p["final_submit_present"] is False
    assert p["automation"] == "none_wired"


def test_accounts_posture_matrix():
    _, body = dispatch(API, "GET", f"{ACTIVE_TRADER_PREFIX}/permission-queue")
    accts = {a["id"]: a for a in body["accounts"]}
    assert accts["alpaca-paper"]["eligible"] is True and accts["alpaca-paper"]["paper"] is True
    for aid in ("schwab-taxable", "alpaca-live", "moomoo"):   # live/data venues never eligible
        assert accts[aid]["eligible"] is False


def test_signal_projection_trigger_row():
    row = {"id": 42, "symbol": "TBPH", "lane": "TRIGGER", "ign_score": 71, "setup_state": None,
           "primary_setup_label": None, "matched_setup_labels": None, "market_session": "REGULAR",
           "data_tier": "T0", "dcf": 0.4, "rvol_tod": 8.4, "profile_source": "per_symbol",
           "entry_ref": 16.98, "stop_ref": 16.97, "r_dollars": 0.13, "stop_dist_bps": 380,
           "gate_result": "PASS", "gate_reasons": {"rr": 2.8}, "subscores": {"v_rvol": 0.88, "v_burst": 0.81},
           "confirmation_labels": ["VWAP_ALIGNED"], "setup_fail_reasons": None}
    s = _map_ignition_row_to_signal(row)
    assert s["state"] == "TRIGGERED"                  # TRIGGER lane → FSM TRIGGERED state
    assert s["lane"] == "TRIGGER"                     # lane preserved…
    assert s["primarySetupLabel"] == "IGNITION BREAKOUT"   # …and distinct from the setup label
    assert s["subscores"]["v_rvol"] == 88             # scaled 0-1 → 0-100
    assert s["entryRef"] == 16.98 and s["stopBps"] == 380 and s["legToR"] == 2.8
    assert "submitOrder" not in s and "orderIntent" not in s   # no order fields


def test_signal_projection_veto_row_carries_reason():
    row = {"id": 7, "symbol": "X", "lane": "IGN_60", "ign_score": 61, "setup_state": "INVALIDATED",
           "gate_result": "VETO", "subscores": {}, "setup_fail_reasons": {"g": "SPREAD_TOO_WIDE"}}
    s = _map_ignition_row_to_signal(row)
    assert s["state"] == "VETOED" and s["vetoReason"] == "SPREAD_TOO_WIDE"


def test_accounts_constant_shape():
    assert {a["venue"] for a in _ACTIVE_TRADER_ACCOUNTS} >= {"schwab", "alpaca_paper", "alpaca_live", "moomoo"}


def test_get_only():
    status, body = dispatch(API, "POST", f"{ACTIVE_TRADER_PREFIX}/permission-queue")
    assert status == 405 and body["write"] is False


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
