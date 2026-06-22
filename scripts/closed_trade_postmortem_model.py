#!/usr/bin/env python3
"""closed_trade_postmortem_model.py — Convert closed trades into dashboard-ready postmortems.

Pure functions. No DB writes. No trades. No strategy changes.
"""
import re
from pathlib import Path

_MAX_HOLD_CACHE = {}


def _strategy_max_hold(strategy):
    """Return the strategy's configured max_hold_days (or None) — so a stale-close lesson doesn't
    recommend adding a rule that already exists. Read-only config lookup, cached."""
    if not strategy:
        return None
    if strategy in _MAX_HOLD_CACHE:
        return _MAX_HOLD_CACHE[strategy]
    val = None
    try:
        p = Path(__file__).resolve().parent.parent / "config" / "strategies" / f"{strategy}.yaml"
        if p.exists():
            m = re.search(r"max_hold_days:\s*(\d+)", p.read_text())
            val = int(m.group(1)) if m else None
    except Exception:
        val = None
    _MAX_HOLD_CACHE[strategy] = val
    return val


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
    "broker_submit_blocked_never_filled": "broker_submit_blocked",
    "revalidation_blocked_never_submitted": "broker_submit_blocked",
    "auto_cancel_never_submitted": "broker_submit_blocked",
    "order_never_filled_on_alpaca": "broker_position_closed",
    "closed_on_different_trade_id": "duplicate_trade_record",
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
    # closed under a different trade record for the same symbol — a bookkeeping artifact, not a trade outcome
    if "position_closed" in exit_reason or "different_trade" in exit_reason:
        return "NEEDS_REVIEW"
    return "NEEDS_REVIEW"


def classify_entry_quality(trade: dict) -> str:
    """Classify whether the entry was good based on outcome."""
    r = float(trade.get("r_multiple") or 0)
    if r >= 1.0: return "GOOD_ENTRY"
    if r >= 0: return "ACCEPTABLE_ENTRY"
    if r >= -0.5: return "WEAK_ENTRY"
    return "CHASED_ENTRY"


def classify_dashboard_verdict(trade: dict) -> str:
    """Clear operator-facing verdict for dashboard display."""
    exit_reason = (trade.get("exit_reason") or "").lower()
    r = float(trade.get("r_multiple") or 0)
    pnl = float(trade.get("pnl") or 0)

    if "target_hit" in exit_reason and r >= 1.0:
        return "CLEAN_WIN"
    if "target_hit" in exit_reason:
        return "GOOD_EXIT"
    if "stop_hit_instant" in exit_reason:
        return "BAD_ENTRY"
    if "stop_hit" in exit_reason:
        return "RULE_BASED_LOSS" if abs(r) <= 1.0 else "BAD_EXIT"
    if "time_stop" in exit_reason:
        return "EARLY_EXIT" if pnl < 0 else "ACCEPTABLE_LOSS" if pnl == 0 else "GOOD_EXIT"
    if "manual" in exit_reason or "stale" in exit_reason:
        return "LATE_EXIT"
    if ("phantom" in exit_reason or "never_filled" in exit_reason or "position_closed" in exit_reason
            or "different_trade" in exit_reason):
        return "DATA_OR_BROKER_REVIEW"
    return "NEEDS_REVIEW"


def classify_mistake_type(trade: dict) -> str:
    """What went wrong, if anything."""
    exit_reason = (trade.get("exit_reason") or "").lower()
    r = float(trade.get("r_multiple") or 0)

    if "target_hit" in exit_reason and r >= 1.0:
        return "none"
    if "stop_hit_instant" in exit_reason:
        return "spread_slippage"
    if "stop_hit" in exit_reason:
        if r < -1.0: return "stop_too_wide"
        if abs(r) < 0.1: return "stop_too_tight"
        return "none"
    if "time_stop" in exit_reason:
        return "time_stop_drag" if r < 0 else "none"
    if "manual" in exit_reason or "stale" in exit_reason:
        return "stale_manual_exit"
    if "phantom" in exit_reason or "never_filled" in exit_reason:
        return "broker_sync_issue"
    if "position_closed" in exit_reason or "different_trade" in exit_reason:
        return "broker_sync_issue"
    if r < -0.5:
        return "chased_entry"
    return "none"


