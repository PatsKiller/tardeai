#!/usr/bin/env python3
"""proposal_quote_trust.py — Classify quote trust and execution eligibility.

Read-only. No broker calls. No order submission.

Usage:
    from proposal_quote_trust import classify_quote_trust
    result = classify_quote_trust(proposal_dict)
"""
from datetime import datetime, timezone

# Provider execution eligibility — only Alpaca and Polygon with real-time bid/ask qualify
EXECUTION_ELIGIBLE_PROVIDERS = {"alpaca", "polygon"}
DISPLAY_ONLY_PROVIDERS = {"yfinance", "finviz", "finviz_cache"}
INFORMATIONAL_PROVIDERS = {"finnhub", "fmp"}

PROVIDER_RANK = {
    "alpaca": 1, "polygon": 2, "finnhub": 3, "fmp": 4,
    "yfinance": 5, "finviz": 6, "finviz_cache": 7,
}

# Max quote age by timeframe class (seconds)
MAX_QUOTE_AGE = {
    "INTRADAY": 120,
    "SHORT_SWING": 600,
    "MEDIUM_SWING": 1800,
    "POSITION": 3600,
}
DEFAULT_MAX_QUOTE_AGE = 900  # 15 min


def classify_quote_trust(proposal: dict) -> dict:
    """Classify quote trust for a proposal. Pure function, no side effects."""
    er = proposal.get("execution_readiness") or {}
    provider = (
        er.get("quote_provider")
        or proposal.get("quote_provider")
        or proposal.get("last_price_source")
        or "unknown"
    ).lower().strip()

    bid = er.get("bid")
    ask = er.get("ask")
    spread_pct = er.get("spread_pct")
    is_delayed = er.get("quote_is_delayed")
    quote_exec_eligible = er.get("quote_execution_eligible")
    quote_ts = er.get("quote_timestamp") or er.get("quote_price")  # fallback
    quote_age = er.get("quote_age_seconds")

    # Provider rank
    provider_rank = PROVIDER_RANK.get(provider, 99)

    # Execution eligibility
    if quote_exec_eligible is not None:
        is_exec = bool(quote_exec_eligible)
    else:
        is_exec = (
            provider in EXECUTION_ELIGIBLE_PROVIDERS
            and bid is not None
            and ask is not None
            and not is_delayed
        )

    bid_ask_available = bid is not None and ask is not None

    # Market session
    now = datetime.now(timezone.utc)
    hour = now.hour
    weekday = now.weekday()
    # NYSE: 9:30-16:00 ET = 13:30-20:00 UTC (standard), 14:30-21:00 (DST varies)
    # Simplified: 13:30-20:00 UTC weekdays
    if weekday >= 5:
        market_session = "weekend"
        trading_now = False
    elif 13 <= hour < 21:
        market_session = "regular_hours" if 14 <= hour < 20 else "extended_hours"
        trading_now = True
    else:
        market_session = "closed"
        trading_now = False

    # Quote age
    tc = proposal.get("strategy_timeframe_class") or "MEDIUM_SWING"
    max_age = MAX_QUOTE_AGE.get(tc, DEFAULT_MAX_QUOTE_AGE)

    if quote_age is not None:
        age_s = float(quote_age)
    else:
        age_s = None

    is_stale = age_s is not None and age_s > max_age

    # Display-only reason
    display_only_reason = None
    if provider in DISPLAY_ONLY_PROVIDERS:
        display_only_reason = f"{provider} is display-only, never execution-eligible"
    elif provider in INFORMATIONAL_PROVIDERS:
        display_only_reason = f"{provider} is informational/delayed"
    elif not bid_ask_available and provider in EXECUTION_ELIGIBLE_PROVIDERS:
        display_only_reason = "No bid/ask available from execution-eligible provider"
    elif is_delayed:
        display_only_reason = "Quote is delayed"

    # Status
    if is_exec and not is_stale:
        status = "EXECUTION_ELIGIBLE"
    elif provider in DISPLAY_ONLY_PROVIDERS:
        status = "DISPLAY_ONLY"
    elif is_stale:
        status = "STALE"
    elif not er:
        status = "NOT_CHECKED"
    elif not bid_ask_available:
        status = "MISSING_BID_ASK"
    elif not trading_now:
        status = "MARKET_CLOSED"
    else:
        status = "UNKNOWN"

    # Next action
    if status == "NOT_CHECKED":
        next_action = "Run Check Execution to get fresh quote"
    elif status == "DISPLAY_ONLY":
        next_action = "Run Check Execution for Alpaca/Polygon execution-eligible quote"
    elif status == "STALE":
        next_action = "Refresh quote — current is too old"
    elif status == "MISSING_BID_ASK":
        next_action = "Run Check Execution for bid/ask data"
    elif status == "MARKET_CLOSED":
        next_action = "Wait for market hours or approve with after-hours caution"
    elif status == "EXECUTION_ELIGIBLE":
        next_action = None
    else:
        next_action = "Run Check Execution"

    return {
        "quote_source": provider,
        "quote_provider_rank": provider_rank,
        "is_execution_eligible": is_exec,
        "quote_age_seconds": age_s,
        "max_allowed_age_seconds": max_age,
        "bid_ask_available": bid_ask_available,
        "spread_pct": float(spread_pct) if spread_pct is not None else None,
        "market_session": market_session,
        "trading_now": trading_now,
        "display_only_reason": display_only_reason,
        "quote_trust_status": status,
        "next_action": next_action,
    }
