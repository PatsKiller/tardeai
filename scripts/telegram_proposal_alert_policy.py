#!/usr/bin/env python3
"""telegram_proposal_alert_policy.py — Decide when and what to alert for proposals.

Pure functions. No Telegram sends. No DB writes. No broker calls.
"""
import hashlib
from datetime import datetime, timezone


def classify_proposal_alert_state(proposal: dict) -> str:
    """Classify what alert type a proposal deserves."""
    status = proposal.get("status", "")
    verdict = proposal.get("operator_verdict", "")
    blockers = proposal.get("approval_blockers") or []
    rr = float(proposal.get("proposed_rr") or proposal.get("rr") or 0)
    er = proposal.get("execution_readiness") or {}
    readiness = er.get("readiness_state", "")
    approval_allowed = bool(proposal.get("approval_allowed"))

    # ACTIONABLE_READY only when approval is actually allowed (not just empty blockers at promote time)
    if approval_allowed and (verdict == "READY" or (status == "PENDING" and not blockers and rr >= 2.0)):
        return "ACTIONABLE_READY"
    if "BLOCKED" in (readiness or "").upper() or "BLOCKED" in (verdict or "").upper():
        if any("price_moved" in str(b) or "rr_below" in str(b) for b in blockers):
            return "BLOCKED_NEEDS_REBUILD"
        return "BLOCKED_EXECUTION_FAILED"
    if status == "PENDING" and blockers:
        return "NEEDS_OPERATOR_DECISION"
    if status in ("EXPIRED", "expired"):
        return "EXPIRED_OR_STALE"
    return "NEEDS_OPERATOR_DECISION"


def _strategy_meta(proposal: dict) -> dict:
    sid = proposal.get("strategy_id") or ""
    try:
        from proposal_lifecycle import get_strategy_metadata
        meta = get_strategy_metadata(sid)
        return {
            "display_name": proposal.get("strategy_display_name") or meta.get("display_name") or sid,
            "strategy_type": proposal.get("strategy_type") or meta.get("strategy_type"),
            "strategy_type_label": proposal.get("strategy_type_label") or meta.get("strategy_type_label"),
            "timeframe": proposal.get("strategy_timeframe_display") or meta.get("timeframe"),
        }
    except Exception:
        tc = (proposal.get("proposal_timeframe_class") or "").upper().replace("SHORT_SWING", "SHORT_SWING")
        return {
            "display_name": proposal.get("strategy_display_name") or sid,
            "strategy_type": tc or None,
            "strategy_type_label": tc.replace("_", " ").title() if tc else None,
            "timeframe": None,
        }


def build_proposal_alert_packet(proposal: dict) -> dict:
    """Build the decision packet for a Telegram alert."""
    alert_state = classify_proposal_alert_state(proposal)
    _meta = _strategy_meta(proposal)
    blockers = proposal.get("approval_blockers") or []
    er = proposal.get("execution_readiness") or {}
    rr = float(proposal.get("proposed_rr") or 0)
    entry = float(proposal.get("proposed_entry") or 0)
    stop = float(proposal.get("proposed_stop") or 0)
    target = float(proposal.get("proposed_target1") or 0)
    shares = int(proposal.get("proposed_shares") or 0)
    risk = abs(entry - stop) * shares if entry and stop and shares else 0

    # Action options
    actions = []
    if alert_state == "ACTIONABLE_READY":
        actions = ["APPROVE_PAPER", "REJECT", "WATCH", "OPEN_DETAILS"]
    elif alert_state == "BLOCKED_NEEDS_REBUILD":
        actions = ["REBUILD", "REJECT", "WATCH", "OPEN_DETAILS"]
    elif alert_state == "BLOCKED_EXECUTION_FAILED":
        actions = ["REBUILD", "REJECT", "OPEN_DETAILS"]
    else:
        actions = ["WATCH", "REJECT", "OPEN_DETAILS"]

    return {
        "alert_type": alert_state,
        "urgency": "HIGH" if alert_state == "ACTIONABLE_READY" else "MEDIUM" if "BLOCKED" in alert_state else "LOW",
        "proposal_id": proposal.get("id"),
        "symbol": proposal.get("symbol"),
        "strategy_id": proposal.get("strategy_id"),
        "strategy_display": _meta.get("display_name") or proposal.get("strategy_id"),
        "strategy_type": _meta.get("strategy_type"),
        "strategy_type_label": _meta.get("strategy_type_label"),
        "strategy_timeframe": _meta.get("timeframe"),
        "sector": proposal.get("sector"),
        "industry": proposal.get("industry"),
        "catalyst": proposal.get("catalyst"),
        "catalyst_verified": proposal.get("catalyst_verified"),
        "entry": entry, "stop": stop, "target": target,
        "rr": round(rr, 2), "shares": shares, "risk_dollars": round(risk, 2),
        "quote_provider": er.get("quote_provider") or proposal.get("last_price_source"),
        "quote_age": er.get("quote_age_seconds"),
        "execution_eligible": er.get("quote_execution_eligible"),
        "spread_pct": er.get("spread_pct"),
        "readiness_state": er.get("readiness_state"),
        "blockers": [str(b.get("reason", b)) if isinstance(b, dict) else str(b) for b in blockers[:5]],
        "missing_evidence": proposal.get("missing_data") or [],
        "approval_allowed": proposal.get("approval_allowed", False) and alert_state == "ACTIONABLE_READY",
        "actions": actions,
        "recommended_action": actions[0] if actions else "WATCH",
    }


