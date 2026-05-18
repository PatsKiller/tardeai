#!/usr/bin/env python3
"""quote_provider_trust_policy.py — Quote provider eligibility and market-session rules.

Pure functions. No broker calls. No DB writes. No order submission.
"""
from datetime import datetime, timezone

EXEC_ELIGIBLE = {"alpaca", "polygon"}
DISPLAY_ONLY = {"yfinance", "finviz", "finviz_cache"}
INFORMATIONAL = {"finnhub", "fmp"}

PROVIDER_RANK = {"alpaca": 1, "polygon": 2, "finnhub": 3, "fmp": 4, "yfinance": 5, "finviz": 6}

# Max quote age (seconds) by strategy family + state
MAX_AGE = {
    ("INTRADAY_MOMENTUM", "pending"): 120,
    ("INTRADAY_MOMENTUM", "approval"): 60,
    ("GAP_EVENT", "pending"): 300,
    ("GAP_EVENT", "approval"): 120,
    ("SHORT_SWING", "pending"): 900,
    ("SHORT_SWING", "approval"): 300,
    ("MEDIUM_SWING", "pending"): 1800,
    ("MEDIUM_SWING", "approval"): 600,
    ("RECOVERY_WATCH", "pending"): 1800,
    ("DIVIDEND_CORE_COMPOUNDER", "pending"): 3600,
    ("DIVIDEND_CORE_COMPOUNDER", "approval"): 900,
}
DEFAULT_MAX_AGE = 900

SPREAD_LIMITS = {
    "INTRADAY_MOMENTUM": 1.5, "GAP_EVENT": 2.0, "SHORT_SWING": 3.0,
    "MEDIUM_SWING": 4.0, "RECOVERY_WATCH": 5.0, "DIVIDEND_CORE_COMPOUNDER": 3.0,
}


def classify_quote_provider(provider: str, quote: dict = None) -> dict:
    """Classify a quote provider's trust level."""
    p = (provider or "").lower().strip()
    q = quote or {}
    if p in EXEC_ELIGIBLE:
        level = "execution_eligible"
    elif p in DISPLAY_ONLY:
        level = "display_only"
    elif p in INFORMATIONAL:
        level = "informational"
    else:
        level = "unknown"
    return {
        "provider": p, "trust_level": level,
        "rank": PROVIDER_RANK.get(p, 99),
        "is_execution_eligible": level == "execution_eligible" and bool(q.get("bid")) and bool(q.get("ask")) and not q.get("is_delayed"),
        "display_only_reason": f"{p} is display-only" if level == "display_only" else None,
    }


def max_quote_age_seconds(strategy_family: str = "SHORT_SWING", proposal_state: str = "pending", session: str = "regular") -> int:
    """Return max acceptable quote age in seconds."""
    if session in ("closed", "weekend"):
        return 86400  # Accept stale during closed, but don't claim freshness
    return MAX_AGE.get((strategy_family, proposal_state), MAX_AGE.get((strategy_family, "pending"), DEFAULT_MAX_AGE))


def spread_limit_for_strategy(strategy_family: str = "SHORT_SWING") -> float:
    """Return max acceptable spread percentage."""
    return SPREAD_LIMITS.get(strategy_family, 5.0)


def is_execution_eligible_quote(provider: str, quote: dict, session: dict = None) -> dict:
    """Full execution eligibility check."""
    cp = classify_quote_provider(provider, quote)
    blockers = []
    warnings = []

    if not cp["is_execution_eligible"]:
        if cp["trust_level"] == "display_only":
            blockers.append(f"display_only: {provider}")
        elif cp["trust_level"] == "unknown":
            blockers.append(f"unknown_provider: {provider}")
        elif not quote.get("bid") or not quote.get("ask"):
            blockers.append("missing_bid_ask")
        elif quote.get("is_delayed"):
            blockers.append("quote_delayed")

    age = quote.get("quote_age_seconds")
    if age is not None and float(age) > max_quote_age_seconds():
        blockers.append(f"stale: {float(age):.0f}s")

    spread = quote.get("spread_pct")
    if spread is not None and float(spread) > spread_limit_for_strategy():
        blockers.append(f"wide_spread: {float(spread):.1f}%")

    return {
        "eligible": len(blockers) == 0, "provider": provider,
        "trust_level": cp["trust_level"], "blockers": blockers, "warnings": warnings,
    }


def quote_next_action(quote_status: dict) -> str:
    """Recommend next action based on quote status."""
    blockers = quote_status.get("blockers", [])
    if not blockers:
        return None
    if any("display_only" in b for b in blockers):
        return "Run Check Execution for Alpaca/Polygon quote"
    if any("unknown" in b for b in blockers):
        return "Run Check Execution to identify quote provider"
    if any("stale" in b for b in blockers):
        return "Refresh quote — current is too old"
    if any("missing_bid_ask" in b for b in blockers):
        return "Run Check Execution for bid/ask data"
    if any("wide_spread" in b for b in blockers):
        return "Wait for tighter spread or accept with caution"
    return "Run Check Execution"