def generate_improved_lesson(trade: dict) -> dict:
    """Generate a specific, actionable lesson — never generic."""
    exit_reason = (trade.get("exit_reason") or "").lower()
    r = float(trade.get("r_multiple") or 0)
    pnl = float(trade.get("pnl") or 0)
    symbol = trade.get("symbol", "?")
    strategy = trade.get("strategy_id", "?")

    if "target_hit" in exit_reason:
        return {
            "category": "exit_discipline",
            "lesson": f"{symbol} ({strategy}): Target hit at {r:.1f}R — exit discipline followed, strategy plan executed as designed",
            "rule_feedback": f"Target rule worked correctly for {strategy}; no rule change needed",
            "action": "no_action",
            "action_priority": "none",
            "action_owner": "operator",
            "next_operator_action": "No action needed — review P&L and confirm strategy confidence",
            "better_exit_possible": "no",
            "post_exit_review_needed": False,
        }
    if "stop_hit_instant" in exit_reason:
        return {
            "category": "entry_timing",
            "lesson": f"{symbol} ({strategy}): Stopped out instantly at {r:.2f}R — entry price was likely too aggressive, spread was too wide, or stop was placed inside the bid-ask range",
            "rule_feedback": f"Review {strategy} entry criteria: require tighter spread limits or wider initial stop to survive first candle",
            "action": "investigate_data_gap",
            "action_priority": "high",
            "action_owner": "strategy_review",
            "next_operator_action": f"Check {symbol} spread at entry time, verify stop was outside bid-ask, review {strategy} entry filter",
            "better_exit_possible": "unknown",
            "post_exit_review_needed": True,
        }
    if "stop_hit" in exit_reason:
        severity = "within acceptable R risk" if abs(r) <= 1.0 else "exceeded target R risk"
        return {
            "category": "stop_quality",
            "lesson": f"{symbol} ({strategy}): Stop hit at {r:.1f}R — {severity}. Entry quality was {'adequate' if abs(r) <= 0.5 else 'weak'}, stop placement {'held correctly' if abs(r) <= 1.0 else 'was too wide'}",
            "rule_feedback": f"Stop distance {'acceptable' if abs(r) <= 1.0 else 'needs tightening'} for {strategy}; {'no change needed' if abs(r) <= 1.0 else 'consider tighter stop or smaller position size'}",
            "action": "review_strategy" if abs(r) > 0.5 else "no_action",
            "action_priority": "medium" if abs(r) > 0.5 else "none",
            "action_owner": "strategy_review" if abs(r) > 0.5 else "operator",
            "next_operator_action": f"{'Review ' + strategy + ' stop distance and position sizing' if abs(r) > 0.5 else 'No action — loss within acceptable risk parameters'}",
            "better_exit_possible": "no",
            "post_exit_review_needed": abs(r) > 0.5,
        }
    if "time_stop" in exit_reason:
        protected = pnl >= 0
        return {
            "category": "holding_period",
            "lesson": f"{symbol} ({strategy}): Time stop triggered — setup did not move within the allowed window. {'Capital protected, exited flat/green' if protected else 'Small loss incurred, time stop prevented further drawdown'}",
            "rule_feedback": f"Time stop {'protected capital as designed' if protected else 'cut a losing position early — review whether the setup needed a longer window or the entry was weak'}",
            "action": "no_action" if protected else "tighten_exit_rule",
            "action_priority": "none" if protected else "low",
            "action_owner": "operator",
            "next_operator_action": f"{'No action — time stop worked as intended' if protected else 'Review whether ' + strategy + ' holding window is too short for this setup type'}",
            "better_exit_possible": "no" if protected else "unknown",
            "post_exit_review_needed": not protected,
        }
    if "manual" in exit_reason or "stale" in exit_reason:
        mh = _strategy_max_hold(strategy)
        held = trade.get("_held_days")
        if mh:
            # strategy ALREADY has a max-hold auto-exit — don't recommend adding one that exists.
            return {
                "category": "exit_enforcement",
                "lesson": f"{symbol} ({strategy}): Closed manual/stale though {strategy} already defines max_hold_days={mh} with auto-exit"
                          + (f" (held only ~{held}d)" if held is not None else "") + " — the stale close fired before/instead of the configured time-exit. The gap is ENFORCEMENT/timing, not a missing rule",
                "rule_feedback": f"{strategy} HAS a {mh}-day max-hold auto-exit; verify the time-exit executor actually fires and that stale-detection is not closing positions prematurely (well inside the {mh}-day window)",
                "action": "verify_exit_enforcement",
                "action_priority": "medium",
                "action_owner": "strategy_review",
                "next_operator_action": f"Confirm {strategy}'s max_hold_days={mh} auto-exit drives exits; investigate why {symbol} was flagged stale early instead",
                "better_exit_possible": "yes",
                "post_exit_review_needed": True,
            }
        return {
            "category": "manual_intervention",
            "lesson": f"{symbol} ({strategy}): Closed manually/stale — no explicit exit rule fired, position was closed by operator discretion. This indicates the strategy lacks a clear exit condition for this scenario",
            "rule_feedback": f"{strategy} needs an explicit exit rule for positions that go stale — add a time-based or condition-based auto-exit to prevent ad-hoc closures",
            "action": "improve_rr_filter",
            "action_priority": "medium",
            "action_owner": "strategy_review",
            "next_operator_action": f"Add explicit stale-exit rule to {strategy} — define max holding period or condition-based exit trigger",
            "better_exit_possible": "yes",
            "post_exit_review_needed": True,
        }
    if "broker_submit_blocked" in exit_reason or "revalidation_blocked" in exit_reason:
        return {
            "category": "execution_gate",
            "lesson": f"{symbol} ({strategy}): Broker submission was blocked before any fill — trade record was cancelled, no position was opened. Review risk gate / concentration / revalidation reason",
            "rule_feedback": "Blocked submits must cancel the pending DB row immediately; digest excludes these bookkeeping closes",
            "action": "review_risk_gate",
            "action_priority": "medium",
            "action_owner": "strategy_review",
            "next_operator_action": f"Review why {symbol} was blocked at submit (proposal event log / ATM failure reason)",
            "better_exit_possible": "n/a",
            "post_exit_review_needed": False,
        }
    if "phantom" in exit_reason or "never_filled" in exit_reason:
        return {
            "category": "data_quality",
            "lesson": f"{symbol} ({strategy}): Order was never filled on broker or position was phantom — execution pipeline created a trade record but no actual position existed. Check order submission and fill confirmation flow",
            "rule_feedback": "Execution pipeline needs validation: verify fill confirmation before recording trade entry",
            "action": "investigate_data_gap",
            "action_priority": "high",
            "action_owner": "data_pipeline",
            "next_operator_action": f"Check Alpaca order history for {symbol} — verify whether order was submitted, rejected, or never sent",
            "better_exit_possible": "unknown",
            "post_exit_review_needed": True,
        }
    if "position_closed" in exit_reason:
        return {
            "category": "broker_sync",
            "lesson": f"{symbol} ({strategy}): Position was closed externally on Alpaca — either a manual close on the broker side, a margin call, or a corporate action. System did not initiate this exit",
            "rule_feedback": "Broker reconciliation should detect and alert on external closes immediately — verify reconciler coverage",
            "action": "review_manual_close",
            "action_priority": "high",
            "action_owner": "broker_sync",
            "next_operator_action": f"Check Alpaca activity log for {symbol} — determine if this was a manual close, margin event, or sync error",
            "better_exit_possible": "unknown",
            "post_exit_review_needed": True,
        }
    if "different_trade" in exit_reason:
        return {
            "category": "data_quality",
            "lesson": f"{symbol} ({strategy}): Position closed under a DIFFERENT trade record for the same symbol — two overlapping records existed for one Alpaca position and the other record's close cascaded here. A bookkeeping artifact, not a trading outcome",
            "rule_feedback": "Dedupe overlapping open trades per symbol: block/merge a second open record for an already-open symbol so one record maps to one live position",
            "action": "investigate_data_gap",
            "action_priority": "medium",
            "action_owner": "data_pipeline",
            "next_operator_action": f"Check for duplicate open trades on {symbol}; enforce one trade record per live Alpaca position (entry-dedup guard)",
            "better_exit_possible": "n/a",
            "post_exit_review_needed": True,
        }
    return {
        "category": "unknown",
        "lesson": f"{symbol} ({strategy}): Exit reason '{exit_reason}' is not classified — add this exit type to the postmortem model",
        "rule_feedback": "Add classification for this exit reason to closed_trade_postmortem_model.py",
        "action": "add_to_lessons",
        "action_priority": "low",
        "action_owner": "system",
        "next_operator_action": f"Classify exit reason '{exit_reason}' and add to postmortem model",
        "better_exit_possible": "unknown",
        "post_exit_review_needed": True,
    }