def alert_suppression_key(proposal: dict) -> str:
    """Generate a dedup key so we don't spam the same alert."""
    parts = f"{proposal.get('id','')}-{proposal.get('symbol','')}-{proposal.get('status','')}-{proposal.get('operator_verdict','')}"
    return hashlib.md5(parts.encode()).hexdigest()[:12]


def should_send_alert(proposal: dict, recent_keys: set = None) -> dict:
    """Check whether this alert should be sent or suppressed."""
    key = alert_suppression_key(proposal)
    if recent_keys and key in recent_keys:
        return {"send": False, "reason": "duplicate_suppressed", "key": key}
    state = classify_proposal_alert_state(proposal)
    if state == "EXPIRED_OR_STALE":
        return {"send": False, "reason": "expired_no_alert", "key": key}
    return {"send": True, "reason": state, "key": key}


def _esc_md(s: str) -> str:
    """Escape Markdown V1 special characters in free text."""
    return str(s).replace("_", "\\_").replace("*", "\\*").replace("[", "\\[").replace("`", "\\`")


def format_telegram_message(packet: dict) -> str:
    """Format alert packet as Telegram message text."""
    emoji = {"ACTIONABLE_READY": "\u2705", "BLOCKED_NEEDS_REBUILD": "\u26a0\ufe0f",
             "BLOCKED_EXECUTION_FAILED": "\u274c", "NEEDS_OPERATOR_DECISION": "\u2753",
             "EXPIRED_OR_STALE": "\u23f0"}.get(packet["alert_type"], "\u2753")

    _type_line = _esc_md(packet.get("strategy_type_label") or packet.get("strategy_type") or "Unknown")
    if packet.get("strategy_timeframe"):
        _type_line += f" · {_esc_md(packet['strategy_timeframe'])}"
    lines = [
        f"{emoji} *Paper Proposal: {packet['symbol']}*",
        f"Strategy: {_esc_md(packet['strategy_display'])}",
        f"Type: {_type_line} | {packet['alert_type'].replace('_', ' ')}",
        "",
    ]

    if packet.get("sector"):
        lines.append(f"Sector: {packet['sector']}" + (f" / {packet['industry']}" if packet.get("industry") else ""))

    if packet.get("catalyst"):
        cv = "\u2705" if packet.get("catalyst_verified") else "\u26a0\ufe0f"
        cat = packet["catalyst"] if isinstance(packet["catalyst"], str) else "Yes"
        lines.append(f"Catalyst: {cv} {_esc_md(cat[:80])}")

    lines.append("")
    lines.append(f"Entry: ${packet['entry']:.2f} | Stop: ${packet['stop']:.2f} | Target: ${packet['target']:.2f}")
    lines.append(f"R:R: {packet['rr']}:1 | Risk: ${packet['risk_dollars']:.0f} | Shares: {packet['shares']}")

    if packet.get("quote_provider"):
        exec_flag = "\u2705" if packet.get("execution_eligible") else "\u274c"
        lines.append(f"Quote: {packet['quote_provider']} {exec_flag}" + (f" spread {packet['spread_pct']:.1f}%" if packet.get("spread_pct") else ""))

    if packet.get("blockers"):
        lines.append("")
        lines.append("*Blockers:*")
        for b in packet["blockers"][:3]:
            lines.append(f"\u2022 {b}")

    if packet.get("missing_evidence"):
        lines.append(f"Missing: {', '.join(packet['missing_evidence'][:5])}")

    lines.append("")
    lines.append(f"*Action:* {packet['recommended_action']}")
    if packet["approval_allowed"]:
        lines.append("_Approve Paper available_")
    else:
        lines.append("_Approval blocked — review required_")

    # ALERT-2: Add Telegram command shortcuts
    pid = packet.get("proposal_id") or "?"
    lines.append("")
    if packet["approval_allowed"]:
        lines.append(f"`/ptapprove {pid}`")
    lines.append(f"`/ptreject {pid}`")
    lines.append(f"`paper status`  |  Details: https://ms01-openclaw.tail163d14.ts.net/v3/trading")

    return "\n".join(lines)


def build_proposal_inline_keyboard(packet: dict) -> dict | None:
    """Build inline keyboard buttons for proposal alerts."""
    pid = packet.get("proposal_id")
    if not pid:
        return None

    rows = []
    if packet.get("approval_allowed"):
        rows.append([
            {"text": "Approve", "callback_data": f"ptapprove:{pid}"},
            {"text": "Reject", "callback_data": f"ptreject:{pid}"},
        ])
        rows.append([
            {"text": "\u00bd\u00d7 Shares", "callback_data": f"ptapprove_half:{pid}"},
            {"text": "2\u00d7 Shares", "callback_data": f"ptapprove_2x:{pid}"},
            {"text": "More Info", "callback_data": f"ptinfo:{pid}"},
        ])
    else:
        rows.append([
            {"text": "Approve", "callback_data": f"ptapprove:{pid}"},
            {"text": "Reject", "callback_data": f"ptreject:{pid}"},
            {"text": "More Info", "callback_data": f"ptinfo:{pid}"},
        ])

    return {"inline_keyboard": rows}
