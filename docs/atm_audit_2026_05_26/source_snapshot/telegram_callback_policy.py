#!/usr/bin/env python3
"""telegram_callback_policy.py — Telegram callback validation for proposal actions.

Pure functions. No Telegram sends. No DB writes. No broker calls.
"""
import hashlib
from datetime import datetime, timezone

ALLOWED_ACTIONS = {"APPROVE_PAPER", "REJECT", "REBUILD", "WATCH", "OPEN_DETAILS"}
BLOCKED_ACTIONS_WHEN_NOT_READY = {"APPROVE_PAPER"}


def parse_callback_payload(payload: dict) -> dict:
    """Parse and normalize a callback payload."""
    return {
        "action": str(payload.get("action", "")).upper(),
        "proposal_id": payload.get("proposal_id"),
        "symbol": payload.get("symbol"),
        "source": payload.get("source", "telegram"),
        "operator": payload.get("operator", "primary"),
        "timestamp": payload.get("timestamp"),
    }


def classify_callback_action(payload: dict, proposal: dict) -> dict:
    """Determine whether a callback action is allowed for this proposal."""
    action = payload.get("action", "").upper()
    blockers = []

    if action not in ALLOWED_ACTIONS:
        return {"action": action, "allowed": False, "paper_only": True,
                "blockers": [f"unknown_action: {action}"], "response_text": f"Unknown action: {action}"}

    # Never allow live
    if action == "APPROVE_PAPER":
        # Check all gates
        approval_blockers = proposal.get("approval_blockers") or []
        er = proposal.get("execution_readiness") or {}
        readiness = er.get("readiness_state", "")
        rr = float(proposal.get("proposed_rr") or 0)
        status = proposal.get("status", "")

        if status not in ("PENDING", "pending"):
            blockers.append(f"proposal_not_pending: status={status}")

        if approval_blockers:
            blocker_reasons = [str(b.get("reason", b)) if isinstance(b, dict) else str(b) for b in approval_blockers]
            blockers.extend(blocker_reasons[:3])

        if "BLOCKED" in readiness.upper():
            blockers.append(f"execution_blocked: {readiness}")

        if rr < 2.0 and rr > 0:
            blockers.append(f"rr_below_minimum: {rr:.2f}")

        if not proposal.get("approval_allowed") and not blockers:
            blockers.append("approval_not_allowed")

    elif action == "REJECT":
        if proposal.get("status") not in ("PENDING", "pending"):
            blockers.append("proposal_not_pending")

    elif action == "REBUILD":
        pass  # Always allowed as request

    elif action == "WATCH":
        pass  # Always allowed

    elif action == "OPEN_DETAILS":
        pass  # Always allowed

    allowed = len(blockers) == 0

    # Response text
    if allowed:
        response = f"{action} allowed for {proposal.get('symbol', '?')} #{payload.get('proposal_id', '?')}"
    else:
        response = f"{action} BLOCKED: {'; '.join(blockers[:3])}"

    return {
        "action": action,
        "allowed": allowed,
        "paper_only": True,
        "blockers": blockers,
        "response_text": response,
    }


def callback_allowed_actions(proposal: dict) -> dict:
    """Return which callback actions are allowed for this proposal."""
    allowed = []
    blocked = []

    for action in ALLOWED_ACTIONS:
        result = classify_callback_action({"action": action}, proposal)
        if result["allowed"]:
            allowed.append(action)
        else:
            blocked.append(action)

    return {"allowed": sorted(allowed), "blocked": sorted(blocked)}


def callback_suppression_key(payload: dict) -> str:
    """Dedup key for callback actions."""
    parts = f"{payload.get('action','')}-{payload.get('proposal_id','')}-{payload.get('symbol','')}"
    return hashlib.md5(parts.encode()).hexdigest()[:12]


def build_callback_response(action_result: dict) -> dict:
    """Build a Telegram response message from action result."""
    if action_result.get("success"):
        return {
            "text": f"\u2705 {action_result.get('message', 'Action completed')}",
            "status": "success",
        }
    return {
        "text": f"\u274c {action_result.get('message', 'Action failed')}: {'; '.join(action_result.get('blockers', [])[:3])}",
        "status": "blocked" if action_result.get("blockers") else "error",
    }
