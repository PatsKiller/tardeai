#!/usr/bin/env python3
"""strategy_eligibility_gate_policy.py — Pre-router eligibility gates.

Pure functions. No DB writes. No broker calls.
"""

DAILY_SCALP_SOURCES = {"daily_momentum_scalp", "tradeai_daily_scalp", "external_scalp"}

# Family-sensitive defaults
SPREAD_MAX = {"INTRADAY": 2.0, "SHORT_SWING": 3.0, "MEDIUM_SWING": 5.0, "POSITION": 8.0}
QUOTE_MAX_AGE = {"INTRADAY": 300, "SHORT_SWING": 3600, "MEDIUM_SWING": 7200, "POSITION": 86400}
MIN_PRICE = {"INTRADAY": 1.0, "SHORT_SWING": 1.0, "MEDIUM_SWING": 1.0, "POSITION": 3.0}


def evaluate_basic_eligibility(candidate: dict) -> dict:
    """Check basic data presence and out-of-scope sources."""
    blockers = []
    warnings = []
    missing = []

    if not candidate.get("symbol"):
        blockers.append("missing_symbol")
    if not candidate.get("price") and not candidate.get("proposed_entry"):
        missing.append("price")

    source = (candidate.get("discovery_source") or candidate.get("proposed_by") or "").lower()
    if source in DAILY_SCALP_SOURCES:
        blockers.append("out_of_scope_daily_scalp")

    status = "BLOCK" if blockers else "WARN" if missing else "PASS"
    return {"eligible": status != "BLOCK", "status": status, "blockers": blockers,
            "warnings": warnings, "missing_fields": missing, "gate_version": "eligibility_v1"}


def evaluate_liquidity_eligibility(candidate: dict, strategy_family: str = None) -> dict:
    """Check price, volume, spread, and liquidity thresholds."""
    blockers = []
    warnings = []
    family = (strategy_family or "SHORT_SWING").upper()

    price = float(candidate.get("price") or candidate.get("proposed_entry") or 0)
    min_p = MIN_PRICE.get(family, 1.0)
    if price > 0 and price < min_p:
        blockers.append(f"price_below_min: ${price:.2f} < ${min_p:.2f}")

    spread = candidate.get("spread_pct")
    if spread is not None:
        max_sp = SPREAD_MAX.get(family, 5.0)
        if float(spread) > max_sp:
            blockers.append(f"spread_too_wide: {float(spread):.1f}% > {max_sp:.1f}%")
        elif float(spread) > max_sp * 0.7:
            warnings.append(f"spread_elevated: {float(spread):.1f}%")

    rvol = candidate.get("rvol")
    if family == "INTRADAY" and (not rvol or float(rvol or 0) < 1.0):
        warnings.append("low_rvol_for_intraday")

    status = "BLOCK" if blockers else "WARN" if warnings else "PASS"
    return {"eligible": status != "BLOCK", "status": status, "blockers": blockers,
            "warnings": warnings, "gate_version": "liquidity_v1"}


def evaluate_quote_eligibility(candidate: dict) -> dict:
    """Check quote freshness and execution eligibility."""
    blockers = []
    warnings = []
    er = candidate.get("execution_readiness") or {}
    provider = (er.get("quote_provider") or candidate.get("last_price_source") or "").lower()
    age = er.get("quote_age_seconds")

    if not provider or provider == "unknown":
        warnings.append("quote_provider_unknown")
    if provider in ("finviz", "finviz_cache", "yfinance"):
        warnings.append(f"display_only_provider: {provider}")

    if age is not None and float(age) > 86400:
        blockers.append(f"quote_extremely_stale: {float(age):.0f}s")
    elif age is not None and float(age) > 7200:
        warnings.append(f"quote_stale: {float(age):.0f}s")

    status = "BLOCK" if blockers else "WARN" if warnings else "PASS"
    return {"eligible": status != "BLOCK", "status": status, "blockers": blockers,
            "warnings": warnings, "gate_version": "quote_eligibility_v1"}


def summarize_eligibility_blockers(candidate: dict) -> list:
    """Combine all eligibility gate blockers."""
    basic = evaluate_basic_eligibility(candidate)
    liquidity = evaluate_liquidity_eligibility(candidate)
    quote = evaluate_quote_eligibility(candidate)
    all_blockers = basic["blockers"] + liquidity["blockers"] + quote["blockers"]
    all_warnings = basic["warnings"] + liquidity["warnings"] + quote["warnings"]
    return all_blockers + [f"WARN: {w}" for w in all_warnings]
