#!/usr/bin/env python3
"""strategy_watch_horizon_policy.py — Strategy-specific watch windows and maturity states.

Pure functions only. No DB writes. No side effects.

Usage:
    from strategy_watch_horizon_policy import get_default_watch_horizon, classify_candidate_watch_state
"""

# Watch horizon defaults per strategy (trading days)
WATCH_HORIZONS = {
    "momentum_scalp":            {"min_days": 0, "max_days": 2,   "refresh_freq": "intraday",  "backtest_required": False, "fib_required": False, "orb_required": True,  "catalyst_required": False, "technical_required": ["RSI", "RVOL", "VWAP"]},
    "gap_and_go":                {"min_days": 0, "max_days": 2,   "refresh_freq": "intraday",  "backtest_required": False, "fib_required": False, "orb_required": True,  "catalyst_required": False, "technical_required": ["RSI", "RVOL", "gap_pct"]},
    "earnings_catalyst":         {"min_days": 1, "max_days": 10,  "refresh_freq": "daily",     "backtest_required": False, "fib_required": False, "orb_required": False, "catalyst_required": True,  "technical_required": ["RSI", "ATR"]},
    "earnings_pre_buildup":      {"min_days": 3, "max_days": 15,  "refresh_freq": "daily",     "backtest_required": False, "fib_required": False, "orb_required": False, "catalyst_required": True,  "technical_required": ["RSI", "ATR", "EMA"]},
    "earnings_post_momentum":    {"min_days": 1, "max_days": 10,  "refresh_freq": "daily",     "backtest_required": False, "fib_required": False, "orb_required": False, "catalyst_required": True,  "technical_required": ["RSI", "RVOL"]},
    "swing_breakout":            {"min_days": 3, "max_days": 15,  "refresh_freq": "daily",     "backtest_required": True,  "fib_required": True,  "orb_required": False, "catalyst_required": False, "technical_required": ["RSI", "ATR", "EMA", "VWAP"]},
    "swing_trade":               {"min_days": 5, "max_days": 30,  "refresh_freq": "daily",     "backtest_required": True,  "fib_required": True,  "orb_required": False, "catalyst_required": False, "technical_required": ["RSI", "ATR", "EMA", "VWAP"]},
    "recovery_watch":            {"min_days": 5, "max_days": 20,  "refresh_freq": "daily",     "backtest_required": True,  "fib_required": True,  "orb_required": False, "catalyst_required": True,  "technical_required": ["RSI", "ATR", "EMA"]},
    "speculative_growth":        {"min_days": 10, "max_days": 45, "refresh_freq": "daily",     "backtest_required": True,  "fib_required": False, "orb_required": False, "catalyst_required": True,  "technical_required": ["RSI", "ATR", "EMA"]},
    "sector_rotation":           {"min_days": 10, "max_days": 60, "refresh_freq": "weekly",    "backtest_required": True,  "fib_required": False, "orb_required": False, "catalyst_required": False, "technical_required": ["RSI", "EMA"]},
    "fib_retracement_bounce":    {"min_days": 3, "max_days": 20,  "refresh_freq": "daily",     "backtest_required": True,  "fib_required": True,  "orb_required": False, "catalyst_required": False, "technical_required": ["RSI", "ATR", "EMA", "Fib"]},
    "dividend_growth_compounder":{"min_days": 30, "max_days": 180,"refresh_freq": "weekly",    "backtest_required": False, "fib_required": False, "orb_required": False, "catalyst_required": False, "technical_required": ["RSI"]},
    "core_growth_compounder":    {"min_days": 30, "max_days": 180,"refresh_freq": "weekly",    "backtest_required": False, "fib_required": False, "orb_required": False, "catalyst_required": False, "technical_required": ["RSI", "EMA"]},
    "income_add":                {"min_days": 14, "max_days": 90, "refresh_freq": "weekly",    "backtest_required": False, "fib_required": False, "orb_required": False, "catalyst_required": False, "technical_required": ["RSI"]},
    "covered_call_income":       {"min_days": 14, "max_days": 90, "refresh_freq": "weekly",    "backtest_required": False, "fib_required": False, "orb_required": False, "catalyst_required": False, "technical_required": []},
    "bond_income":               {"min_days": 14, "max_days": 180,"refresh_freq": "weekly",    "backtest_required": False, "fib_required": False, "orb_required": False, "catalyst_required": False, "technical_required": []},
    "high_yield_income_bdc":     {"min_days": 14, "max_days": 90, "refresh_freq": "weekly",    "backtest_required": False, "fib_required": False, "orb_required": False, "catalyst_required": False, "technical_required": []},
    "reit_income":               {"min_days": 14, "max_days": 90, "refresh_freq": "weekly",    "backtest_required": False, "fib_required": False, "orb_required": False, "catalyst_required": False, "technical_required": ["RSI"]},
    "international_dividend":    {"min_days": 30, "max_days": 180,"refresh_freq": "weekly",    "backtest_required": False, "fib_required": False, "orb_required": False, "catalyst_required": False, "technical_required": []},
    "defense_thesis":            {"min_days": 10, "max_days": 60, "refresh_freq": "weekly",    "backtest_required": False, "fib_required": False, "orb_required": False, "catalyst_required": True,  "technical_required": ["RSI", "EMA"]},
    "cash_or_stable":            {"min_days": 0, "max_days": 365, "refresh_freq": "monthly",   "backtest_required": False, "fib_required": False, "orb_required": False, "catalyst_required": False, "technical_required": []},
    "core_index":                {"min_days": 0, "max_days": 365, "refresh_freq": "monthly",   "backtest_required": False, "fib_required": False, "orb_required": False, "catalyst_required": False, "technical_required": []},
    "tax_loss_harvest":          {"min_days": 5, "max_days": 30,  "refresh_freq": "weekly",    "backtest_required": False, "fib_required": False, "orb_required": False, "catalyst_required": False, "technical_required": []},
}

