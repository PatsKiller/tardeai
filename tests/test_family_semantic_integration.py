#!/usr/bin/env python3
"""Semantic integration invariants for plan families (seven-name matrix).

Covers the three-axis separation, thesis/event/options/no-trade/ownership rules
that the live Command Center cards exposed as contradictions.

Pure: no network, no database, no broker, no order.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import decision_action_policy as pol  # noqa: E402
import decision_packet as dp  # noqa: E402

NOW = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)


def _base(**over):
    p = {
        "symbol": "TEST", "packet_version": "1.1.0-shadow",
        "evaluated_at": "2026-07-21T11:30:00Z",
        "price_used": 10.0, "facts_as_of": "2026-07-21T11:30:00Z",
        "ownership": {"held": False, "shares": 0.0, "uncommitted_shares": None},
        "event_state": {"impact": "CAUTION", "earnings": {"state": "SCHEDULED", "date": "2026-08-12"}},
        "data_quality": {"state": "FRESH"},
        "horizons": {
            "tactical": {"direction": "UNRESOLVED", "timing": "RANGE_BOUND",
                         "confidence": 0.5, "trigger": "t", "invalidation": "i"},
            "swing": {"direction": "UNRESOLVED", "timing": "RANGE_BOUND",
                      "confidence": 0.5, "trigger": "t", "invalidation": "i"},
            "long_term": {"thesis_state": "CONSTRUCTIVE", "direction": "BULLISH",
                          "confidence": 0.6, "thesis": "x", "invalidation": "y"},
        },
        "plan_families": {
            "long_term": {
                "family": "LONG_TERM", "state": "ELIGIBLE",
                "structures": [{"structure": "STAGED_SHARES", "state": "ELIGIBLE",
                                "starter_entry": {"price_or_zone": [9, 10]}}],
            },
            "swing": {
                "family": "SWING", "state": "ELIGIBLE",
                "structures": [{"structure": "TACTICAL_SWING", "state": "ELIGIBLE",
                                "entry_zone": [9, 10], "limit_price": 9.5, "urgency": "READY"}],
            },
            "bearish": {"family": "BEARISH", "state": "REJECTED", "structures": [
                {"structure": "SHORT_STOCK", "state": "REJECTED",
                 "rejection_reasons": ["borrow UNKNOWN"]}]},
            "options": {"family": "OPTIONS", "state": "CONDITIONAL", "structures": [
                {"structure": "LONG_PUT", "state": "NOT_APPLICABLE", "rejection_reasons": ["n/a"]},
                {"structure": "LONG_CALL", "state": "REJECTED", "rejection_reasons": ["no setup"]},
                {"structure": "CALL_DEBIT_SPREAD", "state": "REJECTED", "rejection_reasons": ["no setup"]},
                {"structure": "CASH_SECURED_PUT", "state": "REJECTED", "rejection_reasons": ["cash"]},
            ]},
            "no_trade": {"family": "NO_TRADE", "state": "ELIGIBLE",
                         "rationale": "always valid"},
        },
        "no_trade_is_valid": True,
        "preferred_action": {"structure": "NO_TRADE"},
    }
    for k, v in over.items():
        p[k] = v
    return p


# ── 1. Three-axis separation ──────────────────────────────────────────────────

def test_reconcile_adds_three_axes():
    p = dp.materialize_packet(_base())
    for key in ("long_term", "swing", "bearish", "options"):
        fam = p["plan_families"][key]
        assert fam.get("constructibility_state")
        assert fam.get("decision_state")
        assert fam.get("action_state")


def test_event_blocked_keeps_constructible_but_blocks_action():
    p = _base()
    p["horizons"]["tactical"]["timing"] = "EVENT_BLOCKED"
    p = dp.materialize_packet(p)
    sw = p["plan_families"]["swing"]
    assert sw["constructibility_state"] == "CONSTRUCTIBLE"
    assert sw["decision_state"] != "ELIGIBLE" or sw["action_state"] == "BLOCKED"
    assert sw["action_state"] == "BLOCKED"
    assert sw["action_state"] != "READY"
    assert not any(str(s.get("state")) == "ELIGIBLE" for s in sw["structures"])


def test_event_blocked_never_grants_propose_entry():
    p = _base()
    p["horizons"]["tactical"]["timing"] = "EVENT_BLOCKED"
    p = dp.materialize_packet(p)
    r = pol.evaluate_action(p, generated_at=p["evaluated_at"], now=NOW)
    assert r["allowed"] is False
    assert r["state"] == "BLOCKED"
    assert r["action"] != "PROPOSE_ENTRY"


# ── 2. Long-term thesis / family ──────────────────────────────────────────────

@pytest.mark.parametrize("thesis", ["FUNDAMENTALLY_UNATTRACTIVE", "DETERIORATING"])
def test_fundamentally_unattractive_rejects_long_term(thesis):
    p = _base()
    p["horizons"]["long_term"]["thesis_state"] = thesis
    p = dp.materialize_packet(p)
    lt = p["plan_families"]["long_term"]
    assert lt["decision_state"] == "REJECTED"
    assert lt["state"] == "REJECTED"
    assert not any(str(s.get("state")) == "ELIGIBLE" for s in lt["structures"])
    assert dp.assert_family_invariants(p) == []


def test_insufficient_evidence_is_data_unavailable_not_eligible():
    p = _base()
    p["horizons"]["long_term"]["thesis_state"] = "INSUFFICIENT_EVIDENCE"
    p = dp.materialize_packet(p)
    lt = p["plan_families"]["long_term"]
    assert lt["decision_state"] == "DATA_UNAVAILABLE"
    assert lt["decision_state"] != "ELIGIBLE"


def test_unattractive_thesis_plus_event_block_never_ready():
    """Generic: FU thesis + EVENT_BLOCKED cannot yield long-term ELIGIBLE or swing READY."""
    p = _base()
    p["horizons"]["long_term"]["thesis_state"] = "FUNDAMENTALLY_UNATTRACTIVE"
    p["horizons"]["tactical"]["timing"] = "EVENT_BLOCKED"
    p = dp.materialize_packet(p)
    assert p["plan_families"]["long_term"]["decision_state"] == "REJECTED"
    assert p["plan_families"]["swing"]["action_state"] == "BLOCKED"
    inv = dp.assert_family_invariants(p)
    assert inv == [], inv


# ── 3. Options roll-up ────────────────────────────────────────────────────────

def test_options_all_rejected_is_not_conditional():
    p = dp.materialize_packet(_base())
    op = p["plan_families"]["options"]
    assert op["decision_state"] == "REJECTED"
    assert op["decision_state"] != "CONDITIONAL"


def test_options_conditional_requires_conditional_child():
    p = _base()
    p["plan_families"]["options"]["structures"] = [
        {"structure": "LONG_CALL", "state": "REJECTED", "rejection_reasons": ["x"]},
        {"structure": "POST_EARNINGS_REEVALUATION", "state": "CONDITIONAL",
         "condition": "after print", "reevaluate_after": "2026-08-13",
         "data_required": "post-earnings chain", "why_preferred": "IV crush"},
    ]
    p["plan_families"]["options"]["state"] = "CONDITIONAL"
    p = dp.materialize_packet(p)
    op = p["plan_families"]["options"]
    assert op["decision_state"] == "CONDITIONAL"
    kids = [s for s in op["structures"] if s.get("state") == "CONDITIONAL"]
    assert kids
    assert kids[0].get("activation_trigger")
    assert dp.assert_family_invariants(p) == []


# ── 4. No-trade semantics ─────────────────────────────────────────────────────

def test_no_trade_available_does_not_block_ready_swing():
    p = _base()
    p = dp.materialize_packet(p)
    nt = p["plan_families"]["no_trade"]
    assert nt["available"] is True
    assert nt["preferred"] is False
    assert nt["decision_state"] == "NOT_APPLICABLE"
    r = pol.evaluate_action(p, generated_at=p["evaluated_at"], now=NOW)
    assert r["action"] == "PROPOSE_ENTRY" and r["allowed"] is True


def test_no_trade_preferred_when_nothing_else_eligible():
    p = _base()
    p["plan_families"]["swing"] = {"family": "SWING", "state": "REJECTED", "structures": [
        {"structure": "TACTICAL_SWING", "state": "REJECTED", "rejection_reasons": ["x"]}]}
    p["plan_families"]["long_term"] = {"family": "LONG_TERM", "state": "REJECTED", "structures": [
        {"structure": "STAGED_SHARES", "state": "REJECTED", "rejection_reasons": ["x"]}]}
    p["horizons"]["long_term"]["thesis_state"] = "FUNDAMENTALLY_UNATTRACTIVE"
    p = dp.materialize_packet(p)
    nt = p["plan_families"]["no_trade"]
    assert nt["preferred"] is True
    r = pol.evaluate_action(p, generated_at=p["evaluated_at"], now=NOW)
    assert r["action"] == "NO_ACTION" and r["allowed"] is False


# ── 5. Position truth / covered-call applicability ────────────────────────────

def test_held_long_dominates_bearish_borrow_unknown():
    p = _base()
    p["ownership"] = {"held": True, "shares": 200.0, "uncommitted_shares": 200.0}
    p["plan_families"]["bearish"]["structures"] = [{
        "structure": "SHORT_STOCK", "state": "REJECTED",
        "rejection_reasons": ["borrow UNKNOWN — not constructible"],
    }]
    p = dp.materialize_packet(p)
    reasons = p["plan_families"]["bearish"]["structures"][0]["rejection_reasons"]
    assert any("held long" in str(r).lower() for r in reasons)


def test_covered_call_requires_uncommitted_shares():
    p = _base()
    p["ownership"] = {"held": True, "shares": 50.0, "uncommitted_shares": 50.0}
    p["plan_families"]["options"] = {
        "family": "OPTIONS", "state": "ELIGIBLE",
        "structures": [{"structure": "COVERED_CALL", "state": "ELIGIBLE"}],
    }
    p = dp.materialize_packet(p)
    cc = p["plan_families"]["options"]["structures"][0]
    assert cc["state"] == "NOT_APPLICABLE"
    assert "uncommitted" in str(cc["rejection_reasons"][0]).lower() or "100" in str(cc["rejection_reasons"][0])


def test_unheld_ownership_keeps_covered_call_not_applicable():
    """Any unheld symbol: covered-call must not claim share applicability."""
    p = _base()
    p["ownership"] = {"held": False, "shares": 0.0}
    p["plan_families"]["options"]["structures"] = [
        {"structure": "COVERED_CALL", "state": "NOT_APPLICABLE",
         "rejection_reasons": ["0 shares held"]},
        {"structure": "CALL_DEBIT_SPREAD", "state": "ELIGIBLE"},
    ]
    p = dp.materialize_packet(p)
    assert p["ownership"]["held"] is False
    states = {s["structure"]: s["state"] for s in p["plan_families"]["options"]["structures"]}
    assert states.get("COVERED_CALL") == "NOT_APPLICABLE"


# ── 6. Invariant suite ────────────────────────────────────────────────────────

def test_assert_family_invariants_flags_legacy_contradictions():
    p = _base()
    p["horizons"]["long_term"]["thesis_state"] = "FUNDAMENTALLY_UNATTRACTIVE"
    # Do NOT materialize — raw contradiction.
    errs = dp.assert_family_invariants(p)
    assert any("FUNDAMENTALLY_UNATTRACTIVE" in e for e in errs)


def test_insufficient_evidence_never_long_term_eligible_after_materialize():
    p = _base()
    p["horizons"]["long_term"]["thesis_state"] = "INSUFFICIENT_EVIDENCE"
    p = dp.materialize_packet(p)
    assert p["plan_families"]["long_term"]["decision_state"] != "ELIGIBLE"
    assert dp.assert_family_invariants(p) == []


def test_event_blocked_blocks_action_policy_for_any_symbol():
    p = _base()
    p["horizons"]["tactical"]["timing"] = "EVENT_BLOCKED"
    p["plan_families"]["swing"]["state"] = "ELIGIBLE"
    p = dp.materialize_packet(p)
    assert p["plan_families"]["swing"]["action_state"] == "BLOCKED"
    r = pol.evaluate_action(p, generated_at=p["evaluated_at"], now=NOW)
    assert r["allowed"] is False
