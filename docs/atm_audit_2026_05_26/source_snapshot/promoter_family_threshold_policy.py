#!/usr/bin/env python3
"""promoter_family_threshold_policy.py — Family-specific promoter readiness thresholds.

Pure functions. No DB writes. No proposal creation. No trades/orders.
"""
FAMILY_MAP = {
    'momentum_scalp': 'INTRADAY_MOMENTUM',
    'gap_and_go': 'GAP_EVENT',
    'swing_breakout': 'SHORT_SWING',
    'swing_trade': 'MEDIUM_SWING',
    'recovery_watch': 'RECOVERY_WATCH',
    'earnings_catalyst': 'EARNINGS_CATALYST',
    'earnings_pre_buildup': 'EARNINGS_PRE',
    'earnings_post_momentum': 'EARNINGS_POST',
    'speculative_growth': 'SPECULATIVE_GROWTH',
    'sector_rotation': 'SECTOR_ROTATION',
    'dividend_growth_compounder': 'DIVIDEND_INCOME',
    'income_add': 'DIVIDEND_INCOME',
    'reit_income': 'DIVIDEND_INCOME',
    'high_yield_income_bdc': 'DIVIDEND_INCOME',
    'international_dividend': 'DIVIDEND_INCOME',
    'bond_income': 'FIXED_INCOME',
    'cash_or_stable': 'FIXED_INCOME',
    'core_growth_compounder': 'CORE_GROWTH',
    'core_index': 'CORE_INDEX',
    'covered_call_income': 'OPTIONS_INCOME',
    'fib_retracement_bounce': 'TECHNICAL_PATTERN',
    'defense_thesis': 'THEMATIC',
    'tax_loss_harvest': 'TAX_STRATEGY',
}

