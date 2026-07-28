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


def test_signal_projection_bare_trigger_stays_a_lane_event_not_a_named_setup():
    # Defect 3 — a bare lane=TRIGGER with NO primary_setup_id/label must NOT be fabricated as a named
    # canonical setup. It stays a LANE event: unclassified identity, empty matched arrays, no setup id.
    row = {"id": 42, "symbol": "TBPH", "lane": "TRIGGER", "ign_score": 71, "setup_state": None,
           "primary_setup_id": None, "primary_setup_label": None, "matched_setup_labels": None,
           "matched_setup_ids": None, "market_session": "REGULAR",
           "data_tier": "T0", "dcf": 0.4, "rvol_tod": 8.4, "profile_source": "per_symbol",
           "entry_ref": 16.98, "stop_ref": 16.97, "r_dollars": 0.13, "stop_dist_bps": 380,
           "gate_result": "PASS", "gate_reasons": {"rr": 2.8}, "subscores": {"v_rvol": 0.88, "v_burst": 0.81},
           "confirmation_labels": ["VWAP_ALIGNED"], "setup_fail_reasons": None}
    s = _map_ignition_row_to_signal(row)
    assert s["state"] == "TRIGGERED"                  # TRIGGER lane → FSM TRIGGERED state
    assert s["lane"] == "TRIGGER"                     # lane preserved…
    assert s["primarySetupLabel"] != "IGNITION BREAKOUT"          # …NEVER fabricated as a named setup
    assert s["displayEventLabel"] == "IGN TRIGGER — SETUP UNCLASSIFIED"
    assert s["setupIdentityState"] == "UNRESOLVED"
    assert "primarySetupId" not in s                  # no canonical id synthesized
    assert s["matchedSetupLabels"] == [] and "matchedSetupIds" not in s   # matched arrays empty
    assert s["executionEligibility"] == "SETUP_NOT_FIRED"   # not FIRED → not eligible
    assert s["subscores"]["v_rvol"] == 88             # scaled 0-1 → 0-100
    assert s["entryRef"] == 16.98 and s["stopBps"] == 380 and s["legToR"] == 2.8
    assert "submitOrder" not in s and "orderIntent" not in s   # no order fields


def test_signal_projection_canonical_ignition_requires_its_setup_id():
    # A canonical IGNITION BREAKOUT only when the setup ID resolves AND carries its registry label.
    row = {"id": 43, "symbol": "TBPH", "lane": "TRIGGER", "ign_score": 71, "setup_state": "FIRED",
           "primary_setup_id": "SCALP_IGNITION_BREAKOUT_V1", "primary_setup_label": "IGNITION BREAKOUT",
           "matched_setup_ids": ["SCALP_IGNITION_BREAKOUT_V1"], "matched_setup_labels": ["IGNITION BREAKOUT"],
           "registry_hash": "sha256:abc", "gate_result": "PASS", "entry_ref": 16.98, "stop_ref": 16.90,
           "gate_reasons": {"stop_validation": {"stop_validation": "PASS"}}, "subscores": {}}
    s = _map_ignition_row_to_signal(row)
    assert s["primarySetupLabel"] == "IGNITION BREAKOUT"
    assert s["setupIdentityState"] == "RESOLVED"
    assert s["primarySetupId"] == "SCALP_IGNITION_BREAKOUT_V1"
    assert s["executionEligibility"] == "SIMULATION_ELIGIBLE"   # FIRED + gate PASS + id + hash + stop PASS


def test_signal_projection_canonical_vwap_pullback_stays_itself():
    row = {"id": 44, "symbol": "AAA", "lane": "IGN_60", "ign_score": 60, "setup_state": "FIRED",
           "primary_setup_id": "SCALP_VWAP_PULLBACK_V1", "primary_setup_label": "VWAP PULLBACK",
           "matched_setup_labels": ["VWAP PULLBACK"], "gate_result": "PASS", "subscores": {}}
    s = _map_ignition_row_to_signal(row)
    assert s["primarySetupLabel"] == "VWAP PULLBACK" and s["setupIdentityState"] == "RESOLVED"


def test_signal_projection_missing_gate_defers_never_passes():
    # Defect 1 — a NULL/missing gate maps to DEFER, never PASS; a FIRED row with DEFER is not eligible.
    row = {"id": 45, "symbol": "BBB", "lane": "IGN_60", "ign_score": 60, "setup_state": "FIRED",
           "primary_setup_id": "SCALP_VWAP_PULLBACK_V1", "primary_setup_label": "VWAP PULLBACK",
           "gate_result": None, "subscores": {}, "entry_ref": 5.0, "stop_ref": 4.9,
           "registry_hash": "sha256:x"}
    s = _map_ignition_row_to_signal(row)
    assert s["gateDecision"] == "DEFER"
    assert s["executionEligibility"] == "GATE_NOT_EVALUATED"


def test_signal_projection_scanner_style_row_never_acquires_setup_identity():
    # A scanner-ish row (no setup id/label, non-trigger lane) never gets a named setup-fire label or id.
    row = {"id": 46, "symbol": "CCC", "lane": "IGN_45", "ign_score": 45, "setup_state": None,
           "primary_setup_id": None, "primary_setup_label": None, "subscores": {}}
    s = _map_ignition_row_to_signal(row)
    assert s["setupIdentityState"] == "UNRESOLVED"
    assert "primarySetupId" not in s and s["matchedSetupLabels"] == []
    assert s["displayEventLabel"] == "IGN_45"


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
