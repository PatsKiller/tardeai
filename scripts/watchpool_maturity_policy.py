#!/usr/bin/env python3
"""watchpool_maturity_policy.py — Classify watchpool/incubator candidate maturity.

Pure functions. No DB writes. No broker calls. No promotions. No approvals.
"""
import hashlib

from strategy_watch_horizon_policy import get_default_watch_horizon

MIN_RR = 2.0


def classify_watchpool_maturity(candidate: dict) -> dict:
    """Classify a watchpool/incubator candidate's alertable maturity state."""
    sid = candidate.get("strategy_id", "")
    horizon = get_default_watch_horizon(sid)
    age = int(candidate.get("days_active") or candidate.get("age_days") or 0)
    ttl_remaining = int(candidate.get("ttl_remaining") or (horizon["max_days"] - age))
    score = int(candidate.get("latest_score") or candidate.get("score") or 0)
    status = candidate.get("current_status") or candidate.get("status") or ""

    # Data checks
    has_quote = bool(candidate.get("quote_provider") or candidate.get("last_price_source"))
    has_catalyst = bool(candidate.get("catalyst") or candidate.get("catalyst_verified"))
    has_technical = bool(candidate.get("technical_snapshot") or candidate.get("rsi"))
    has_route = bool(candidate.get("route_audit") or candidate.get("setup_stack"))
    rvol = float(candidate.get("rvol") or candidate.get("rvol_latest") or 0)
    spread = candidate.get("spread_pct")

    if status in ("EXPIRED", "expired", "KILLED"):
        state = "STALE_OR_EXPIRED"
    elif ttl_remaining <= 0:
        state = "STALE_OR_EXPIRED"
    elif score >= 45 and has_quote and has_catalyst:
        state = "WATCHPOOL_READY"
    elif score >= 38 and has_catalyst and ttl_remaining <= 3:
        state = "NEAR_TRIGGER"
    elif score >= 38 and not has_quote:
        state = "NEEDS_QUOTE_REFRESH"
    elif score >= 38 and not has_technical:
        state = "NEEDS_TECHNICAL_SNAPSHOT"
    elif score >= 30 and not has_catalyst and horizon.get("catalyst_required"):
        state = "NEEDS_CATALYST_CONFIRMATION"
    elif spread is not None and float(spread) > 5.0:
        state = "BLOCKED_SPREAD"
    elif rvol < 1.0 and sid in ("momentum_scalp", "gap_and_go"):
        state = "BLOCKED_VOLUME"
    elif score >= 30:
        state = "MATURING"
    else:
        state = "NO_ACTION"

    return {
        "maturity_state": state,
        "score": score, "age_days": age, "ttl_remaining": ttl_remaining,
        "has_quote": has_quote, "has_catalyst": has_catalyst,
        "has_technical": has_technical, "has_route": has_route,
        "horizon": horizon, "human_review_only": True,
    }


def determine_watchpool_alert_type(candidate: dict) -> str:
    """Map maturity state to alert type."""
    m = classify_watchpool_maturity(candidate)
    state = m["maturity_state"]
    return {
        "WATCHPOOL_READY": "WATCHPOOL_READY",
        "NEAR_TRIGGER": "WATCHPOOL_NEAR_TRIGGER",
        "MATURING": "WATCHPOOL_MATURING",
        "NEEDS_QUOTE_REFRESH": "WATCHPOOL_BLOCKED_FIXABLE",
        "NEEDS_TECHNICAL_SNAPSHOT": "WATCHPOOL_BLOCKED_FIXABLE",
        "NEEDS_CATALYST_CONFIRMATION": "WATCHPOOL_BLOCKED_FIXABLE",
        "NEEDS_ROUTE_AUDIT": "WATCHPOOL_BLOCKED_FIXABLE",
        "BLOCKED_RR": "WATCHPOOL_BLOCKED_FIXABLE",
        "BLOCKED_SPREAD": "WATCHPOOL_BLOCKED_FIXABLE",
        "BLOCKED_VOLUME": "WATCHPOOL_BLOCKED_FIXABLE",
        "STALE_OR_EXPIRED": "WATCHPOOL_EXPIRING",
        "NO_ACTION": "NO_ACTION",
    }.get(state, "NO_ACTION")


def build_watchpool_alert_packet(candidate: dict) -> dict:
    """Build alert packet for Telegram."""
    m = classify_watchpool_maturity(candidate)
    alert_type = determine_watchpool_alert_type(candidate)
    return {
        "alert_type": alert_type,
        "symbol": candidate.get("symbol"),
        "strategy_id": candidate.get("strategy_id"),
        "maturity_state": m["maturity_state"],
        "score": m["score"],
        "age_days": m["age_days"],
        "ttl_remaining": m["ttl_remaining"],
        "rvol": candidate.get("rvol") or candidate.get("rvol_latest"),
        "catalyst": candidate.get("catalyst"),
        "catalyst_verified": candidate.get("catalyst_verified"),
        "recommended_action": {
            "WATCHPOOL_READY": "Review for promotion",
            "WATCHPOOL_NEAR_TRIGGER": "Monitor closely — approaching trigger",
            "WATCHPOOL_MATURING": "Continue watching",
            "WATCHPOOL_BLOCKED_FIXABLE": f"Fix: {m['maturity_state'].replace('NEEDS_', '').replace('BLOCKED_', '').lower()}",
            "WATCHPOOL_EXPIRING": "Expire or rebuild",
            "NO_ACTION": "No action needed",
        }.get(alert_type, "Review"),
        "human_review_only": True,
    }


def should_suppress_watchpool_alert(candidate: dict, recent_keys: set = None) -> dict:
    """Check for duplicate suppression."""
    key = hashlib.md5(f"{candidate.get('symbol','')}-{candidate.get('strategy_id','')}-{determine_watchpool_alert_type(candidate)}".encode()).hexdigest()[:12]
    if recent_keys and key in recent_keys:
        return {"send": False, "reason": "duplicate_suppressed", "key": key}
    alert_type = determine_watchpool_alert_type(candidate)
    if alert_type == "NO_ACTION":
        return {"send": False, "reason": "no_action", "key": key}
    return {"send": True, "reason": alert_type, "key": key}


def format_watchpool_telegram_message(packet: dict) -> str:
    """Format watchpool alert for Telegram."""
    emoji = {"WATCHPOOL_READY": "\u2705", "WATCHPOOL_NEAR_TRIGGER": "\u26a1",
             "WATCHPOOL_MATURING": "\u23f3", "WATCHPOOL_BLOCKED_FIXABLE": "\u26a0\ufe0f",
             "WATCHPOOL_EXPIRING": "\u23f0"}.get(packet["alert_type"], "\u2753")

    lines = [
        f"{emoji} *Watchpool: {packet['symbol']}*",
        f"Strategy: {packet['strategy_id']} | {packet['maturity_state'].replace('_', ' ')}",
        f"Score: {packet['score']} | Age: {packet['age_days']}d | TTL: {packet['ttl_remaining']}d",
    ]
    if packet.get("rvol"):
        lines.append(f"RVOL: {float(packet['rvol']):.1f}x")
    if packet.get("catalyst"):
        cv = "\u2705" if packet.get("catalyst_verified") else "\u26a0\ufe0f"
        lines.append(f"Catalyst: {cv}")
    lines.append(f"\n*Action:* {packet['recommended_action']}")
    lines.append("_Watchpool alert — no trade, no order_")
    return "\n".join(lines)
