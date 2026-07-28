#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from active_trader import momentum_exit_policy as mx  # noqa: E402

NOW = 1_753_700_000.0


def _obs(at, **over):
    raw = {
        "symbol": "AAPL",
        "observed_at": at,
        "entered_at": NOW,
        "price": 101.0,
        "entry_price": 100.0,
        "hard_stop_price": 98.0,
        "initial_risk_per_share": 2.0,
        "momentum_failure": 0.10,
        "tape_reversal": 0.10,
        "book_weakness": 0.10,
        "structure_failure": 0.10,
        "quote_age_s": 1.0,
        "book_age_s": 1.0,
        "tape_age_s": 1.0,
        "high_watermark": 102.0,
    }
    raw.update(over)
    return mx.MomentumObservation.from_mapping(raw)


def _bad(at, **over):
    raw = {
        "price": 100.8,
        "momentum_failure": 0.90,
        "tape_reversal": 0.85,
        "book_weakness": 0.80,
        "structure_failure": 0.80,
    }
    raw.update(over)
    return _obs(at, **raw)


def test_minimum_hold_blocks_soft_exit_but_not_hard_stop():
    policy = mx.MomentumExitPolicy()
    soft = policy.evaluate(_bad(NOW + 5))
    assert soft.state == mx.STATE_HOLD
    assert soft.reason_code == mx.R_MIN_HOLD

    hard = policy.evaluate(_bad(NOW + 6, price=97.9))
    assert hard.state == mx.STATE_SIGNAL
    assert hard.reason_code == mx.R_HARD_STOP


def test_brief_momentum_bump_does_not_emit_exit_signal():
    policy = mx.MomentumExitPolicy()
    first = policy.evaluate(_bad(NOW + 25))
    assert first.state == mx.STATE_WATCH

    recovered = policy.evaluate(_obs(NOW + 30))
    assert recovered.state in {mx.STATE_WATCH, mx.STATE_HOLD}
    assert recovered.action == mx.ACTION_HOLD

    settled = policy.evaluate(_obs(NOW + 46))
    assert settled.state == mx.STATE_HOLD
    assert settled.reason_code == mx.R_RESET


def test_persistent_multifactor_failure_arms_then_signals():
    policy = mx.MomentumExitPolicy()
    watch = policy.evaluate(_bad(NOW + 25))
    assert watch.state == mx.STATE_WATCH

    armed = policy.evaluate(_bad(NOW + 36))
    assert armed.state == mx.STATE_ARMED
    assert armed.action == mx.ACTION_ARM

    still_armed = policy.evaluate(_bad(NOW + 41))
    assert still_armed.state == mx.STATE_ARMED

    signal = policy.evaluate(_bad(NOW + 47))
    assert signal.state == mx.STATE_SIGNAL
    assert signal.action == mx.ACTION_SIGNAL
    assert signal.reason_code == mx.R_PERSISTENT_FAILURE


def test_high_score_without_price_confirmation_stays_armed():
    policy = mx.MomentumExitPolicy()
    policy.evaluate(
        _bad(NOW + 25, price=103.0, high_watermark=103.0, structure_failure=0.70)
    )
    out = policy.evaluate(
        _bad(NOW + 36, price=103.0, high_watermark=103.0, structure_failure=0.70)
    )
    assert out.state == mx.STATE_ARMED
    assert out.reason_code == mx.R_PRICE_CONFIRMATION_MISSING


def test_stale_data_uses_protection_only_and_does_not_invent_momentum_exit():
    policy = mx.MomentumExitPolicy()
    out = policy.evaluate(_bad(NOW + 25, tape_age_s=99))
    assert out.state == mx.STATE_PROTECT_ONLY
    assert out.action == mx.ACTION_PROTECT_ONLY
    assert out.reason_code == mx.R_DATA_STALE


def test_two_confirmation_dimensions_are_required():
    policy = mx.MomentumExitPolicy()
    out = policy.evaluate(
        _obs(
            NOW + 25,
            momentum_failure=1.0,
            tape_reversal=0.59,
            book_weakness=0.59,
            structure_failure=0.59,
        )
    )
    assert out.action == mx.ACTION_HOLD
    assert out.state == mx.STATE_HOLD


def test_account_fields_do_not_change_exit_decision():
    first = mx.MomentumExitPolicy().evaluate(
        _bad(NOW + 25, account_id="one", venue="a", environment="sandbox")
    )
    second = mx.MomentumExitPolicy().evaluate(
        _bad(NOW + 25, account_id="two", venue="b", environment="production")
    )
    assert first == second
    assert not hasattr(_bad(NOW + 25), "account_id")


def test_source_emits_account_unbound_signal_only_without_external_actions():
    src = (ROOT / "scripts" / "active_trader" / "momentum_exit_policy.py").read_text(
        encoding="utf-8"
    ).lower()
    forbidden = [
        "import requests",
        "import socket",
        "import urllib",
        "http://",
        "https://",
        "place_order",
        "submit_order",
        "cancel_order",
        "modify_order",
        "unlock_trade",
        "api_key",
        "secret_key",
        "paper execution",
        "paper exit",
        "mode_paper",
    ]
    assert [token for token in forbidden if token in src] == []
