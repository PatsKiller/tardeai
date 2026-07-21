#!/usr/bin/env python3
"""Trailing-STOP-LIMIT is a first-class protective placement option.

A trailing stop that rests a LIMIT (not a market) once triggered: the trigger
ratchets up with price by trail_pct, and a second offset holds the limit
limit_offset% below LAST so the exit fills without slipping to market. Advisory
only here — no order is submitted and no 2FA is requested.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from brokers import protective_stop_pilot as psp  # noqa: E402
from brokers import protective_stop_policy as pol  # noqa: E402


def test_alias_normalizes_to_schwab_trailing_stop_limit():
    assert psp.normalize_kind("TRAILING_LIMIT") == "TRAILING_STOP_LIMIT"
    assert psp.normalize_kind("TRAILING_STOP_LIMIT") == "TRAILING_STOP_LIMIT"


def test_spec_has_both_a_trail_and_a_limit_offset():
    spec = psp.build_order_spec("ANET", 50, "TRAILING_LIMIT", trail_pct=8, limit_offset=8.5)
    assert spec["orderType"] == "TRAILING_STOP_LIMIT"
    assert spec["stopPriceLinkType"] == "PERCENT" and spec["stopPriceOffset"] == 8.0
    assert spec["priceLinkType"] == "PERCENT" and spec["priceOffset"] == 8.5
    assert spec["duration"] == "GOOD_TILL_CANCEL"
    assert spec["orderLegCollection"][0]["instruction"] == "SELL"


def test_limit_defaults_to_the_trail_when_not_widened():
    spec = psp.build_order_spec("ANET", 50, "TRAILING_LIMIT", trail_pct=8)
    assert spec["priceOffset"] == spec["stopPriceOffset"] == 8.0


def test_limit_offset_narrower_than_trail_is_rejected():
    # a limit above the trigger could never fill on the way down
    with pytest.raises(ValueError):
        psp.build_order_spec("ANET", 50, "TRAILING_LIMIT", trail_pct=8, limit_offset=5)


def test_intent_round_trips_through_spec_from_intent():
    it = psp.build_intent("schwab_taxable", "ANET", 50, "TRAILING_LIMIT",
                          stop_price=160.0, trail_pct=8, limit_offset=8.5,
                          advised_stop=160.0, current_price=175.0, held_qty=50)
    ev = it.meta.signal_evidence
    assert ev["order_type"] == "TRAILING_STOP_LIMIT" and ev["trail_pct"] == 8.0 and ev["limit_offset"] == 8.5
    spec = psp.spec_from_intent(it)   # confirm-time rebuild never trusts the client
    assert spec["orderType"] == "TRAILING_STOP_LIMIT" and spec["priceOffset"] == 8.5


def test_policy_allows_the_new_order_type():
    assert "TRAILING_STOP_LIMIT" in pol.ALLOWED_ORDER_TYPES
    ok, reasons = pol.evaluate(account_key="schwab_taxable", instruction="SELL",
                               order_type="TRAILING_STOP_LIMIT", stop_price=160.0,
                               current_price=175.0, advised_stop=160.0, qty=50,
                               held_qty=50, symbol="ANET")
    assert not any("order_type" in str(r) and "not in" in str(r) for r in reasons)


# ── safety properties (Section 5) ─────────────────────────────────────────────

def test_ui_clamps_limit_offset_to_at_least_the_trail():
    """The UI cannot request a limit tighter than the trail (would sit above the
    trigger and never fill on the way down)."""
    src = (ROOT / "apps" / "command-center-v3" / "src" / "components"
           / "HoldingProtectionActions.tsx").read_text()
    assert "Math.max(numOr(ovLimitOffset)" in src


def test_api_independently_revalidates_the_offset_relationship():
    """Even if a client bypassed the UI clamp, the spec builder rejects it."""
    with pytest.raises(ValueError):
        psp.build_order_spec("ANET", 50, "TRAILING_LIMIT", trail_pct=8, limit_offset=4)


def test_button_is_gated_to_schwab_only():
    src = (ROOT / "apps" / "command-center-v3" / "src" / "components"
           / "HoldingProtectionActions.tsx").read_text()
    assert "isSchwab && (trailPct != null || numOr(ovTrail) != null) && btn('Apply Trailing-Limit Stop (2FA)', 'TRAILING_LIMIT')" in src


def test_fidelity_snaptrade_does_not_claim_native_trailing_limit():
    from brokers import snaptrade_protective_stop_pilot as snap
    assert snap.normalize_kind("TRAILING_LIMIT") == ""          # unsupported → advisory/manual
    # but the shared signature still accepts+ignores the kwarg so Fidelity STOP works
    it = snap.build_intent("fidelity_individual", "ANET", 50, "STOP",
                           stop_price=160.0, limit_offset=8.5, current_price=175.0)
    assert it is not None


def test_confirm_reconstructs_the_ticket_server_side_not_from_client():
    it = psp.build_intent("schwab_taxable", "ANET", 50, "TRAILING_LIMIT",
                          stop_price=160.0, trail_pct=8, limit_offset=8.5,
                          advised_stop=160.0, current_price=175.0, held_qty=50)
    # even if a client re-sent a tampered spec, confirm rebuilds from the stored intent
    spec = psp.spec_from_intent(it)
    assert spec["orderType"] == "TRAILING_STOP_LIMIT"
    assert spec["stopPriceOffset"] == 8.0 and spec["priceOffset"] == 8.5


def test_request_and_submit_are_separate_2fa_gated_steps():
    """No path builds+submits in one call: request_2fa and submit are distinct, and
    submit routes through schwab_transport with the guard."""
    import inspect
    assert "approval_service.request_approval" in inspect.getsource(psp.request_2fa)
    assert "schwab_transport.place_order" in inspect.getsource(psp.submit)
