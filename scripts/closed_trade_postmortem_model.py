#!/usr/bin/env python3
"""closed_trade_postmortem_model.py — Convert closed trades into dashboard-ready postmortems.

Pure functions. No DB writes. No trades. No strategy changes.
"""

EXIT_TYPE_MAP = {
    "target_hit": "target_hit",
    "stop_hit": "stop_hit",
    "stop_hit_instant": "instant_stop",
    "time_stop_intraday_1545": "time_stop",
    "time_stop_max_0d": "time_stop",
    "manual_stale_close": "stale_close",
    "manual_close": "manual_close",
    "position_closed_in_alpaca": "broker_position_closed",
    "phantom_no_alpaca_position": "broker_position_closed",
    "order_never_filled_on_alpaca": "broker_position_closed",
}


def classify_exit_quality(trade: dict) -> str:
    """Classify whether the exit was good, acceptable, or bad."""
    exit_reason = (trade.get("exit_reason") or "").lower()
    r = float(trade.get("r_multiple") or 0)
    pnl = float(trade.get("pnl") or 0)

    if "target_hit" in exit_reason:
        return "GOOD_EXIT" if r >= 1.0 else "ACCEPTABLE_EXIT"
    if "stop_hit_instant" in exit_reason:
        return "NEEDS_REVIEW"  # Instant stop suggests entry/spread issue
    if "stop_hit" in exit_reason:
        return "ACCEPTABLE_EXIT" if abs(r) <= 1.0 else "BAD_EXIT"
    if "time_stop" in exit_reason:
        return "ACCEPTABLE_EXIT" if pnl >= 0 else "EARLY_EXIT"
    if "manual" in exit_reason or "stale" in exit_reason:
        return "NEEDS_REVIEW"
    if "phantom" in exit_reason or "never_filled" in exit_reason:
        return "NEEDS_REVIEW"
    if "position_closed" in exit_reason:
        return "NEEDS_REVIEW"
    return "NEEDS_REVIEW"


def classify_entry_quality(trade: dict) -> str:
    """Classify whether the entry was good based on outcome."""
    r = float(trade.get("r_multiple") or 0)
    if r >= 1.0: return "GOOD_ENTRY"
    if r >= 0: return "ACCEPTABLE_ENTRY"
    if r >= -0.5: return "WEAK_ENTRY"
    return "CHASED_ENTRY"


def generate_lesson(trade: dict) -> dict:
    """Generate a one-line lesson and category from exit analysis."""
    exit_reason = (trade.get("exit_reason") or "").lower()
    r = float(trade.get("r_multiple") or 0)
    symbol = trade.get("symbol", "?")
    strategy = trade.get("strategy_id", "?")

    if "target_hit" in exit_reason:
        return {"category": "exit_discipline", "lesson": f"{symbol}: Target hit at {r:.1f}R — strategy followed correctly",
                "action": "no_action"}
    if "stop_hit_instant" in exit_reason:
        return {"category": "entry_timing", "lesson": f"{symbol}: Instant stop — entry price may have been too aggressive or spread too wide",
                "action": "investigate_data_gap"}
    if "stop_hit" in exit_reason:
        return {"category": "stop_quality", "lesson": f"{symbol}: Stop hit at {r:.1f}R — check stop distance and entry quality",
                "action": "review_strategy" if abs(r) > 0.5 else "no_action"}
    if "time_stop" in exit_reason:
        return {"category": "holding_period", "lesson": f"{symbol}: Time stop triggered — setup did not move within window",
                "action": "tighten_exit_rule" if r < 0 else "no_action"}
    if "manual" in exit_reason or "stale" in exit_reason:
        return {"category": "manual_intervention", "lesson": f"{symbol}: Manual/stale close — define explicit exit rule to avoid ad-hoc decisions",
                "action": "improve_rr_filter"}
    if "phantom" in exit_reason or "never_filled" in exit_reason:
        return {"category": "data_quality", "lesson": f"{symbol}: Order never filled or phantom position — check execution pipeline",
                "action": "investigate_data_gap"}
    if "position_closed" in exit_reason:
        return {"category": "manual_intervention", "lesson": f"{symbol}: Position closed externally — investigate whether intentional",
                "action": "review_manual_close"}
    return {"category": "unknown", "lesson": f"{symbol}: Exit reason '{exit_reason}' needs classification",
            "action": "add_to_lessons"}


def build_postmortem(trade: dict) -> dict:
    """Build a complete postmortem for one closed trade."""
    exit_reason = trade.get("exit_reason") or "unknown"
    exit_type = EXIT_TYPE_MAP.get(exit_reason.lower(), "unknown")
    exit_quality = classify_exit_quality(trade)
    entry_quality = classify_entry_quality(trade)
    lesson = generate_lesson(trade)

    pnl = float(trade.get("pnl") or 0)
    r = float(trade.get("r_multiple") or 0)

    return {
        "trade_id": trade.get("id"),
        "symbol": trade.get("symbol"),
        "strategy": trade.get("strategy_id"),
        "entry_price": trade.get("entry_price"),
        "exit_price": trade.get("exit_price"),
        "shares": trade.get("shares"),
        "pnl": round(pnl, 2),
        "r_multiple": round(r, 2),
        "verdict": "WIN" if pnl > 0 else "LOSS" if pnl < 0 else "FLAT",
        "exit_reason": exit_reason,
        "exit_type": exit_type,
        "exit_quality": exit_quality,
        "entry_quality": entry_quality,
        "why_closed": exit_reason.replace("_", " ").title(),
        "one_line_lesson": lesson["lesson"],
        "lesson_category": lesson["category"],
        "operator_action": lesson["action"],
        "strategy_confidence_impact": "positive" if r >= 1.0 else "neutral" if r >= 0 else "negative" if r < -0.5 else "neutral",
        "followup_required": lesson["action"] not in ("no_action",),
        "human_review_only": True,
    }