FAMILY_THRESHOLDS = {
    'INTRADAY_MOMENTUM': {
        'max_spread_pct': 3.0,
        'min_rvol': 3.0,
        'min_score': 35,
        'require_catalyst': True,
        'require_fresh_quote': True,
        'require_market_hours': True,
        'require_earnings_date': False,
        'require_dividend_data': False,
        'require_options_chain': False,
        'require_technical_pattern': False,
    },
    'GAP_EVENT': {
        'max_spread_pct': 3.0,
        'min_rvol': 2.0,
        'min_score': 30,
        'require_catalyst': True,
        'require_fresh_quote': True,
        'require_market_hours': True,
        'require_earnings_date': False,
        'require_dividend_data': False,
        'require_options_chain': False,
        'require_technical_pattern': False,
    },
    'SHORT_SWING': {
        'max_spread_pct': 5.0,
        'min_rvol': 1.5,
        'min_score': 25,
        'require_catalyst': False,
        'require_fresh_quote': True,
        'require_market_hours': False,
        'require_earnings_date': False,
        'require_dividend_data': False,
        'require_options_chain': False,
        'require_technical_pattern': False,
    },
    'MEDIUM_SWING': {
        'max_spread_pct': 5.0,
        'min_rvol': 1.0,
        'min_score': 20,
        'require_catalyst': False,
        'require_fresh_quote': True,
        'require_market_hours': False,
        'require_earnings_date': False,
        'require_dividend_data': False,
        'require_options_chain': False,
        'require_technical_pattern': False,
    },
    'RECOVERY_WATCH': {
        'max_spread_pct': 5.0,
        'min_rvol': 0.5,
        'min_score': 15,
        'require_catalyst': False,
        'require_fresh_quote': True,
        'require_market_hours': False,
        'require_earnings_date': False,
        'require_dividend_data': False,
        'require_options_chain': False,
        'require_technical_pattern': False,
    },
    'DIVIDEND_INCOME': {
        'max_spread_pct': 8.0,
        'min_rvol': 0.0,
        'min_score': 15,  # MAP-5: lowered from 30 (momentum default) to 15 for income
        'require_catalyst': False,
        'require_fresh_quote': True,
        'require_market_hours': False,
        'require_earnings_date': False,
        'require_dividend_data': True,
        'require_options_chain': False,
        'require_technical_pattern': False,
        'min_avg_volume': 50000,
        'use_dividend_scoring': True,  # MAP-5: use dividend_income_scoring_policy
    },
    'FIXED_INCOME': {
        'max_spread_pct': 10.0,
        'min_rvol': 0.0,
        'min_score': 5,
        'require_catalyst': False,
        'require_fresh_quote': False,
        'require_market_hours': False,
        'require_earnings_date': False,
        'require_dividend_data': False,
        'require_options_chain': False,
        'require_technical_pattern': False,
    },
    'EARNINGS_CATALYST': {
        'max_spread_pct': 5.0,
        'min_rvol': 1.0,
        'min_score': 20,
        'require_catalyst': True,
        'require_fresh_quote': True,
        'require_market_hours': False,
        'require_earnings_date': True,
        'require_dividend_data': False,
        'require_options_chain': False,
        'require_technical_pattern': False,
    },
    'EARNINGS_PRE': {
        'max_spread_pct': 5.0,
        'min_rvol': 0.5,
        'min_score': 15,
        'require_catalyst': False,
        'require_fresh_quote': True,
        'require_market_hours': False,
        'require_earnings_date': True,
        'require_dividend_data': False,
        'require_options_chain': False,
        'require_technical_pattern': False,
    },
    'EARNINGS_POST': {
        'max_spread_pct': 5.0,
        'min_rvol': 1.0,
        'min_score': 20,
        'require_catalyst': True,
        'require_fresh_quote': True,
        'require_market_hours': False,
        'require_earnings_date': True,
        'require_dividend_data': False,
        'require_options_chain': False,
        'require_technical_pattern': False,
    },
    'TECHNICAL_PATTERN': {
        'max_spread_pct': 5.0,
        'min_rvol': 0.5,
        'min_score': 15,
        'require_catalyst': False,
        'require_fresh_quote': True,
        'require_market_hours': False,
        'require_earnings_date': False,
        'require_dividend_data': False,
        'require_options_chain': False,
        'require_technical_pattern': True,
    },
    'OPTIONS_INCOME': {
        'max_spread_pct': 5.0,
        'min_rvol': 0.0,
        'min_score': 10,
        'require_catalyst': False,
        'require_fresh_quote': True,
        'require_market_hours': False,
        'require_earnings_date': False,
        'require_dividend_data': False,
        'require_options_chain': True,
        'require_technical_pattern': False,
    },
    'SECTOR_ROTATION': {
        'max_spread_pct': 5.0,
        'min_rvol': 0.5,
        'min_score': 15,
        'require_catalyst': False,
        'require_fresh_quote': True,
        'require_market_hours': False,
        'require_earnings_date': False,
        'require_dividend_data': False,
        'require_options_chain': False,
        'require_technical_pattern': False,
    },
    'SPECULATIVE_GROWTH': {
        'max_spread_pct': 5.0,
        'min_rvol': 1.0,
        'min_score': 20,
        'require_catalyst': True,
        'require_fresh_quote': True,
        'require_market_hours': False,
        'require_earnings_date': False,
        'require_dividend_data': False,
        'require_options_chain': False,
        'require_technical_pattern': False,
    },
    'CORE_GROWTH': {
        'max_spread_pct': 5.0,
        'min_rvol': 0.0,
        'min_score': 15,
        'require_catalyst': False,
        'require_fresh_quote': True,
        'require_market_hours': False,
        'require_earnings_date': False,
        'require_dividend_data': False,
        'require_options_chain': False,
        'require_technical_pattern': False,
    },
    'CORE_INDEX': {
        'max_spread_pct': 2.0,
        'min_rvol': 0.0,
        'min_score': 5,
        'require_catalyst': False,
        'require_fresh_quote': False,
        'require_market_hours': False,
        'require_earnings_date': False,
        'require_dividend_data': False,
        'require_options_chain': False,
        'require_technical_pattern': False,
    },
    'THEMATIC': {
        'max_spread_pct': 5.0,
        'min_rvol': 0.5,
        'min_score': 15,
        'require_catalyst': False,
        'require_fresh_quote': True,
        'require_market_hours': False,
        'require_earnings_date': False,
        'require_dividend_data': False,
        'require_options_chain': False,
        'require_technical_pattern': False,
    },
    'TAX_STRATEGY': {
        'max_spread_pct': 8.0,
        'min_rvol': 0.0,
        'min_score': 5,
        'require_catalyst': False,
        'require_fresh_quote': False,
        'require_market_hours': False,
        'require_earnings_date': False,
        'require_dividend_data': False,
        'require_options_chain': False,
        'require_technical_pattern': False,
    },
}

