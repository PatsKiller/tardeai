#!/usr/bin/env python3
"""missed_opportunity_policy.py — Classify proposal timing decay and missed opportunities.

Pure functions. No DB writes. No broker calls. No approvals.
"""

MIN_RR = 2.0
MAX_PRICE_DRIFT = 8.0
MAX_SPREAD = 5.0
ALERT_SLA_SECONDS = 60  # Alert should fire within 60s of proposal creation


def classify_opportunity_timing(proposal: dict, alert: dict = None) -> dict:
    """Classify whether the opportunity was acted on in time."""
    created = proposal.get("created_at")
    checked = proposal.get("check_execution_at") or proposal.get("execution_check_at")
    alert_at = (alert or {}).get("ts") or (alert or {}).get("sent_at")

    latency_s = None
    if created and checked:
        try:
            from datetime import datetime, timezone
            c = created if not isinstance(created, str) else datetime.fromisoformat(str(created).replace("Z", "+00:00"))
            e = checked if not isinstance(checked, str) else datetime.fromisoformat(str(checked).replace("Z", "+00:00"))
            if c.tzinfo is None: c = c.replace(tzinfo=timezone.utc)
            if e.tzinfo is None: e = e.replace(tzinfo=timezone.utc)
            latency_s = (e - c).total_seconds()
        except Exception:
            pass

    if latency_s is not None:
        if latency_s <= 300:
            timing = "on_time"
        elif latency_s <= 1800:
            timing = "delayed"
        elif latency_s <= 7200:
            timing = "late"
        else:
            timing = "missed"
    else:
        timing = "insufficient_data"

    return {"timing": timing, "created_to_check_seconds": latency_s}


def calculate_alert_latency(proposal: dict, alert: dict = None) -> dict:
    """Measure how quickly an alert was sent after proposal creation."""
    if not alert or not alert.get("ts"):
        return {"alert_sent": False, "latency_seconds": None, "sla_met": False, "sla_target": ALERT_SLA_SECONDS}

    try:
        from datetime import datetime, timezone
        created = proposal.get("created_at")
        c = created if not isinstance(created, str) else datetime.fromisoformat(str(created).replace("Z", "+00:00"))
        a = alert["ts"] if not isinstance(alert["ts"], str) else datetime.fromisoformat(str(alert["ts"]).replace("Z", "+00:00"))
        if c.tzinfo is None: c = c.replace(tzinfo=timezone.utc)
        if a.tzinfo is None: a = a.replace(tzinfo=timezone.utc)
        latency = (a - c).total_seconds()
        return {"alert_sent": True, "latency_seconds": round(latency), "sla_met": latency <= ALERT_SLA_SECONDS, "sla_target": ALERT_SLA_SECONDS}
    except Exception:
        return {"alert_sent": True, "latency_seconds": None, "sla_met": False, "sla_target": ALERT_SLA_SECONDS}


def calculate_proposal_decay(proposal: dict, latest_quote: dict = None) -> dict:
    """Measure how much a proposal has decayed from creation values."""
    entry = float(proposal.get("proposed_entry") or 0)
    stop = float(proposal.get("proposed_stop") or 0)
    target = float(proposal.get("proposed_target1") or 0)
    orig_rr = float(proposal.get("proposed_rr") or 0)

    quote_price = float((latest_quote or {}).get("quote_price") or (latest_quote or {}).get("last_price") or 0)
    spread = (latest_quote or {}).get("spread_pct")
    volume = (latest_quote or {}).get("volume") or (latest_quote or {}).get("day_volume")

    price_move = abs(quote_price - entry) / entry * 100 if entry > 0 and quote_price > 0 else 0
    new_rr = (target - quote_price) / (quote_price - stop) if quote_price > stop and target > quote_price else 0
    rr_decay = orig_rr - new_rr if orig_rr > 0 and new_rr > 0 else None

    return {
        "entry": entry, "quote_price": quote_price,
        "price_move_pct": round(price_move, 2),
        "original_rr": round(orig_rr, 2), "current_rr": round(new_rr, 2),
        "rr_decay": round(rr_decay, 2) if rr_decay is not None else None,
        "spread_pct": float(spread) if spread is not None else None,
        "volume": int(volume) if volume is not None else None,
        "actionable": new_rr >= MIN_RR and price_move <= MAX_PRICE_DRIFT,
    }


def classify_missed_opportunity(proposal: dict, latest_quote: dict = None) -> dict:
    """Overall missed opportunity classification."""
    decay = calculate_proposal_decay(proposal, latest_quote)
    timing = classify_opportunity_timing(proposal)

    if decay["actionable"]:
        status = "still_actionable"
    elif decay["price_move_pct"] > MAX_PRICE_DRIFT:
        status = "missed_price_moved"
    elif decay["current_rr"] < MIN_RR and decay["current_rr"] > 0:
        status = "rebuild_required"
    elif decay.get("spread_pct") and decay["spread_pct"] > MAX_SPREAD:
        status = "blocked_spread"
    elif decay.get("volume") and decay["volume"] < 5000:
        status = "blocked_volume"
    else:
        status = "insufficient_data"

    return {
        "status": status,
        "timing": timing["timing"],
        "decay": decay,
        "human_review_only": True,
    }


def recommended_operator_action(decay: dict) -> dict:
    """Recommend action based on decay analysis."""
    if decay.get("actionable"):
        return {"action": "approve_paper_if_ready", "reason": "Still within parameters"}
    if decay.get("current_rr", 0) < MIN_RR and decay.get("current_rr", 0) > 0:
        return {"action": "rebuild", "reason": f"R:R decayed to {decay['current_rr']:.2f}"}
    if decay.get("price_move_pct", 0) > MAX_PRICE_DRIFT:
        return {"action": "expire", "reason": f"Price moved {decay['price_move_pct']:.1f}%"}
    return {"action": "watch", "reason": "Insufficient data for action"}
