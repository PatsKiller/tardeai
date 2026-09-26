"""Strategy families this desk can validate. Absent families stay absent.

Pointer only. Does not widen gates or add generators.
"""
from __future__ import annotations

from typing import Any

LIFECYCLE = "config/options_lifecycle_policy.json"

MATRIX: dict[str, dict[str, Any]] = {
    "covered_call": {
        "family": "covered_call",
        "gates": ["share_coverage", "strike", "expiration", "upside_cap", "assignment", "income_yield", "stock_alternative"],
        "negative_cases": ["fewer_than_100_shares", "stale_quote", "missing_chain", "concentration_conflict"],
        "lifecycle": LIFECYCLE,
    },
    "cash_secured_put": {
        "family": "cash_secured_put",
        "gates": ["cash_reserve", "assignment_economics", "breakeven", "downside", "underlying_thesis"],
        "negative_cases": ["insufficient_cash", "deteriorating_thesis", "event_gap_risk", "missing_assignment_disclosure"],
        "lifecycle": LIFECYCLE,
    },
    "protective_put": {
        "family": "protective_put",
        "gates": ["hedge_need", "notional_covered", "convexity", "premium_drag", "replacement_timing"],
        "negative_cases": ["no_held_exposure", "hedge_no_longer_needed", "stale_chain", "excessive_premium"],
        "lifecycle": LIFECYCLE,
    },
    "long_call": {
        "family": "long_call",
        "gates": ["thesis_direction", "delta", "theta", "premium_at_risk", "expiration", "defined_maximum_loss"],
        "negative_cases": ["weak_thesis", "excessive_premium", "theta_burn", "missing_catalyst_or_horizon"],
        "lifecycle": LIFECYCLE,
    },
    "debit_spread": {
        "family": "vertical_debit",
        "gates": ["leg_identity", "width", "debit", "max_loss", "max_profit", "package_liquidity", "pop"],
        "negative_cases": ["incomplete_leg", "inconsistent_expiry", "unproven_multileg_route", "slippage_breach"],
        "lifecycle": LIFECYCLE,
    },
    "credit_spread": {
        "family": "vertical_credit",
        "gates": ["leg_identity", "width", "credit", "max_loss", "max_profit", "package_liquidity", "pop"],
        "negative_cases": ["incomplete_leg", "inconsistent_expiry", "unproven_multileg_route", "slippage_breach"],
        "lifecycle": LIFECYCLE,
    },
}

ABSENT = frozenset({
    "leaps_diagonal", "iron_condor", "iron_butterfly", "buffer_protect", "collar",
})

# Registry ids that are paper or research lanes, not missing matrix rows.
PAPER_OR_RESEARCH = frozenset({
    "deep_itm_call", "atm_call", "atm_put",
    "earnings_put_debit_spread", "earnings_put_credit_spread",
})


def known_family(strategy_id: str) -> bool:
    return strategy_id in MATRIX


def registry_gaps(registry_ids: list[str], *, live_only: bool = True, live_flags: dict[str, bool] | None = None) -> list[str]:
    """Ids with live_enabled that have no matrix row. Paper lanes are not gaps."""
    flags = live_flags or {}
    missing = []
    for sid in registry_ids:
        if sid in ABSENT or sid in PAPER_OR_RESEARCH or sid in MATRIX:
            continue
        if live_only and not flags.get(sid):
            continue
        missing.append(sid)
    return missing