DEFAULT_THRESHOLDS = FAMILY_THRESHOLDS['MEDIUM_SWING']


def get_strategy_family(strategy_id: str) -> str:
    return FAMILY_MAP.get(strategy_id, 'MEDIUM_SWING')


def get_family_thresholds(strategy_id: str) -> dict:
    family = get_strategy_family(strategy_id)
    return FAMILY_THRESHOLDS.get(family, DEFAULT_THRESHOLDS)


def evaluate_candidate(candidate: dict, strategy_id: str) -> dict:
    """Evaluate a candidate against family-specific thresholds.
    Returns readiness assessment. No DB writes."""
    family = get_strategy_family(strategy_id)
    thresholds = get_family_thresholds(strategy_id)

    passed = []
    failed = []
    warnings = []
    missing = []

    spread = candidate.get("spread_pct")
    rvol = candidate.get("rvol") or candidate.get("rvol_latest") or 0
    score = candidate.get("score") or candidate.get("latest_score") or candidate.get("baseline_score") or 0
    has_catalyst = bool(candidate.get("catalyst"))
    has_fresh_quote = candidate.get("has_fresh_quote", True)

    # Spread
    if spread is not None:
        if spread <= thresholds["max_spread_pct"]:
            passed.append(f"spread {spread:.1f}% <= {thresholds['max_spread_pct']}%")
        else:
            failed.append(f"spread {spread:.1f}% > {thresholds['max_spread_pct']}% (family: {family})")
    else:
        warnings.append("spread unknown")

    # RVOL
    if rvol >= thresholds.get("min_rvol", 0):
        passed.append(f"rvol {rvol:.1f} >= {thresholds.get('min_rvol', 0)}")
    else:
        failed.append(f"rvol {rvol:.1f} < {thresholds.get('min_rvol', 0)} (family: {family})")

    # Score
    if score >= thresholds.get("min_score", 0):
        passed.append(f"score {score} >= {thresholds.get('min_score', 0)}")
    else:
        failed.append(f"score {score} < {thresholds.get('min_score', 0)}")

    # Catalyst
    if thresholds.get("require_catalyst") and not has_catalyst:
        failed.append("catalyst required but missing")

    # Earnings date
    if thresholds.get("require_earnings_date"):
        if not candidate.get("earnings_date"):
            missing.append("earnings_date")
            failed.append("earnings date required but missing")

    # Dividend data
    if thresholds.get("require_dividend_data"):
        if not candidate.get("dividend_yield") and not candidate.get("has_dividend_data"):
            warnings.append("dividend data preferred but missing")

    # Options chain
    if thresholds.get("require_options_chain"):
        if not candidate.get("has_options_chain"):
            missing.append("options_chain")
            failed.append("options chain required — PROVIDER_MISSING")

    # Technical pattern
    if thresholds.get("require_technical_pattern"):
        if not candidate.get("has_technical_pattern"):
            warnings.append("technical pattern evidence preferred but missing")

    # Determine status
    if any("PROVIDER_MISSING" in f for f in failed):
        status = "PROVIDER_MISSING"
    elif len(failed) > 0:
        status = "BLOCKED"
    elif len(missing) > 0:
        status = "NEEDS_DATA"
    elif len(warnings) > 0:
        status = "READY_SHADOW"
    else:
        status = "READY_SHADOW"

    return {
        "family": family,
        "strategy_id": strategy_id,
        "readiness_status": status,
        "score": max(0, 100 - len(failed) * 25 - len(warnings) * 10),
        "thresholds_used": thresholds,
        "passed": passed,
        "failed": failed,
        "warnings": warnings,
        "missing_fields": missing,
        "human_review_only": True,
        "proposal_eligible": False,
        "policy_version": "promoter_family_thresholds_v1",
    }
