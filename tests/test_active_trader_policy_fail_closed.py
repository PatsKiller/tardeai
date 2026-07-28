#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from active_trader import momentum_exit_policy as mx  # noqa: E402
from active_trader import t2_jit_policy as t2  # noqa: E402

NOW = 1_753_700_000.0


def _t2_obs(**over):
    raw = {
        "symbol": "AAPL",
        "observed_at": NOW,
        "session_state": "ACTIVE",
        "mode": "SHADOW",
        "setup_state": "FIRED",
        "gate_decision": "PASS",
        "execution_eligible": True,
        "baseline_quote_age_s": 1.0,
        "trigger_distance_bps": 2.0,
    }
    raw.update(over)
    return raw


def _momentum_obs(at, **over):
    raw = {
        "symbol": "AAPL",
        "observed_at": at,
        "entered_at": NOW,
        "price": 100.8,
        "entry_price": 100.0,
        "hard_stop_price": 98.0,
        "initial_risk_per_share": 2.0,
        "momentum_failure": 0.90,
        "tape_reversal": 0.85,
        "book_weakness": 0.80,
        "structure_failure": 0.80,
        "quote_age_s": 1.0,
        "book_age_s": 1.0,
        "tape_age_s": 1.0,
        "high_watermark": 102.0,
    }
    raw.update(over)
    return raw


def test_missing_baseline_age_fails_closed():
    raw = _t2_obs()
    raw.pop("baseline_quote_age_s")
    snap = t2.T2LeaseManager().reconcile([raw], now=NOW)
    assert snap.leases == ()
    assert snap.decisions[0].reason_code == t2.R_BASELINE_STALE


def test_expired_lease_is_reacquired_with_a_new_identity():
    cfg = t2.T2PolicyConfig(lease_ttl_s=5, cooldown_s=20)
    manager = t2.T2LeaseManager(cfg)
    first = manager.reconcile([_t2_obs()], now=NOW)
    old_id = first.leases[0].lease_id
    second = manager.reconcile([_t2_obs()], now=NOW + 6)
    assert second.leases[0].lease_id != old_id
    assert any(event.reason_code == t2.R_EXPIRED for event in second.events)


def test_missing_freshness_fields_fail_to_protect_only():
    raw = _momentum_obs(NOW + 25)
    raw.pop("quote_age_s")
    raw.pop("book_age_s")
    raw.pop("tape_age_s")
    out = mx.MomentumExitPolicy().evaluate(raw)
    assert out.state == mx.STATE_PROTECT_ONLY
    assert out.reason_code == mx.R_DATA_STALE


def test_armed_state_latches_until_reset_hysteresis_completes():
    policy = mx.MomentumExitPolicy()
    policy.evaluate(_momentum_obs(NOW + 25))
    armed = policy.evaluate(_momentum_obs(NOW + 36))
    assert armed.state == mx.STATE_ARMED

    middle = policy.evaluate(_momentum_obs(
        NOW + 40,
        price=101.2,
        momentum_failure=0.50,
        tape_reversal=0.50,
        book_weakness=0.50,
        structure_failure=0.50,
    ))
    assert middle.state == mx.STATE_ARMED
    assert middle.action == mx.ACTION_ARM

    recovering = policy.evaluate(_momentum_obs(
        NOW + 45,
        price=101.2,
        momentum_failure=0.10,
        tape_reversal=0.10,
        book_weakness=0.10,
        structure_failure=0.10,
    ))
    assert recovering.state == mx.STATE_ARMED

    reset = policy.evaluate(_momentum_obs(
        NOW + 61,
        price=101.2,
        momentum_failure=0.10,
        tape_reversal=0.10,
        book_weakness=0.10,
        structure_failure=0.10,
    ))
    assert reset.state == mx.STATE_HOLD
    assert reset.reason_code == mx.R_RESET