def build_postmortem(trade: dict) -> dict:
    """Build a complete postmortem for one closed trade."""
    exit_reason = trade.get("exit_reason") or "unknown"
    exit_type = EXIT_TYPE_MAP.get(exit_reason.lower(), "unknown")
    exit_quality = classify_exit_quality(trade)
    entry_quality = classify_entry_quality(trade)
    dashboard_verdict = classify_dashboard_verdict(trade)
    mistake_type = classify_mistake_type(trade)
    lesson = generate_improved_lesson(trade)

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
        "dashboard_verdict": dashboard_verdict,
        "mistake_type": mistake_type,
        "why_closed": exit_reason.replace("_", " ").title(),
        "one_line_lesson": lesson["lesson"],
        "improved_lesson": lesson["lesson"],
        "lesson_category": lesson["category"],
        "rule_feedback": lesson["rule_feedback"],
        "operator_action": lesson["action"],
        "action_priority": lesson["action_priority"],
        "action_owner": lesson["action_owner"],
        "next_operator_action": lesson["next_operator_action"],
        "better_exit_possible": lesson["better_exit_possible"],
        "post_exit_review_needed": lesson["post_exit_review_needed"],
        "confidence_delta": "positive" if r >= 1.0 else "neutral" if r >= 0 else "negative" if r < -0.5 else "neutral",
        "strategy_confidence_impact": "positive" if r >= 1.0 else "neutral" if r >= 0 else "negative" if r < -0.5 else "neutral",
        "followup_required": lesson["action"] not in ("no_action",),
        "human_review_only": True,
    }


