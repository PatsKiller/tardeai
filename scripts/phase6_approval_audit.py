#!/usr/bin/env python3
"""phase6_approval_audit.py — Approval audit trail helper for Phase 6C.

Provides functions to create, update, and finalize audit records for
paper proposal approval attempts.

PAPER ONLY. No live trading. No secrets stored.
"""
import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("phase6_approval_audit")

MAX_JSON_SIZE = 50_000  # Truncate JSON payloads beyond this


def _hash(value: str) -> str:
    """SHA-256 hash for privacy (IP, user-agent)."""
    if not value:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


def _safe_json(obj, max_size=MAX_JSON_SIZE) -> str:
    """Serialize to JSON string, truncating if oversized."""
    if obj is None:
        return "{}"
    try:
        s = json.dumps(obj, default=str)
        if len(s) > max_size:
            return json.dumps({"_truncated": True, "_original_size": len(s),
                               "_preview": s[:2000]}, default=str)
        return s
    except Exception:
        return "{}"


def _get_safety_state() -> dict:
    """Capture current safety flags from environment or .env file."""
    # Try os.environ first, fall back to reading .env file
    alpaca_mode = os.getenv("ALPACA_MODE")
    llm_disable = os.getenv("LLM_DISABLE_LIVE_EXECUTION")
    live_trading = os.getenv("LIVE_TRADING")
    if not alpaca_mode:
        try:
            _proj = Path(__file__).resolve().parent.parent
            for line in (_proj / ".env").read_text().splitlines():
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    k, v = k.strip(), v.strip()
                    if k == "ALPACA_MODE" and not alpaca_mode:
                        alpaca_mode = v
                    elif k == "LLM_DISABLE_LIVE_EXECUTION" and not llm_disable:
                        llm_disable = v
                    elif k == "LIVE_TRADING" and not live_trading:
                        live_trading = v
        except Exception:
            pass
    return {
        "alpaca_mode": alpaca_mode or "unknown",
        "llm_live_execution_disabled": (llm_disable or "false").lower() == "true",
        "live_trading_enabled": (live_trading or "false").lower() == "true",
    }


