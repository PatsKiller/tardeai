#!/usr/bin/env python3
"""Active Trader Stage 1a — venue eligibility + Schwab compliance-block prompt contract.

Product rules under test:
  - Schwab is primary when eligible.
  - A Schwab compliance-blocked symbol surfaces the reason, REQUIRES an operator prompt,
    and NEVER silently auto-routes to Moomoo/Alpaca.
  - Eligible Schwab => no alternate prompt.
  - Fail-closed to 'unknown'; alternate venues need operator opt-in.
  - The read surface stays GET-only, write:false, no order/canary/session authority.

Pure + read-only: no network, no DB, no order, no send.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from active_trader import venue_eligibility as ve  # noqa: E402
from active_trader.read_api import ReadOnlyActiveTraderAPI, capability_snapshot  # noqa: E402
from active_trader.read_http import dispatch, ACTIVE_TRADER_PREFIX  # noqa: E402


# ── fixtures ──────────────────────────────────────────────────────────────────

SNAP_BLOCKLIST = {
    "venues": {
        "schwab": {"available": True, "compliance_coverage": "blocklist"},
        "moomoo": {"available": True, "operator_opt_in": False},
        "alpaca": {"available": True, "operator_opt_in": False},
    },
    "symbol_compliance": {
        "GNS": {"schwab_blocked": True, "block_code": "low_float_restriction", "detail": "low-float restricted"},
        "AMTD": {"schwab_blocked": True, "block_code": "call_broker"},
        "AAPL": {"schwab_blocked": False},
    },
}


# ── the two required cases ──────────────────────────────────────────────────────

def test_schwab_block_requires_prompt_and_no_auto_switch():
    r = ve.evaluate_eligibility("GNS", "schwab", SNAP_BLOCKLIST)
    assert r.status == ve.BLOCKED_SCHWAB_COMPLIANCE
    assert r.block_code == "low_float_restriction"
    assert r.prompt_required is True
    assert r.auto_route is False                     # NEVER silent auto-route
    assert set(r.alternate_venues) == {"moomoo", "alpaca"}

    prompt = ve.operator_prompt_required(r)
    assert prompt["prompt_required"] is True
    assert prompt["requires_operator_confirmation"] is True
    assert prompt["auto_route"] is False
    assert prompt["send"] is False                   # template only — nothing is sent
    assert "GNS" in prompt["message"] and "Switch to" in prompt["message"]


def test_eligible_schwab_no_alternate_prompt():
    r = ve.evaluate_eligibility("AAPL", "schwab", SNAP_BLOCKLIST)
    assert r.status == ve.ELIGIBLE
    assert r.prompt_required is False
    assert r.alternate_venues == ()
    prompt = ve.operator_prompt_required(r)
    assert prompt["prompt_required"] is False
    assert prompt["message"] == ""


# ── block-reason surfacing + call-broker variant ───────────────────────────────

def test_call_broker_block_surfaces_reason():
    r = ve.evaluate_eligibility("AMTD", "schwab", SNAP_BLOCKLIST)
    assert r.status == ve.BLOCKED_SCHWAB_COMPLIANCE and r.block_code == "call_broker"
    assert "call" in r.reason.lower()               # reason is explicit, not silent
    assert r.auto_route is False


# ── fail-closed unknown ─────────────────────────────────────────────────────────

def test_no_snapshot_fails_closed_unknown():
    assert ve.evaluate_eligibility("AAPL", "schwab", None).status == ve.UNKNOWN
    assert ve.evaluate_eligibility("AAPL", "schwab", {}).status == ve.UNKNOWN


def test_no_symbol_fails_closed_unknown():
    assert ve.evaluate_eligibility("", "schwab", SNAP_BLOCKLIST).status == ve.UNKNOWN


def test_allowlist_coverage_uncovered_symbol_is_unknown():
    snap = {"venues": {"schwab": {"available": True, "compliance_coverage": "allowlist"}},
            "symbol_compliance": {}}
    assert ve.evaluate_eligibility("ZZZZ", "schwab", snap).status == ve.UNKNOWN


def test_blocklist_coverage_uncovered_symbol_is_eligible():
    assert ve.evaluate_eligibility("MSFT", "schwab", SNAP_BLOCKLIST).status == ve.ELIGIBLE


# ── alternate venues require operator opt-in ────────────────────────────────────

def test_alternate_without_opt_in_is_restricted():
    r = ve.evaluate_eligibility("AAPL", "moomoo", SNAP_BLOCKLIST)
    assert r.status == ve.RESTRICTED
    assert r.prompt_required is True                 # operator must opt in
    assert r.auto_route is False


def test_alternate_with_opt_in_is_eligible():
    snap = {"venues": {"schwab": {"available": True},
                       "alpaca": {"available": True, "operator_opt_in": True}},
            "symbol_compliance": {}}
    assert ve.evaluate_eligibility("AAPL", "alpaca", snap).status == ve.ELIGIBLE


def test_unknown_venue_is_restricted():
    assert ve.evaluate_eligibility("AAPL", "etrade", SNAP_BLOCKLIST).status == ve.RESTRICTED


# ── prompt helper type-guard ────────────────────────────────────────────────────

def test_operator_prompt_required_rejects_non_result():
    with pytest.raises(TypeError):
        ve.operator_prompt_required({"status": "blocked_schwab_compliance"})


# ── HTTP surface: GET-only, read-only, no write authority ───────────────────────

def test_endpoint_block_returns_prompt_and_zero_authority():
    st, body = dispatch(ReadOnlyActiveTraderAPI(), "GET",
                        f"{ACTIVE_TRADER_PREFIX}/venue-eligibility", {"symbol": ["GNS"]})
    assert st == 200
    assert body["write"] is False and body["canary"] is False and body["auto_route"] is False
    assert body["authority"]["order"] is False and body["authority"]["financial_action"] is False
    assert body["eligibility"]["status"] == ve.BLOCKED_SCHWAB_COMPLIANCE
    assert body["operator_prompt"]["prompt_required"] is True
    assert body["operator_prompt"]["send"] is False


def test_endpoint_eligible_has_no_prompt():
    st, body = dispatch(ReadOnlyActiveTraderAPI(), "GET",
                        f"{ACTIVE_TRADER_PREFIX}/venue-eligibility", {"symbol": "AAPL"})
    assert st == 200
    assert body["eligibility"]["status"] == ve.ELIGIBLE
    assert body["operator_prompt"]["prompt_required"] is False


def test_endpoint_requires_symbol():
    st, body = dispatch(ReadOnlyActiveTraderAPI(), "GET",
                        f"{ACTIVE_TRADER_PREFIX}/venue-eligibility", {})
    assert st == 400 and body["kind"] == "bad_request"


def test_endpoint_is_get_only():
    st, body = dispatch(ReadOnlyActiveTraderAPI(), "POST",
                        f"{ACTIVE_TRADER_PREFIX}/venue-eligibility", {"symbol": "GNS"})
    assert st == 405 and body["write"] is False


# ── the committed fixtures load and drive the same contract ─────────────────────

def test_committed_fixtures_snapshot_drives_contract():
    snap = capability_snapshot()
    assert snap["source"] == "fixtures"
    assert ve.evaluate_eligibility("GNS", "schwab", snap).status == ve.BLOCKED_SCHWAB_COMPLIANCE
    assert ve.evaluate_eligibility("AAPL", "schwab", snap).status == ve.ELIGIBLE


# ── packet_g / Stage 0 write flags stay OFF ─────────────────────────────────────

def test_stage0_write_flags_remain_off():
    """Stage 1a must not enable any write/order/canary authority (packet_g stays stage0)."""
    from active_trader.flags import load_flags, HARD_OFF
    flags = load_flags()
    flags.assert_stage0_safe()                       # raises if any hard-off flag is true
    assert flags.write is False and flags.canary is False
    for name in HARD_OFF:
        assert flags.flags.get(name) is not True
