#!/usr/bin/env python3
"""Active Trader P4 — broker capability layer (fail-closed, evidence-only).

Rules under test:
  - UNKNOWN capability (no evidence block / UI-label only) -> fails closed.
  - EXPIRED verification -> fails closed.
  - LIVE environment is never execution-eligible in this build.
  - Thinkorswim / manual is never routable and never eligible.
  - PAPER + fresh + trade + protection -> execution-eligible.

Pure + read-only: no network, no broker client, no order, no send.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from active_trader import broker_capabilities as bc  # noqa: E402


NOW = 1_753_700_000.0
FRESH_EXP = NOW + 3600.0   # expires an hour from now
STALE_EXP = NOW - 1.0      # already expired

FULL_CAPS = {
    "read": True,
    "trade": True,
    "session": True,
    "order_types": ["limit", "stop", "stop_limit", "market"],
    "replace_cancel": True,
    "protection": True,
}


def _snapshot():
    return {
        "now": NOW,
        "accounts": {
            "ALP-PAPER": {
                "broker": bc.BROKER_ALPACA,
                "environment": bc.ENV_PAPER,
                "account_type": "margin",
                "capabilities": dict(FULL_CAPS),
                "verified_at": NOW - 60,
                "expires_at": FRESH_EXP,
                "evidence_source": "broker_probe:2026-07-28T12:00Z",
            },
            "SCHWAB-LIVE": {
                "broker": bc.BROKER_SCHWAB,
                "environment": bc.ENV_LIVE,
                "account_type": "rollover",
                "capabilities": dict(FULL_CAPS),
                "verified_at": NOW - 60,
                "expires_at": FRESH_EXP,
                "evidence_source": "broker_probe:2026-07-28T12:00Z",
            },
            "ALP-EXPIRED": {
                "broker": bc.BROKER_ALPACA,
                "environment": bc.ENV_PAPER,
                "account_type": "margin",
                "capabilities": dict(FULL_CAPS),
                "verified_at": NOW - 7200,
                "expires_at": STALE_EXP,
                "evidence_source": "broker_probe:stale",
            },
            "TOS-MANUAL": {
                "broker": bc.BROKER_TOS,
                "environment": bc.ENV_MANUAL,
                "account_type": "cash",
                "capabilities": dict(FULL_CAPS),
                "verified_at": NOW - 60,
                "expires_at": FRESH_EXP,
                "evidence_source": "broker_probe:tos",
            },
            "MOO-DATA": {
                "broker": bc.BROKER_MOOMOO,
                "environment": bc.ENV_DATA_PLANE,
                "account_type": "data",
                "capabilities": {"read": True, "trade": False, "protection": False,
                                 "order_types": []},
                "verified_at": NOW - 60,
                "expires_at": FRESH_EXP,
                "evidence_source": "broker_probe:moomoo-l2",
            },
            "UI-LABEL-ONLY": {
                "broker": bc.BROKER_ALPACA,
                "environment": bc.ENV_PAPER,
                "account_type": "margin",
                # NO capabilities evidence block; only a UI label + no evidence_source.
                "ui_label": "Trading Enabled",
                "verified_at": NOW - 60,
                "expires_at": FRESH_EXP,
            },
        },
    }


# ── unknown fails closed ────────────────────────────────────────────────────────

def test_ui_label_only_is_unknown_and_fails_closed():
    cap = bc.resolve_capability("UI-LABEL-ONLY", _snapshot())
    assert cap.trade_capability is False
    assert cap.eligibility_reason == bc.REASON_UNKNOWN
    assert bc.is_execution_eligible(cap) is False


def test_absent_account_fails_closed():
    cap = bc.resolve_capability("DOES-NOT-EXIST", _snapshot())
    assert cap.trade_capability is False
    assert cap.eligibility_reason == bc.REASON_ACCOUNT_MISSING
    assert bc.is_execution_eligible(cap) is False


def test_empty_snapshot_fails_closed():
    cap = bc.resolve_capability("ALP-PAPER", None)
    assert cap.trade_capability is False
    assert bc.is_execution_eligible(cap) is False


# ── expired fails closed ────────────────────────────────────────────────────────

def test_expired_verification_fails_closed():
    cap = bc.resolve_capability("ALP-EXPIRED", _snapshot())
    assert cap.verification_fresh is False
    assert cap.trade_capability is False
    assert cap.eligibility_reason == bc.REASON_EXPIRED
    assert bc.is_execution_eligible(cap) is False


# ── live never eligible ─────────────────────────────────────────────────────────

def test_live_env_never_execution_eligible():
    cap = bc.resolve_capability("SCHWAB-LIVE", _snapshot())
    assert cap.environment == bc.ENV_LIVE
    assert cap.eligibility_reason == bc.REASON_LIVE_BLOCKED
    assert bc.is_execution_eligible(cap) is False


# ── thinkorswim / manual never routable ─────────────────────────────────────────

def test_thinkorswim_manual_never_routable():
    cap = bc.resolve_capability("TOS-MANUAL", _snapshot())
    assert cap.routable is False
    assert cap.trade_capability is False
    assert cap.eligibility_reason == bc.REASON_MANUAL
    assert bc.is_execution_eligible(cap) is False


# ── data plane is read-only ─────────────────────────────────────────────────────

def test_data_plane_read_only_not_eligible():
    cap = bc.resolve_capability("MOO-DATA", _snapshot())
    assert cap.read_capability is True
    assert cap.trade_capability is False
    assert cap.eligibility_reason == bc.REASON_DATA_PLANE
    assert bc.is_execution_eligible(cap) is False


# ── the one eligible case ───────────────────────────────────────────────────────

def test_paper_fresh_with_protection_is_eligible():
    cap = bc.resolve_capability("ALP-PAPER", _snapshot())
    assert cap.environment == bc.ENV_PAPER
    assert cap.verification_fresh is True
    assert cap.trade_capability is True
    assert cap.protection_capability is True
    assert bc.supports_price_controlled(cap) is True
    assert bc.is_execution_eligible(cap) is True


def test_market_dropped_from_order_types():
    cap = bc.resolve_capability("ALP-PAPER", _snapshot())
    assert "market" not in cap.order_type_capability
    assert "limit" in cap.order_type_capability