DEFAULT_HORIZON = {"min_days": 5, "max_days": 30, "refresh_freq": "daily", "backtest_required": False, "fib_required": False, "orb_required": False, "catalyst_required": False, "technical_required": ["RSI"]}


def get_default_watch_horizon(strategy_id: str) -> dict:
    """Return watch horizon config for a strategy."""
    return WATCH_HORIZONS.get(strategy_id, DEFAULT_HORIZON).copy()


def classify_candidate_watch_state(candidate: dict, strategy_id: str = None) -> dict:
    """Classify candidate maturity state. Pure function."""
    sid = strategy_id or candidate.get("strategy_id", "")
    horizon = get_default_watch_horizon(sid)
    age_days = candidate.get("age_days", 0) or 0

    # Check data availability
    has_technical = bool(candidate.get("technical_snapshot") or candidate.get("rsi"))
    has_catalyst = bool(candidate.get("catalyst_verified") or candidate.get("catalyst"))
    has_backtest = bool(candidate.get("backtest_summary") or candidate.get("backtest_exists"))
    has_fib = bool(candidate.get("fib_context") or candidate.get("fib_status") == "available")
    has_orb = bool(candidate.get("orb_status") and candidate.get("orb_status") not in ("not_applicable", "missing_required", "not_checked"))
    has_execution = bool(candidate.get("execution_readiness"))
    has_ai_review = bool(candidate.get("agent_reviews") or candidate.get("llm_analysis"))

    # Disqualification checks
    disqualified = False
    disqualified_reason = None
    if candidate.get("status") in ("REJECTED", "EXPIRED", "KILLED"):
        disqualified = True
        disqualified_reason = f"Status: {candidate.get('status')}"
    elif candidate.get("risk_gate_result") in ("REJECTED", "FAIL"):
        disqualified = True
        disqualified_reason = "Risk gate rejected"

    if disqualified:
        return {"watch_state": "disqualified", "reason": disqualified_reason, "horizon": horizon, "age_days": age_days}

    # Expiration check
    if age_days > horizon["max_days"]:
        return {"watch_state": "expired", "reason": f"Age {age_days}d exceeds max {horizon['max_days']}d", "horizon": horizon, "age_days": age_days}

    # Insufficient data
    missing = []
    if horizon["catalyst_required"] and not has_catalyst:
        missing.append("catalyst")
    if horizon["backtest_required"] and not has_backtest:
        missing.append("backtest")
    if horizon["fib_required"] and not has_fib:
        missing.append("fib")
    if horizon["orb_required"] and not has_orb:
        missing.append("orb")
    for t in horizon["technical_required"]:
        if not has_technical:
            missing.append(t)
            break

    # State classification
    if age_days < horizon["min_days"]:
        state = "new_candidate" if age_days < 1 else "observing"
    elif missing:
        state = "insufficient_data"
    elif not has_execution and not has_ai_review:
        state = "maturing"
    elif has_execution and has_ai_review:
        state = "ready_for_proposal" if not missing else "ready_for_review"
    elif has_execution or has_ai_review:
        state = "ready_for_review"
    else:
        state = "maturing"

    return {
        "watch_state": state,
        "age_days": age_days,
        "min_watch_days": horizon["min_days"],
        "max_watch_days": horizon["max_days"],
        "missing_requirements": missing,
        "horizon": horizon,
    }


def summarize_watch_blockers(candidate: dict, strategy_id: str = None) -> list:
    """Return list of blockers preventing proposal readiness."""
    result = classify_candidate_watch_state(candidate, strategy_id)
    blockers = []
    state = result["watch_state"]
    if state == "new_candidate":
        blockers.append(f"Too new — needs {result.get('min_watch_days', '?')} min observation days")
    elif state == "observing":
        blockers.append(f"Observing — {result['age_days']}d / {result.get('min_watch_days', '?')}d minimum")
    elif state == "expired":
        blockers.append(result.get("reason", "Expired"))
    elif state == "disqualified":
        blockers.append(result.get("reason", "Disqualified"))
    elif state == "insufficient_data":
        for m in result.get("missing_requirements", []):
            blockers.append(f"Missing required: {m}")
    elif state == "maturing":
        blockers.append("Needs execution check and AI review")
    return blockers


def recommend_watch_action(candidate: dict, strategy_id: str = None) -> dict:
    """Recommend next action for this candidate. Human-review-only."""
    result = classify_candidate_watch_state(candidate, strategy_id)
    state = result["watch_state"]
    actions = {
        "new_candidate": "Continue observing — too early to act",
        "observing": "Continue observing — below minimum watch window",
        "maturing": "Run execution check and AI review",
        "insufficient_data": f"Fill missing data: {', '.join(result.get('missing_requirements', []))}",
        "ready_for_review": "Review data completeness before promotion",
        "ready_for_proposal": "Promote to proposal when operator ready",
        "expired": "Archive or rebuild — exceeded max watch window",
        "disqualified": "Remove from watchlist",
    }
    return {
        "watch_state": state,
        "action": actions.get(state, "Review manually"),
        "human_review_only": True,
    }
