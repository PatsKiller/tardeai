#!/usr/bin/env python3
"""The canonical action-policy authority — the ONE source of action eligibility.

The card was made to display the packet but the buttons still gated on the legacy
one-word label (cioAvoid). So the card could say "constructive" while the buttons
behaved as though IGNORE were authoritative. This module is now the sole authority;
the card renders its result and cannot advertise an action the API refuses.

Invariants pinned here:
  - `allowed` is True ONLY when state == READY
  - READY requires an ELIGIBLE blueprint — never a model opinion
  - CONDITIONAL exposes the trigger but is never allowed (no masquerade-as-ready)
  - a STALE/CONFLICTED packet may only refresh/review
  - a BLOCKED/UNKNOWN event fails closed to monitoring
  - NO_TRADE ELIGIBLE blocks a proposal action
  - a valid packet cannot authorise a DIFFERENT symbol/version (input_hash)

Pure: no network, no database.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import decision_action_policy as pol  # noqa: E402

NOW = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)


def _packet(**over):
    p = {
        "symbol": "TEST", "packet_id": 1, "packet_version": "1.1.0-shadow",
        "evaluated_at": "2026-07-21T11:30:00Z",
        "price_used": 19.6, "facts_as_of": "2026-07-21T11:30:00Z",
        "event_state": {"impact": "CAUTION", "earnings": {"state": "SCHEDULED", "date": "2026-08-12"}},
        "data_quality": {"state": "FRESH"},
        "ownership": {"held": False, "shares": 0},
        "horizons": {"tactical": {"timing": "WAIT_FOR_PULLBACK",
                                  "trigger": "reclaim 19.96", "invalidation": "close below 15.15"}},
        "plan_families": {
            "swing": {"state": "CONDITIONAL", "structures": [{"underlying_trigger": "reclaim 19.96",
                                                              "underlying_invalidation": "close below 15.15"}]},
            "options": {"state": "CONDITIONAL", "structures": [{"state": "REJECTED"}]},
            "no_trade": {"state": "ELIGIBLE"},
        },
    }
    for k, v in over.items():
        p[k] = v
    return p


# ── allowed only when READY, and READY needs an eligible blueprint ────────────

def test_eligible_swing_is_the_only_thing_that_grants_propose():
    p = _packet()
    p["plan_families"]["swing"] = {"state": "ELIGIBLE", "structures": [{"state": "ELIGIBLE"}]}
    r = pol.evaluate_action(p, generated_at=p["evaluated_at"], now=NOW)
    assert r["action"] == "PROPOSE_ENTRY" and r["allowed"] is True and r["state"] == "READY"
    # and it still routes through approval + 2FA — never a direct order
    assert any("2FA" in c for c in r["required_confirmations"])


def test_conditional_swing_exposes_trigger_but_is_not_allowed():
    r = pol.evaluate_action(_packet(), generated_at="2026-07-21T11:30:00Z", now=NOW)
    assert r["allowed"] is False and r["state"] == "CONDITIONAL"
    assert any("reclaim 19.96" in w for w in r["warnings"]), "must expose the trigger"
    assert r["action"] != "PROPOSE_ENTRY"


def test_model_opinion_alone_never_grants_action():
    """A bullish long-term thesis with a conditional swing is still not allowed."""
    p = _packet()
    p["horizons"]["long_term"] = {"thesis_state": "STRONG_CONVICTION", "direction": "BULLISH"}
    r = pol.evaluate_action(p, generated_at=p["evaluated_at"], now=NOW)
    assert r["allowed"] is False   # thesis is not eligibility


# ── stale / event / no-trade gates ────────────────────────────────────────────

def test_stale_data_quality_permits_only_refresh():
    p = _packet(data_quality={"state": "STALE"})
    r = pol.evaluate_action(p, generated_at=p["evaluated_at"], now=NOW)
    assert r["action"] == "REFRESH" and r["allowed"] is False and r["state"] == "STALE"


def test_old_packet_is_stale_by_wallclock():
    p = _packet()
    old = (NOW - timedelta(hours=30)).isoformat()
    r = pol.evaluate_action(p, generated_at=old, now=NOW)
    assert r["state"] == "STALE" and r["action"] == "REFRESH"
    assert r.get("should_be_stale") is True
    assert r.get("packet_age_hours") is not None
    assert r.get("ttl_hours_applied") is not None


def test_rth_few_hour_ttl_marks_packet_stale():
    """During US cash session, star/buy plans older than ~4h must REFRESH.

    NOW at 16:00 UTC = 12:00 ET on a July weekday → RTH. A 5h-old packet
    exceeds the 4h RTH TTL but would still pass the legacy 12h overnight gate.
    """
    rth_now = datetime(2026, 7, 21, 16, 0, tzinfo=timezone.utc)  # 12:00 ET
    p = _packet()
    gen = (rth_now - timedelta(hours=5)).isoformat()
    r = pol.evaluate_action(p, generated_at=gen, now=rth_now)
    assert r["state"] == "STALE" and r["action"] == "REFRESH"
    assert r.get("should_be_stale") is True
    assert r.get("rth") is True
    assert r.get("ttl_hours_applied", 99) <= 4.0 + 1e-6
    assert any("RTH" in str(b) for b in r.get("blocks") or [])


def test_off_hours_allows_packet_under_12h():
    """Outside RTH the longer overnight TTL applies — 5h-old is still current."""
    off_now = datetime(2026, 7, 21, 2, 0, tzinfo=timezone.utc)  # 22:00 ET prior
    p = _packet()
    gen = (off_now - timedelta(hours=5)).isoformat()
    r = pol.evaluate_action(p, generated_at=gen, now=off_now, ttl_hours=None)
    # Not age-stale (other gates may still apply for CONDITIONAL)
    assert r.get("should_be_stale") is False
    assert r["state"] != "STALE" or "packet is" not in str(r.get("blocks") or [])
    assert r.get("ttl_hours_applied", 0) >= 12.0 - 1e-6


def test_blocked_event_fails_closed_to_monitor():
    p = _packet(event_state={"impact": "BLOCKED", "earnings": {}})
    r = pol.evaluate_action(p, generated_at=p["evaluated_at"], now=NOW)
    assert r["state"] == "BLOCKED" and r["allowed"] is False


def test_unknown_event_fails_closed():
    p = _packet(event_state={"impact": "UNKNOWN", "earnings": {}})
    r = pol.evaluate_action(p, generated_at=p["evaluated_at"], now=NOW)
    assert r["state"] == "BLOCKED"


def test_no_trade_eligible_blocks_when_nothing_else_is():
    p = _packet()
    p["plan_families"]["swing"] = {"state": "REJECTED", "structures": [{"state": "REJECTED"}]}
    p["plan_families"]["options"] = {"state": "REJECTED", "structures": [{"state": "REJECTED"}]}
    r = pol.evaluate_action(p, generated_at=p["evaluated_at"], now=NOW)
    assert r["action"] == "NO_ACTION" and r["allowed"] is False


def test_eligible_option_routes_to_research_not_propose():
    p = _packet()
    p["plan_families"]["swing"] = {"state": "REJECTED", "structures": [{"state": "REJECTED"}]}
    p["plan_families"]["options"] = {"state": "ELIGIBLE",
                                     "structures": [{"state": "ELIGIBLE", "occ_symbol": "X"}]}
    r = pol.evaluate_action(p, generated_at=p["evaluated_at"], now=NOW)
    assert r["action"] == "RESEARCH_OPTIONS" and r["allowed"] is True


def test_existing_proposal_blocks_a_second_propose():
    p = _packet()
    p["plan_families"]["swing"] = {"state": "ELIGIBLE", "structures": [{"state": "ELIGIBLE"}]}
    r = pol.evaluate_action(p, generated_at=p["evaluated_at"], existing_proposal=True, now=NOW)
    assert r["action"] != "PROPOSE_ENTRY" and r["allowed"] is False


# ── no packet is not a silent grant ───────────────────────────────────────────

def test_no_packet_routes_to_build_not_authority():
    r = pol.evaluate_action(None)
    assert r["action"] == "REFRESH" and r["allowed"] is False and r["state"] == "DATA_UNAVAILABLE"


# ── input hash binds a decision to its exact inputs ───────────────────────────

def test_input_hash_changes_when_material_inputs_change():
    a = pol.compute_input_hash(_packet())
    b = pol.compute_input_hash(_packet(price_used=25.0))
    c = pol.compute_input_hash(_packet(ownership={"held": True, "shares": 100}))
    assert a != b and a != c


def test_input_hash_stable_for_same_inputs():
    assert pol.compute_input_hash(_packet()) == pol.compute_input_hash(_packet())


def test_result_carries_provenance():
    r = pol.evaluate_action(_packet(), generated_at="2026-07-21T11:30:00Z", now=NOW)
    assert r["policy_version"] == pol.POLICY_VERSION
    assert r["packet_id"] == 1 and r["input_hash"]


# ── the frontend consumes it and legacy is a flagged fallback ─────────────────

def test_frontend_uses_action_policy_over_cioavoid():
    src = (ROOT / "apps" / "command-center-v3" / "src" / "lib" / "watchlistCardAction.ts").read_text()
    # the policy branch must come BEFORE the cioAvoid branch
    assert src.index("it.action_policy") < src.index("cioAvoid(it.latest_recommendation)")
    assert "policy_version" in src


def test_legacy_path_is_flagged_as_fallback():
    src = (ROOT / "apps" / "command-center-v3" / "src" / "lib" / "watchlistCardAction.ts").read_text()
    assert "LEGACY FALLBACK" in src


def test_conditional_policy_does_not_allow_primary_in_ui():
    """A CONDITIONAL/BLOCKED policy result must set allowPrimary:false in the card."""
    src = (ROOT / "apps" / "command-center-v3" / "src" / "lib" / "watchlistCardAction.ts").read_text()
    blk = src[src.index("CANONICAL ACTION POLICY"):src.index("const noStop")]
    assert "allowPrimary: false" in blk