def build_daily_summary(postmortems: list) -> dict:
    """Build a daily summary from a list of postmortems."""
    if not postmortems:
        return {
            "closed_today_count": 0, "total_realized_pnl": 0, "daily_avg_r": 0,
            "wins": 0, "losses": 0, "flats": 0,
            "best_trade": None, "worst_trade": None,
            "top_lesson": "No closed trades", "top_action_item": "No action needed",
            "trades_needing_review": [], "strategy_confidence_changes": {},
            "repeated_failure_patterns": [],
        }

    wins = [pm for pm in postmortems if pm["verdict"] == "WIN"]
    losses = [pm for pm in postmortems if pm["verdict"] == "LOSS"]
    flats = [pm for pm in postmortems if pm["verdict"] == "FLAT"]
    total_pnl = sum(pm["pnl"] for pm in postmortems)
    avg_r = sum(pm["r_multiple"] for pm in postmortems) / len(postmortems)

    best = max(postmortems, key=lambda x: x["pnl"])
    worst = min(postmortems, key=lambda x: x["pnl"])

    # Find highest priority action item
    priority_order = {"urgent": 0, "high": 1, "medium": 2, "low": 3, "none": 4}
    action_items = [pm for pm in postmortems if pm["action_priority"] != "none"]
    action_items.sort(key=lambda x: priority_order.get(x["action_priority"], 5))
    top_action = action_items[0] if action_items else None

    # Find the most impactful lesson (highest priority non-generic)
    review_items = [pm for pm in postmortems if pm["followup_required"]]
    top_lesson_pm = review_items[0] if review_items else best

    # Strategy confidence
    confidence = {}
    for pm in postmortems:
        s = pm["strategy"]
        if s not in confidence:
            confidence[s] = []
        confidence[s].append(pm["confidence_delta"])

    # Repeated patterns
    mistake_counts = {}
    for pm in postmortems:
        mt = pm["mistake_type"]
        if mt != "none":
            mistake_counts[mt] = mistake_counts.get(mt, 0) + 1
    repeated = [{"pattern": k, "count": v} for k, v in mistake_counts.items() if v >= 2]

    return {
        "closed_today_count": len(postmortems),
        "total_realized_pnl": round(total_pnl, 2),
        "daily_avg_r": round(avg_r, 2),
        "wins": len(wins),
        "losses": len(losses),
        "flats": len(flats),
        "win_loss_summary": f"{len(wins)}W / {len(losses)}L / {len(flats)}F",
        "best_trade": {"symbol": best["symbol"], "pnl": best["pnl"], "reason": best["dashboard_verdict"]},
        "worst_trade": {"symbol": worst["symbol"], "pnl": worst["pnl"], "reason": worst["dashboard_verdict"]},
        "top_lesson": top_lesson_pm["improved_lesson"],
        "top_action_item": top_action["next_operator_action"] if top_action else "No action needed",
        "trades_needing_review": [
            {"symbol": pm["symbol"], "strategy": pm["strategy"], "issue": pm["dashboard_verdict"],
             "priority": pm["action_priority"], "action": pm["next_operator_action"]}
            for pm in review_items
        ],
        "strategy_confidence_changes": confidence,
        "repeated_failure_patterns": repeated,
        "human_review_only": True,
    }
