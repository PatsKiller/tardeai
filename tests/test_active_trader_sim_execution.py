#!/usr/bin/env python3
"""Active Trader P4 — deterministic SIMULATION execution path.

An OrderIntent is created ONLY for a fully valid FIRED setup on a paper,
execution-eligible account. Every other condition returns a typed refusal and
NEVER an intent. The only dispatch target is a pure simulator — there is no live
adapter, no order-submit, no 2FA anywhere in the source.

Cases:
  - ARMED (not FIRED)          -> no intent
  - FIRED + gate VETO          -> no intent
  - FIRED + stale data         -> no intent
  - FIRED + missing T2         -> no intent
  - FIRED + inactive session   -> no intent
  - FIRED + unauthorized acct  -> no intent
  - FIRED + unauthorized sym   -> no intent
  - FIRED + risk breach        -> no intent
  - FIRED + market entry       -> no intent
  - FIRED + hash mismatch      -> no intent
  - FIRED + kill switch        -> no intent
  - FIRED + valid              -> EXACTLY ONE simulated intent
  - duplicate event            -> no second intent (idempotency)
  - source grep                -> no live adapter / order-submit / 2FA imports
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from active_trader import broker_capabilities as bc  # noqa: E402
from active_trader import sim_execution as se  # noqa: E402


NOW = 1_753_700_000.0
HASH = "reg_hash_abc123"

CAP_SNAPSHOT = {
    "now": NOW,
    "accounts": {
        "ALP-PAPER": {
            "broker": bc.BROKER_ALPACA,
            "environment": bc.ENV_PAPER,
            "account_type": "margin",
            "capabilities": {
                "read": True, "trade": True, "session": True,
                "order_types": ["limit", "stop", "stop_limit"],
                "replace_cancel": True, "protection": True,
            },
            "verified_at": NOW - 60,
            "expires_at": NOW + 3600,
            "evidence_source": "broker_probe:2026-07-28",
        },
    },
}


def _session(**over):
    s = {
        "session_id": "SESS-1",
        "state": "ACTIVE",
        "account_id": "ALP-PAPER",
        "authorized_accounts": ["ALP-PAPER"],
        "authorized_symbols": ["AAPL"],
        "registry_hash": HASH,
        "entry_cutoff": NOW + 1800,
        "risk": {"max_risk_per_trade": 200.0, "max_position_notional": 100_000.0},
    }
    s.update(over)
    return s


def _context(**over):
    c = {
        "now": NOW,
        "session": _session(),
        "capability_snapshot": copy.deepcopy(CAP_SNAPSHOT),
        "expected_registry_hash": HASH,
        "kill_switch": False,
        "freshness": {"max_quote_age_s": 5, "max_book_age_s": 5, "max_tape_age_s": 10},
    }
    c.update(over)
    return c


def _event(**over):
    e = {
        "event_id": "EVT-1",
        "session_id": "SESS-1",
        "symbol": "AAPL",
        "setup_state": "FIRED",
        "setup_type": "pullback_break",
        "side": "buy",
        "gate_decision": "PASS",
        "requires_t2": True,
        "t2_evidence": {"confirm": "vwap_reclaim", "bars": 2},
        "registry_hash": HASH,
        "account_id": "ALP-PAPER",
        "entry": {"order_type": "limit", "limit_price": 100.0, "stop_price": 98.0},
        "quote": {"ts": NOW - 1},
        "book": {"ts": NOW - 1},
        "tape": {"ts": NOW - 2},
    }
    e.update(over)
    return e


def _run(event=None, context=None):
    eng = se.SimExecutionEngine()
    out = eng.process(event or _event(), context or _context())
    return eng, out


# ── refusals never create an intent ─────────────────────────────────────────────

def test_armed_never_creates_intent():
    eng, out = _run(_event(setup_state="ARMED"))
    assert out.is_intent is False
    assert out.reason_code == se.R_NOT_FIRED
    assert eng.intent_count() == 0


def test_gate_veto_never_creates_intent():
    eng, out = _run(_event(gate_decision="VETO"))
    assert out.is_intent is False
    assert out.reason_code == se.R_GATE_VETO
    assert eng.intent_count() == 0


def test_stale_data_never_creates_intent():
    eng, out = _run(_event(quote={"ts": NOW - 999}))
    assert out.is_intent is False
    assert out.reason_code == se.R_DATA_STALE
    assert eng.intent_count() == 0


def test_missing_t2_when_required_never_creates_intent():
    eng, out = _run(_event(requires_t2=True, t2_evidence={}))
    assert out.is_intent is False
    assert out.reason_code == se.R_MISSING_T2
    assert eng.intent_count() == 0


def test_inactive_session_never_creates_intent():
    eng, out = _run(context=_context(session=_session(state="PAUSED")))
    assert out.is_intent is False
    assert out.reason_code == se.R_SESSION_INACTIVE
    assert eng.intent_count() == 0


def test_unauthorized_account_never_creates_intent():
    eng, out = _run(context=_context(session=_session(authorized_accounts=["OTHER"])))
    assert out.is_intent is False
    assert out.reason_code == se.R_ACCOUNT_UNAUTHORIZED
    assert eng.intent_count() == 0


def test_unauthorized_symbol_never_creates_intent():
    eng, out = _run(context=_context(session=_session(authorized_symbols=["TSLA"])))
    assert out.is_intent is False
    assert out.reason_code == se.R_SYMBOL_UNAUTHORIZED
    assert eng.intent_count() == 0


def test_risk_breach_never_creates_intent():
    # notional cap far below one share's price forces a risk-envelope breach.
    ctx = _context(session=_session(
        risk={"max_risk_per_trade": 200.0, "max_position_notional": 10.0}))
    eng, out = _run(context=ctx)
    assert out.is_intent is False
    assert out.reason_code == se.R_RISK_BREACH
    assert eng.intent_count() == 0


def test_market_entry_never_creates_intent():
    eng, out = _run(_event(entry={"order_type": "market", "stop_price": 98.0}))
    assert out.is_intent is False
    assert out.reason_code == se.R_MARKET_FORBIDDEN
    assert eng.intent_count() == 0


def test_stop_inside_noise_floor_never_creates_intent():
    # Defect 2 — a FIRED event whose stop sits inside the deterministic tick/spread/volatility floor is
    # refused by the SAME shared validator (limit 100, stop 99.999 → 0.001 < 2-tick floor of 0.02).
    eng, out = _run(_event(entry={"order_type": "limit", "limit_price": 100.0, "stop_price": 99.999}))
    assert out.is_intent is False
    assert out.reason_code == se.R_STOP_INVALID
    assert eng.intent_count() == 0


def test_hash_mismatch_never_creates_intent():
    eng, out = _run(_event(registry_hash="WRONG"))
    assert out.is_intent is False
    assert out.reason_code == se.R_HASH_MISMATCH
    assert eng.intent_count() == 0


def test_kill_switch_never_creates_intent():
    eng, out = _run(context=_context(kill_switch=True))
    assert out.is_intent is False
    assert out.reason_code == se.R_KILL_SWITCH
    assert eng.intent_count() == 0


def test_ineligible_live_account_never_creates_intent():
    snap = copy.deepcopy(CAP_SNAPSHOT)
    snap["accounts"]["ALP-PAPER"]["environment"] = bc.ENV_LIVE
    eng, out = _run(context=_context(capability_snapshot=snap))
    assert out.is_intent is False
    assert out.reason_code == se.R_CAPABILITY_INELIGIBLE
    assert eng.intent_count() == 0


# ── the one valid case ──────────────────────────────────────────────────────────

def test_valid_fired_creates_exactly_one_simulated_intent():
    eng, out = _run()
    assert out.is_intent is True
    assert out.ok is True
    assert eng.intent_count() == 1

    intent = out.intent
    assert intent.simulated is True
    assert intent.order_type == "limit"          # price-controlled only
    assert intent.symbol == "AAPL"
    # server-side sizing: 200 risk / (100-98) = 100 shares
    assert intent.quantity == 100
    assert intent.risk_amount == 200.0
    assert intent.account_id == "ALP-PAPER"

    # simulated fill + protection + reconciliation all present and inert
    assert out.fill.adapter == se.SIM_ADAPTER
    assert out.fill.simulated is True
    assert out.protection["status"] == "protected_sim"
    assert out.reconciliation["reconciled"] is True
    assert out.journal_entry["simulated"] is True


def test_duplicate_event_creates_no_second_intent():
    eng = se.SimExecutionEngine()
    first = eng.process(_event(), _context())
    assert first.is_intent is True
    assert eng.intent_count() == 1

    # identical (session_id, event_id) again -> idempotent refusal, no new intent
    second = eng.process(_event(), _context())
    assert second.is_intent is False
    assert second.reason_code == se.R_DUPLICATE
    assert eng.intent_count() == 1


# ── safety: no live path anywhere in the source ─────────────────────────────────

def test_source_has_no_live_adapter_or_2fa_imports():
    src = (ROOT / "scripts" / "active_trader" / "sim_execution.py").read_text(
        encoding="utf-8").lower()
    forbidden = [
        "import requests", "import socket", "import urllib", "http://", "https://",
        "submit_order", "place_order", "cancel_order", "live_adapter", "broker_adapter",
        "two_factor", "twofactor", "2fa", "credential", "oauth", "secret_key",
        "schwab", "alpaca", "moomoo", "thinkorswim", "api_key",
    ]
    hits = [tok for tok in forbidden if tok in src]
    assert hits == [], f"forbidden live-path tokens present in sim_execution.py: {hits}"


def test_only_dispatch_target_is_the_simulator():
    src = (ROOT / "scripts" / "active_trader" / "sim_execution.py").read_text(encoding="utf-8")
    assert 'SIM_ADAPTER = "SIMULATION"' in src
    assert "_simulate_fill" in src
