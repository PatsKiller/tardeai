#!/usr/bin/env python3
"""quote_selection_contract.py — canonical read-only quote selection
(cc-header-truth-v2 Phase 2 B).

Pins the eligibility + fallback + fail-closed semantics the header must share:

* a broker/account provider is never substituted for another broker's truth;
* an unauthenticated / unentitled / unhealthy / data-only-ineligible provider
  is never selected (and never appears as a selectable fallback);
* Finviz is selected when eligible; an eligible alternate is selected with a
  visible fallback reason when Finviz is unavailable; and when no candidate
  qualifies the result is an explicit UNAVAILABLE state with NO fabricated
  price.

No network, broker, scheduler, Drive, database or production path is touched.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib.quote_selection_contract import (  # noqa: E402
    FRESHNESS_STALE,
    STATUS_DEGRADED,
    STATUS_SELECTED,
    STATUS_UNAVAILABLE,
    candidate_eligibility,
    project_quote_selection,
    provider_capability,
    select_quote,
)


def _cand(provider, *, value=100.0, health="ok", freshness="CURRENT",
          entitlement="proven", authenticated=True, obs=None, src_hash=None):
    return {
        "provider": provider,
        "value": value,
        "health": health,
        "freshness": freshness,
        "entitlement": entitlement,
        "authenticated": authenticated,
        "observation_time": obs,
        "source_hash": src_hash,
    }


# ── provider capability matrix is data, not prose ────────────────────────────

def test_moomoo_is_data_only_and_never_a_quote_fallback():
    cap = provider_capability("moomoo")
    assert cap["role"] == "data_only"
    assert cap["quote_capable"] is False


def test_finviz_is_the_default_quote_source():
    assert provider_capability("finviz")["default_quote"] is True


def test_broker_account_providers_are_scope_own_positions():
    assert provider_capability("schwab")["scope"] == "own_positions"
    assert provider_capability("alpaca")["scope"] == "own_positions"


# ── eligibility: fail closed on every axis ───────────────────────────────────

@pytest.mark.parametrize(
    "kw,expect",
    [
        ({"entitlement": None}, False),          # unentitled
        ({"authenticated": False}, False),       # unauthenticated
        ({"health": "unknown"}, False),          # unhealthy
        ({"health": "unavailable"}, False),      # unhealthy
        ({"freshness": "UNAVAILABLE"}, False),   # no freshness
        ({"value": None}, False),                # no price
        ({"value": 0.0}, False),                 # non-positive price
        ({"entitlement": "proven", "authenticated": True, "health": "ok",
          "freshness": "CURRENT", "value": 100.0}, True),  # fully proven
    ],
)
def test_eligibility_axes(kw, expect):
    rec = candidate_eligibility("finviz", **kw)
    assert rec["eligible"] is expect


def test_data_only_provider_is_never_eligible():
    rec = candidate_eligibility("moomoo", authenticated=True, entitlement="proven",
                                health="ok", freshness="CURRENT", value=123.0)
    assert rec["eligible"] is False
    assert rec["rejected_reason"] == "role=data_only"


def test_unknown_provider_is_not_eligible():
    rec = candidate_eligibility("ghost", authenticated=True, entitlement="proven",
                                health="ok", freshness="CURRENT", value=123.0)
    assert rec["eligible"] is False
    assert rec["rejected_reason"] == "provider_unknown"


# ── selection: Finviz preferred, deterministic fallback, fail closed ─────────

def test_finviz_selected_when_eligible():
    sel = select_quote("AAPL", [
        _cand("finviz", value=201.5, obs="2026-09-03T14:30:00Z"),
        _cand("yahoo_cache", value=201.2),
    ])
    assert sel["status"] == STATUS_SELECTED
    assert sel["selected_provider"] == "finviz"
    assert sel["selected_value"] == 201.5
    assert sel["fallback_used"] is False
    assert sel["source_hash"]


def test_finviz_unavailable_falls_back_to_eligible_alternate_with_reason():
    sel = select_quote("AAPL", [
        _cand("finviz", value=None, health="unavailable"),
        _cand("yahoo_cache", value=199.9, obs="2026-09-03T14:30:00Z"),
        _cand("schwab", value=199.8, authenticated=True, entitlement="proven",
              health="ok", freshness="CURRENT"),
    ])
    assert sel["selected_provider"] == "yahoo_cache"
    assert sel["selected_value"] == 199.9
    assert sel["fallback_used"] is True
    assert "finviz" in (sel["fallback_reason"] or "")
    assert sel["status"] == STATUS_DEGRADED


def test_all_candidates_unavailable_is_explicit_unavailable_no_price():
    sel = select_quote("AAPL", [
        _cand("finviz", value=None, health="unavailable"),
        _cand("yahoo_cache", value=None, health="unavailable"),
        _cand("schwab", value=None, health="unavailable"),
    ])
    assert sel["status"] == STATUS_UNAVAILABLE
    assert sel["selected_provider"] is None
    assert sel["selected_value"] is None
    assert sel["quality"] == "UNAVAILABLE"


def test_ineligible_provider_is_never_selected_even_if_offered():
    # moomoo offers a price but is data-only → must be rejected, not selected.
    sel = select_quote("AAPL", [
        _cand("finviz", value=None, health="unavailable"),
        _cand("moomoo", value=777.0, authenticated=True, entitlement="proven",
              health="ok", freshness="CURRENT"),
        _cand("yahoo_cache", value=None, health="unavailable"),
    ])
    assert sel["status"] == STATUS_UNAVAILABLE
    assert sel["selected_value"] is None
    # The moomoo candidate must be present but ineligible.
    moomoo = next(c for c in sel["candidates"] if c["provider"] == "moomoo")
    assert moomoo["eligible"] is False


def test_stale_selected_quote_degrades_not_fabricates():
    sel = select_quote("AAPL", [
        _cand("finviz", value=201.5, freshness=FRESHNESS_STALE),
    ])
    assert sel["selected_provider"] == "finviz"
    assert sel["selected_value"] == 201.5
    assert sel["status"] == STATUS_DEGRADED
    assert sel["quality"] == "DEGRADED"


def test_observation_time_is_carried_through():
    obs = "2026-09-03T14:30:00Z"
    sel = select_quote("AAPL", [_cand("finviz", value=201.5, obs=obs)])
    assert sel["selected_observation_time"] == obs


# ── aggregate projection (header/portfolio surface) ─────────────────────────

def test_project_finviz_primary_no_fallback():
    proj = project_quote_selection(
        reprice_source="finviz_live",
        last_repriced="2026-09-03T14:30:00Z",
        source_counts={"finviz": 30},
        has_any_price=True,
    )
    assert proj["selected_provider"] == "finviz"
    assert proj["fallback_used"] is False
    assert proj["status"] == STATUS_SELECTED
    assert proj["quality"] == "OK"


def test_project_fallback_rows_degrades_with_reason():
    proj = project_quote_selection(
        reprice_source="finviz_live",
        last_repriced="2026-09-03T14:30:00Z",
        source_counts={"finviz": 20, "yahoo_cache_fallback": 10},
        has_any_price=True,
    )
    assert proj["fallback_used"] is True
    assert proj["status"] == STATUS_DEGRADED
    assert proj["quality"] == "DEGRADED"
    assert "yahoo_cache_fallback" in (proj["fallback_reason"] or "")


def test_project_no_price_fails_closed_unavailable():
    proj = project_quote_selection(
        reprice_source="",
        source_counts={},
        has_any_price=False,
    )
    assert proj["selected_provider"] is None
    assert proj["status"] == STATUS_UNAVAILABLE
    assert proj["quality"] == "UNAVAILABLE"


def test_project_candidate_board_names_roles():
    proj = project_quote_selection(
        reprice_source="finviz_live",
        source_counts={"finviz": 30},
        has_any_price=True,
    )
    by_name = {c["provider"]: c for c in proj["candidates"]}
    assert by_name["moomoo"]["role"] == "data_only"
    assert by_name["moomoo"]["quote_capable"] is False
    assert by_name["finviz"]["selected"] is True
    assert by_name["schwab"]["role"] == "broker_account"
