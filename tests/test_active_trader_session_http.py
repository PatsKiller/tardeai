#!/usr/bin/env python3
"""ActiveTrader SESSION CONTROL HTTP dispatcher — POST-capable, simulation-only, live disabled.
The full lifecycle runs in SIMULATION; LIVE activation is FEATURE_DISABLED; no envelope grants a live
or order path; the read plane is unaffected."""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import active_trader.session_control as sc   # noqa: E402
import active_trader.sim_execution as se     # noqa: E402
import active_trader.session_http as sh       # noqa: E402

PFX = "/api/v3/active-trader"


def _draft(now: float | None = None) -> dict:
    # real wall-clock timestamps — the HTTP dispatcher uses real `now`, so an epoch-relative
    # session would read as expired and never activate.
    now = time.time() if now is None else now
    return {
        "strategy": "momentum_scalp", "setup_ids": ["ms_pullback", "ms_break"], "setup_versions": ["v3", "v3"],
        "registry_hash": "reg-abc123", "brokers": ["SIM_BROKER"], "account_ids": ["ACC-1"],
        "symbol_list_or_universe_rule": "universe:premarket_movers", "session_start": now,
        "entry_cutoff": now + 3600, "expiry": now + 7200, "allowed_sessions": ["regular"],
        "max_trades": 10, "max_concurrent_positions": 3, "max_gross_notional": 50000,
        "max_notional_per_trade": 10000, "max_risk_per_trade": 250, "max_daily_loss": 1000,
        "max_chase_bps": 15, "max_order_ttl_sec": 30, "allowed_order_types": ["limit", "stop_limit"],
        "required_protection": ["stop"], "candidate_policy_version": "cand-v1", "risk_policy_version": "risk-v1",
        "operator_identity": "john@jwwhiting.com",
    }


class FlagsOn:
    active_trader_session_builder_enabled = True


class FlagsOff:
    active_trader_session_builder_enabled = False


def _new():
    return sc.SessionStore(None), se.SimExecutionEngine()


def _d(store, eng, method, path, body=None, flags=None):
    return sh.dispatch(store, eng, method, path, None, body, flags)


def _create(store, eng):
    st, b = _d(store, eng, "POST", f"{PFX}/session-drafts", {"operator_identity": "john", "draft": _draft()})
    assert st == 201
    return b["data"]["session_id"], b


def test_full_simulation_lifecycle_reaches_active():
    store, eng = _new()
    sid, _ = _create(store, eng)
    assert _d(store, eng, "POST", f"{PFX}/session-drafts/{sid}/save", {"updates": _draft()})[0] == 200
    assert _d(store, eng, "POST", f"{PFX}/session-drafts/{sid}/validate", {})[0] == 200
    assert _d(store, eng, "POST", f"{PFX}/session-drafts/{sid}/authorization-preview", {})[0] == 200
    assert _d(store, eng, "POST", f"{PFX}/sessions/{sid}/authorize", {})[0] == 200
    assert _d(store, eng, "POST", f"{PFX}/sessions/{sid}/activate", {"mode": "SIMULATION"})[0] == 200
    _, g = _d(store, eng, "GET", f"{PFX}/sessions/{sid}", None)
    assert g["data"]["state"] == "ACTIVE"


def test_activate_live_is_feature_disabled():
    store, eng = _new()
    sid, _ = _create(store, eng)
    _, b = _d(store, eng, "POST", f"{PFX}/sessions/{sid}/activate", {"mode": "LIVE"})
    assert b["data"].get("status") == "FEATURE_DISABLED"
    assert b["live"] is False and b["live_session_enabled"] is False


def test_feature_flag_gate_403():
    store, eng = _new()
    st, b = _d(store, eng, "POST", f"{PFX}/session-drafts", {"draft": _draft()}, flags=FlagsOff())
    assert st == 403 and b["kind"] == "feature_disabled"
    # enabled flag lets it through
    assert _d(store, eng, "POST", f"{PFX}/session-drafts", {"draft": _draft()}, flags=FlagsOn())[0] == 201


def test_get_session_and_journal():
    store, eng = _new()
    sid, _ = _create(store, eng)
    assert _d(store, eng, "GET", f"{PFX}/sessions/{sid}", None)[1]["data"]["session_id"] == sid
    assert isinstance(_d(store, eng, "GET", f"{PFX}/sessions/{sid}/journal", None)[1]["data"], list)


def test_simulate_event_armed_makes_no_intent():
    store, eng = _new()
    sid, _ = _create(store, eng)
    _, b = _d(store, eng, "POST", f"{PFX}/sessions/{sid}/simulate-event",
              {"event": {"setup_state": "ARMED", "session_id": sid, "event_id": "e1", "symbol": "X"}})
    assert b["data"]["intent_count"] == 0 and eng.intent_count() == 0   # ARMED never creates an intent
    assert b["real_order"] is False


def test_envelope_never_grants_live_or_order():
    store, eng = _new()
    _, b = _d(store, eng, "POST", f"{PFX}/session-drafts", {"draft": _draft()})
    assert b["live"] is False and b["live_session_enabled"] is False and b["real_order"] is False
    a = b["authority"]
    assert a["order"] is False and a["financial_action"] is False and a["live"] is False


def test_unknown_path_404():
    store, eng = _new()
    assert _d(store, eng, "POST", f"{PFX}/bogus", {})[0] == 404


def test_is_session_path():
    assert sh.is_session_path(f"{PFX}/session-drafts")
    assert sh.is_session_path(f"{PFX}/sessions/abc/journal")
    assert not sh.is_session_path(f"{PFX}/permission-queue")
    assert not sh.is_session_path(f"{PFX}/scalp/setups")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