def create_approval_audit_attempt(
    conn,
    proposal: dict,
    requested_by: str = None,
    request_source: str = None,
    request_ip: str = None,
    user_agent: str = None,
    metadata: dict = None,
) -> int:
    """Create initial audit row at start of approval attempt. Returns audit_id.

    Raises on failure so caller can fail-closed.
    """
    safety = _get_safety_state()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO paper_proposal_approval_audit (
            proposal_id, symbol, side, requested_by, request_source,
            request_ip_hash, user_agent_hash,
            approval_status, alpaca_mode, llm_live_execution_disabled,
            live_trading_enabled, proposal_snapshot_json, metadata_json,
            original_entry, stop_price, target_price
        ) VALUES (
            %s, %s, %s, %s, %s,
            %s, %s,
            'started', %s, %s,
            %s, %s::jsonb, %s::jsonb,
            %s, %s, %s
        ) RETURNING id
    """, [
        proposal.get("id") or proposal.get("proposal_id"),
        proposal.get("symbol"),
        proposal.get("side", "long"),
        requested_by or "dashboard",
        request_source or "api",
        _hash(request_ip),
        _hash(user_agent),
        safety["alpaca_mode"],
        safety["llm_live_execution_disabled"],
        safety["live_trading_enabled"],
        _safe_json({k: v for k, v in proposal.items()
                    if k not in ("catalyst", "thesis", "llm_analysis")}),
        _safe_json(metadata or {}),
        proposal.get("proposed_entry"),
        proposal.get("proposed_stop"),
        proposal.get("proposed_target1"),
    ])
    audit_id = cur.fetchone()[0]
    conn.commit()
    log.info(f"Audit #{audit_id} created for proposal #{proposal.get('id')}")
    return audit_id


def update_approval_audit(
    conn,
    audit_id: int,
    approval_status: str = None,
    block_reason: str = None,
    final_message: str = None,
    session_policy: dict = None,
    market_revalidation: dict = None,
    risk_gate: dict = None,
    proposal_snapshot: dict = None,
    paper_trade: dict = None,
    alpaca_response: dict = None,
    error: dict = None,
    gate: str = None,
    gate_passed: bool = None,
    fields: dict = None,
):
    """Update audit row with gate results. Non-critical — logs errors but doesn't raise."""
    try:
        sets = ["updated_at = NOW()"]
        params = []

        if approval_status:
            sets.append("approval_status = %s")
            params.append(approval_status)
        if block_reason:
            sets.append("block_reason = %s")
            params.append(block_reason[:2000])
        if final_message:
            sets.append("final_message = %s")
            params.append(final_message[:2000])
        if session_policy is not None:
            sets.append("session_policy_json = %s::jsonb")
            params.append(_safe_json(session_policy))
        if market_revalidation is not None:
            sets.append("market_revalidation_json = %s::jsonb")
            params.append(_safe_json(market_revalidation))
        if risk_gate is not None:
            sets.append("risk_gate_json = %s::jsonb")
            params.append(_safe_json(risk_gate))
        if paper_trade is not None:
            sets.append("paper_trade_json = %s::jsonb")
            params.append(_safe_json(paper_trade))
        if alpaca_response is not None:
            sets.append("alpaca_response_json = %s::jsonb")
            params.append(_safe_json(alpaca_response))
        if error is not None:
            sets.append("error_json = %s::jsonb")
            params.append(_safe_json(error))

        # Gate sequence append and flag
        if gate:
            sets.append("gate_sequence = array_append(gate_sequence, %s)")
            params.append(gate)
        if gate == "session_policy":
            sets.append("passed_session_gate = %s")
            params.append(gate_passed or False)
        elif gate == "market_revalidation":
            sets.append("passed_market_revalidation = %s")
            params.append(gate_passed or False)
        elif gate == "risk_gate":
            sets.append("passed_risk_gate = %s")
            params.append(gate_passed or False)
        elif gate == "paper_trade":
            sets.append("paper_trade_created = %s")
            params.append(gate_passed or False)
        elif gate == "alpaca_submission":
            sets.append("alpaca_submitted = %s")
            params.append(gate_passed or False)

        # Denormalized numeric fields
        if fields:
            for k in ("original_entry", "adjusted_entry", "live_price", "stop_price",
                       "target_price", "rr_at_approval", "spread_pct", "quote_age_minutes"):
                if k in fields and fields[k] is not None:
                    sets.append(f"{k} = %s")
                    params.append(fields[k])

        params.append(audit_id)
        cur = conn.cursor()
        cur.execute(f"UPDATE paper_proposal_approval_audit SET {', '.join(sets)} WHERE id = %s", params)
        conn.commit()
    except Exception as e:
        log.warning(f"Audit #{audit_id} update failed (non-critical): {e}")
        try:
            conn.rollback()
        except Exception:
            pass


def append_approval_audit_event(
    conn,
    audit_id: int,
    event_type: str,
    event_status: str,
    message: str = None,
    event_json: dict = None,
):
    """Append a granular event to the audit events table. Non-critical."""
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO paper_proposal_approval_audit_events
                (audit_id, event_type, event_status, message, event_json)
            VALUES (%s, %s, %s, %s, %s::jsonb)
        """, [audit_id, event_type, event_status,
              (message or "")[:2000], _safe_json(event_json)])
        conn.commit()
    except Exception as e:
        log.warning(f"Audit event append failed (non-critical): {e}")
        try:
            conn.rollback()
        except Exception:
            pass


def finalize_approval_audit(
    conn,
    audit_id: int,
    final_status: str,
    final_message: str,
    fields: dict = None,
):
    """Set final status on audit row."""
    update_approval_audit(
        conn, audit_id,
        approval_status=final_status,
        final_message=final_message,
        fields=fields,
    )
    append_approval_audit_event(
        conn, audit_id,
        event_type="finalized",
        event_status=final_status,
        message=final_message,
    )
