#!/usr/bin/env python3
"""Active Trader P3 — session control plane (SIMULATION/SHADOW only).

Safety-critical invariants under test:
  * Legal vs illegal lifecycle transitions are enforced by a transition map.
  * The AuthorizationEnvelope hash binds exactly the bound fields; a material
    edit to any bound field changes the hash and invalidates authorization.
  * Deterministic validation rejects missing/non-positive limits, empty
    accounts, unresolved setups, and entry_cutoff > expiry.
  * authorize() uses an INJECTED fake verifier (never real 2FA) and reaches
    AUTHORIZED.
  * activate(LIVE) -> FEATURE_DISABLED and never becomes active-live; only
    SIMULATION/SHADOW reach ACTIVE.
  * An unauthorized / invalidated / expired session cannot activate.
  * revoke and kill are terminal.
  * The module source contains no live-broker / real-2FA / order-submit
    imports or calls.

Pure + inert: no network, no DB, no broker, no order.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from active_trader import session_control as sc  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
def _good_draft(now: float = 1_000.0) -> dict:
    return {
        "strategy": "momentum_scalp",
        "setup_ids": ["ms_pullback", "ms_break"],
        "setup_versions": ["v3", "v3"],
        "registry_hash": "reg-abc123",
        "brokers": ["SIM_BROKER"],
        "account_ids": ["ACC-1"],
        "symbol_list_or_universe_rule": "universe:premarket_movers",
        "session_start": now,
        "entry_cutoff": now + 3_600,
        "expiry": now + 7_200,
        "allowed_sessions": ["regular"],
        "max_trades": 10,
        "max_concurrent_positions": 3,
        "max_gross_notional": 50_000,
        "max_notional_per_trade": 10_000,
        "max_risk_per_trade": 250,
        "max_daily_loss": 1_000,
        "max_chase_bps": 15,
        "max_order_ttl_sec": 30,
        "allowed_order_types": ["limit", "stop_limit"],
        "required_protection": ["stop"],
        "candidate_policy_version": "cand-v1",
        "risk_policy_version": "risk-v1",
        "operator_identity": "john@jwwhiting.com",
    }


def _fake_pass(session, envelope) -> bool:
    return True


def _fake_fail(session, envelope) -> bool:
    return False


def _authorized_session(store: sc.SessionStore, now: float = 1_000.0):
    s = sc.create_draft(store, "john@jwwhiting.com", now=now)
    sc.save_draft(store, s.session_id, _good_draft(now), now=now)
    res = sc.validate_draft(store, s.session_id, now=now)
    assert res["ok"], res["errors"]
    sc.authorization_preview(store, s.session_id, now=now)
    auth = sc.authorize(store, s.session_id, _fake_pass, now=now)
    assert auth["ok"]
    return s.session_id


# ---------------------------------------------------------------------------
# Transitions
def test_legal_transition_path_to_authorized():
    store = sc.SessionStore()
    sid = _authorized_session(store)
    assert sc.get_session(store, sid)["state"] == sc.AUTHORIZED


def test_illegal_transition_raises():
    store = sc.SessionStore()
    s = sc.create_draft(store, "op", now=1_000)
    # EDITING -> ACTIVE is not a legal transition.
    with pytest.raises(sc.SessionTransitionError):
        sc._transition(s, sc.ACTIVE, "bad", at=1_000)


def test_is_legal_transition_map():
    assert sc.is_legal_transition(sc.EDITING, sc.SAVED)
    assert not sc.is_legal_transition(sc.EDITING, sc.AUTHORIZED)
    assert not sc.is_legal_transition(sc.CLOSED, sc.ACTIVE)  # terminal
    assert not sc.is_legal_transition(sc.REVOKED, sc.EDITING)


def test_validate_from_editing_is_illegal():
    store = sc.SessionStore()
    s = sc.create_draft(store, "op", _good_draft(), now=1_000)
    # never saved -> still EDITING
    with pytest.raises(sc.SessionTransitionError):
        sc.validate_draft(store, s.session_id, now=1_000)


# ---------------------------------------------------------------------------
# Envelope hash binding
def test_envelope_hash_deterministic():
    e1 = sc.build_envelope(_good_draft())
    e2 = sc.build_envelope(_good_draft())
    assert e1.authorization_hash == e2.authorization_hash
    assert e1.authorization_hash == e1.recompute_hash()


def test_hash_order_independent_for_sequence_content():
    # Same bound values produce same hash regardless of dict insertion order.
    d = _good_draft()
    d2 = {k: d[k] for k in reversed(list(d.keys()))}
    assert sc.build_envelope(d).authorization_hash == sc.build_envelope(d2).authorization_hash


def test_material_edit_changes_hash():
    base = sc.build_envelope(_good_draft())
    edited_draft = _good_draft()
    edited_draft["max_gross_notional"] = 99_999  # material change to a bound limit
    edited = sc.build_envelope(edited_draft)
    assert edited.authorization_hash != base.authorization_hash


def test_material_edit_invalidates_authorization():
    store = sc.SessionStore()
    sid = _authorized_session(store)
    session = store.get(sid)
    assert sc.is_authorization_valid(session)

    # Operator edits a bound field after authorizing.
    sc.save_draft(store, sid, {"max_notional_per_trade": 25_000}, now=2_000)
    session = store.get(sid)
    # Authorization must be gone; the session is walked back out of AUTHORIZED
    # (through EDITING) and re-saved, so it is no longer authorized/active.
    assert session.state in (sc.EDITING, sc.SAVED)
    assert session.state not in sc.TERMINAL_STATES
    assert session.state != sc.AUTHORIZED
    assert not sc.is_authorization_valid(session)
    assert session.authorized_hash is None


def test_is_authorization_valid_false_when_hashes_differ():
    store = sc.SessionStore()
    sid = _authorized_session(store)
    session = store.get(sid)
    # A different envelope (material edit) must not validate against the pin.
    other = sc.build_envelope({**_good_draft(), "max_daily_loss": 5_000})
    assert not sc.is_authorization_valid(session, other)


# ---------------------------------------------------------------------------
# Validation
def test_validate_rejects_missing_limit():
    store = sc.SessionStore()
    d = _good_draft()
    del d["max_daily_loss"]
    s = sc.create_draft(store, "op", now=1_000)
    sc.save_draft(store, s.session_id, d, now=1_000)
    res = sc.validate_draft(store, s.session_id, now=1_000)
    assert not res["ok"]
    assert any("max_daily_loss" in e for e in res["errors"])
    assert store.get(s.session_id).state == sc.SAVED  # not promoted


def test_validate_rejects_nonpositive_limit():
    store = sc.SessionStore()
    d = _good_draft()
    d["max_trades"] = 0
    s = sc.create_draft(store, "op", now=1_000)
    sc.save_draft(store, s.session_id, d, now=1_000)
    res = sc.validate_draft(store, s.session_id, now=1_000)
    assert not res["ok"]
    assert any("max_trades" in e for e in res["errors"])


def test_validate_rejects_empty_accounts():
    store = sc.SessionStore()
    d = _good_draft()
    d["account_ids"] = []
    s = sc.create_draft(store, "op", now=1_000)
    sc.save_draft(store, s.session_id, d, now=1_000)
    res = sc.validate_draft(store, s.session_id, now=1_000)
    assert not res["ok"]
    assert any("account_ids" in e for e in res["errors"])


def test_validate_rejects_cutoff_after_expiry():
    store = sc.SessionStore()
    d = _good_draft()
    d["entry_cutoff"] = d["expiry"] + 10  # cutoff after expiry
    s = sc.create_draft(store, "op", now=1_000)
    sc.save_draft(store, s.session_id, d, now=1_000)
    res = sc.validate_draft(store, s.session_id, now=1_000)
    assert not res["ok"]
    assert any("entry_cutoff" in e for e in res["errors"])


def test_validate_rejects_unresolved_setup():
    store = sc.SessionStore()
    s = sc.create_draft(store, "op", now=1_000)
    sc.save_draft(store, s.session_id, _good_draft(), now=1_000)
    res = sc.validate_draft(store, s.session_id,
                            setup_resolver=lambda sid: False, now=1_000)
    assert not res["ok"]
    assert any("unresolved setup_id" in e for e in res["errors"])


def test_validate_ok_promotes_to_validated():
    store = sc.SessionStore()
    s = sc.create_draft(store, "op", now=1_000)
    sc.save_draft(store, s.session_id, _good_draft(), now=1_000)
    res = sc.validate_draft(store, s.session_id,
                            setup_resolver=lambda sid: True, now=1_000)
    assert res["ok"] and res["errors"] == []
    assert store.get(s.session_id).state == sc.VALIDATED


# ---------------------------------------------------------------------------
# Authorization (fake verifier only)
def test_authorize_uses_fake_verifier_reaches_authorized():
    store = sc.SessionStore()
    s = sc.create_draft(store, "op", now=1_000)
    sc.save_draft(store, s.session_id, _good_draft(), now=1_000)
    sc.validate_draft(store, s.session_id, now=1_000)
    sc.authorization_preview(store, s.session_id, now=1_000)
    res = sc.authorize(store, s.session_id, _fake_pass, now=1_000)
    assert res["ok"]
    assert store.get(s.session_id).state == sc.AUTHORIZED


def test_authorize_failed_verifier_returns_to_review():
    store = sc.SessionStore()
    s = sc.create_draft(store, "op", now=1_000)
    sc.save_draft(store, s.session_id, _good_draft(), now=1_000)
    sc.validate_draft(store, s.session_id, now=1_000)
    sc.authorization_preview(store, s.session_id, now=1_000)
    res = sc.authorize(store, s.session_id, _fake_fail, now=1_000)
    assert not res["ok"]
    assert store.get(s.session_id).state == sc.AUTHORIZATION_REVIEW
    assert store.get(s.session_id).authorized_hash is None


# ---------------------------------------------------------------------------
# Activation — the hard safety guard
def test_activate_live_returns_feature_disabled_and_never_active():
    store = sc.SessionStore()
    sid = _authorized_session(store)
    res = sc.activate(store, sid, sc.LIVE, now=1_100)
    assert res["status"] == sc.FEATURE_DISABLED
    # State must NOT have advanced to ACTIVE.
    assert store.get(sid).state == sc.AUTHORIZED
    assert store.get(sid).mode is None


def test_live_activation_is_hard_disabled_constant():
    assert sc.LIVE_ACTIVATION_ENABLED is False


def test_activate_simulation_reaches_active():
    store = sc.SessionStore()
    sid = _authorized_session(store)
    res = sc.activate(store, sid, sc.SIMULATION, now=1_100)
    assert res["status"] == sc.ACTIVE
    assert store.get(sid).state == sc.ACTIVE
    assert store.get(sid).mode == sc.SIMULATION


def test_activate_shadow_reaches_active():
    store = sc.SessionStore()
    sid = _authorized_session(store)
    res = sc.activate(store, sid, sc.SHADOW, now=1_100)
    assert res["status"] == sc.ACTIVE
    assert store.get(sid).mode == sc.SHADOW


def test_unauthorized_session_cannot_activate():
    store = sc.SessionStore()
    s = sc.create_draft(store, "op", now=1_000)
    sc.save_draft(store, s.session_id, _good_draft(), now=1_000)
    sc.validate_draft(store, s.session_id, now=1_000)
    res = sc.activate(store, s.session_id, sc.SIMULATION, now=1_000)
    assert res["status"] == "ERROR"
    assert store.get(s.session_id).state == sc.VALIDATED  # unchanged


def test_expired_session_cannot_activate():
    store = sc.SessionStore()
    now = 1_000.0
    sid = _authorized_session(store, now=now)
    # Activate well past the envelope expiry (now + 7200).
    res = sc.activate(store, sid, sc.SIMULATION, now=now + 999_999)
    assert res["status"] == "ERROR"
    assert "expired" in res["reason"]
    assert store.get(sid).state == sc.AUTHORIZED


def test_invalidated_authorization_cannot_activate():
    store = sc.SessionStore()
    sid = _authorized_session(store)
    # Edit a bound field -> authorization invalidated, back to EDITING.
    sc.save_draft(store, sid, {"max_trades": 20}, now=2_000)
    res = sc.activate(store, sid, sc.SIMULATION, now=2_100)
    # Not authorized anymore.
    assert res["status"] == "ERROR"


# ---------------------------------------------------------------------------
# Terminal states
def test_revoke_is_terminal():
    store = sc.SessionStore()
    sid = _authorized_session(store)
    sc.revoke(store, sid, reason="operator abort", now=1_100)
    assert store.get(sid).state == sc.REVOKED
    # A revoked session cannot activate and cannot transition further.
    res = sc.activate(store, sid, sc.SIMULATION, now=1_200)
    assert res["status"] == "ERROR"
    assert store.get(sid).state == sc.REVOKED  # unchanged
    with pytest.raises(sc.SessionTransitionError):
        sc.pause(store, sid, now=1_300)


def test_kill_is_terminal():
    store = sc.SessionStore()
    sid = _authorized_session(store)
    sc.activate(store, sid, sc.SIMULATION, now=1_100)
    sc.kill(store, sid, reason="emergency", now=1_200)
    assert store.get(sid).state == sc.KILLED
    # No transition out of KILLED.
    with pytest.raises(sc.SessionTransitionError):
        sc.pause(store, sid, now=1_300)
    with pytest.raises(sc.SessionTransitionError):
        sc.revoke(store, sid, now=1_300)


# ---------------------------------------------------------------------------
# Journal + persistence
def test_journal_records_lifecycle():
    store = sc.SessionStore()
    sid = _authorized_session(store)
    events = [e["event"] for e in sc.session_journal(store, sid)]
    assert "create_draft" in events
    assert "authorized" in events


def test_json_persistence_roundtrip(tmp_path):
    path = tmp_path / "active_trader" / "sessions.json"
    store = sc.SessionStore(path=path)
    sid = _authorized_session(store)
    assert path.is_file()
    # Reload from disk into a fresh store.
    store2 = sc.SessionStore(path=path)
    reloaded = store2.get(sid)
    assert reloaded.state == sc.AUTHORIZED
    assert reloaded.envelope is not None
    assert sc.is_authorization_valid(reloaded)


# ---------------------------------------------------------------------------
# Source-level inertness guard
def test_source_has_no_live_broker_2fa_or_order_submit():
    src = (ROOT / "scripts" / "active_trader" / "session_control.py").read_text(encoding="utf-8")

    # No imports of known live-broker / execution / real-2FA modules.
    banned_import = re.compile(
        r"^\s*(from|import)\s+.*\b("
        r"schwab|alpaca|moomoo|ibkr|snaptrade|broker_adapter|requests|httpx|urllib|socket|"
        r"pyotp|twilio|smtplib"
        r")\b",
        re.IGNORECASE | re.MULTILINE,
    )
    assert banned_import.search(src) is None, "live/network/2FA import present"

    # No order-submission / broker-call verbs invoked in code.
    banned_call = re.compile(
        r"\b(submit_order|place_order|send_order|cancel_order|modify_order|"
        r"route_order|broker\.\w+|send_2fa|verify_2fa|get_credentials?|read_credential)\s*\(",
        re.IGNORECASE,
    )
    assert banned_call.search(src) is None, "order/broker/2FA call present"

    # The hard guard must be present and disabled.
    assert "LIVE_ACTIVATION_ENABLED: bool = False" in src
    assert "FEATURE_DISABLED" in src
