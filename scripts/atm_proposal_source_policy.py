#!/usr/bin/env python3
"""Source-neutral ATM eligibility — curated pipelines (pullback/MACD, watchlist, auto) vs generic.

Curated proposals ship with authoritative entry/stop/target from their screener or watchlist
path. On paper accounts they may fast-track past the enrichment queue without bias toward
auto-generated-only proposals.
"""
from __future__ import annotations

CURATED_DISCOVERY = frozenset({"pullback_macd", "watchlist", "screener", "incubator"})
CURATED_ORIGINS = frozenset({"watchlist"})

# Min R:R for curated fast-track (screener already validated structure)
MIN_RR_PULLBACK = 1.2
MIN_RR_WATCHLIST = 2.0
MIN_RR_DEFAULT_CURATED = 1.5
MAX_AGE_HOURS_PULLBACK = 48.0
MAX_AGE_HOURS_WATCHLIST = 24.0


def is_curated_proposal(proposal: dict) -> bool:
    ds = str(proposal.get("discovery_source") or "").lower()
    origin = str(proposal.get("origin") or "").lower()
    return ds in CURATED_DISCOVERY or origin in CURATED_ORIGINS


def _has_complete_levels(proposal: dict) -> bool:
    try:
        entry = float(proposal.get("proposed_entry") or 0)
        stop = float(proposal.get("proposed_stop") or 0)
        target = float(proposal.get("proposed_target1") or 0)
    except (TypeError, ValueError):
        return False
    return entry > 0 and stop > 0 and target > 0 and entry > stop and target > entry


def _min_rr(proposal: dict) -> float:
    ds = str(proposal.get("discovery_source") or "").lower()
    if ds == "pullback_macd":
        return MIN_RR_PULLBACK
    if ds == "watchlist" or str(proposal.get("origin") or "").lower() == "watchlist":
        return MIN_RR_WATCHLIST
    return MIN_RR_DEFAULT_CURATED


def _max_age_hours(proposal: dict) -> float:
    ds = str(proposal.get("discovery_source") or "").lower()
    if ds == "pullback_macd":
        return MAX_AGE_HOURS_PULLBACK
    if ds == "watchlist" or str(proposal.get("origin") or "").lower() == "watchlist":
        return MAX_AGE_HOURS_WATCHLIST
    return 4.0


def curated_fast_track_eligible(
    proposal: dict,
    *,
    acct_mode: str,
    proposal_age_hours: float,
) -> tuple[bool, str]:
    """Paper curated proposals with complete levels may skip enrichment wait."""
    if acct_mode != "paper":
        return False, "not_paper_account"
    if not is_curated_proposal(proposal):
        return False, "not_curated_source"
    if not _has_complete_levels(proposal):
        return False, "incomplete_entry_stop_target"
    rg = str(proposal.get("risk_gate_result") or "").upper()
    if rg in ("REJECTED", "FAIL", "BLOCKED"):
        return False, f"risk_gate_{rg.lower()}"
    # Paper curated: ADVISORY is acceptable (pullback screener default); hard rejects still block.
    if rg not in ("APPROVED", "ADVISORY", "PASSED", "PASS", ""):
        return False, f"risk_gate_{rg.lower()}"
    try:
        rr = float(proposal.get("proposed_rr") or 0)
    except (TypeError, ValueError):
        rr = 0.0
    min_rr = _min_rr(proposal)
    if rr < min_rr:
        return False, f"rr_{rr:.2f}_below_{min_rr}"
    max_age = _max_age_hours(proposal)
    if proposal_age_hours > max_age:
        return False, f"age_{proposal_age_hours:.1f}h_over_{max_age}h"
    return True, "curated_fast_track"


def generic_fast_track_eligible(
    proposal: dict,
    *,
    acct_mode: str,
    proposal_age_hours: float,
) -> bool:
    """Legacy paper fast-track (any source): fresh, R:R≥2, risk APPROVED."""
    if acct_mode != "paper":
        return False
    try:
        rr = float(proposal.get("proposed_rr") or 0)
    except (TypeError, ValueError):
        rr = 0.0
    rg = str(proposal.get("risk_gate_result") or "").upper()
    return (
        proposal_age_hours < 1.0
        and rr >= 2.0
        and rg in ("APPROVED", "PASSED", "PASS")
    )


def atm_enrichment_bypass(proposal: dict, *, acct_mode: str, proposal_age_hours: float) -> tuple[bool, str]:
    """Unified check: curated fast-track OR generic fast-track."""
    ok, reason = curated_fast_track_eligible(proposal, acct_mode=acct_mode, proposal_age_hours=proposal_age_hours)
    if ok:
        return True, reason
    if generic_fast_track_eligible(proposal, acct_mode=acct_mode, proposal_age_hours=proposal_age_hours):
        return True, "generic_fast_track"
    return False, reason