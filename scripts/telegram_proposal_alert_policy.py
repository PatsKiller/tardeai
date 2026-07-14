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


def _account_meta(proposal: dict) -> dict:
    acct = (proposal.get("target_account") or proposal.get("proposed_account")
            or proposal.get("intended_broker") or proposal.get("final_account") or "")
    acct = str(acct).strip()
    display = acct
    lane = "paper_atm"
    try:
        from broker_config import get_account_display_name
        if acct:
            display = get_account_display_name(acct)
    except Exception:
        try:
            from automated_account import display_account_label
            display = display_account_label(acct) if acct else "—"
        except Exception:
            display = acct.replace("_", " ").title() if acct else "—"
    if acct.startswith("schwab") or acct.startswith("fidelity"):
        lane = "live_2fa"
    elif acct:
        try:
            from automated_account import is_automated_account
            lane = "paper_atm" if is_automated_account(acct) else "live_2fa"
        except Exception:
            pass
    lane_label = {"live_2fa": "Schwab/Fidelity · 2FA manual", "paper_atm": "Automated · Alpaca paper"}.get(lane, lane)
    return {"account_key": acct, "account_display": display, "routing_lane": lane, "routing_lane_label": lane_label}


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
    _acct = _account_meta(proposal)
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
        "status": proposal.get("status"),
        "proposed_by": proposal.get("proposed_by") or proposal.get("source"),
        "account_key": _acct.get("account_key"),
        "account_display": _acct.get("account_display"),
        "routing_lane": _acct.get("routing_lane"),
        "routing_lane_label": _acct.get("routing_lane_label"),
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
    pid = packet.get("proposal_id") or "?"
    try:
        from notification_url_builder import build_proposal_url
        detail_url = build_proposal_url(pid, packet.get("symbol"))
    except Exception:
        detail_url = None

    lines = [
        f"{emoji} *Trade Proposal #{pid}: {packet['symbol']}*",
        f"Strategy: {_esc_md(packet['strategy_display'])}",
        f"Type: {_type_line} | {packet['alert_type'].replace('_', ' ')}",
    ]
    if packet.get("account_display"):
        acct_line = f"Account: {_esc_md(packet['account_display'])}"
        if packet.get("routing_lane_label"):
            acct_line += f" · {_esc_md(packet['routing_lane_label'])}"
        lines.append(acct_line)
    if packet.get("status"):
        src = packet.get("proposed_by") or ""
        src_bit = f" · via {_esc_md(str(src).replace('_', ' '))}" if src else ""
        lines.append(f"Status: {packet['status']}{src_bit}")
    lines.append("")

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
        lines.append("_Approve & route available_")
    else:
        lines.append("_Execution gates failed — review in Command Center (not a 2FA order approval)_")

    # ALERT-2: Add Telegram command shortcuts
    lines.append("")
    if packet["approval_allowed"]:
        lines.append(f"`/ptapprove {pid}`")
    lines.append(f"`/ptreject {pid}`")
    if detail_url:
        lines.append(f"[Open proposal #{pid}]({detail_url})")
    else:
        lines.append(f"Details: /v3/trading?tab=Proposals&proposal={pid}")

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

    try:
        from notification_url_builder import build_proposal_url
        url = build_proposal_url(pid, packet.get("symbol"))
        if url:
            rows.append([{"text": "🔎 Review proposal", "url": url}])
    except Exception:
        pass

    return {"inline_keyboard": rows}
