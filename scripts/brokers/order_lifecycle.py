#!/usr/bin/env python3
"""Strict broker-truth order lifecycle — internal state never outruns broker ack."""
from __future__ import annotations

import datetime as dt
import uuid
from enum import Enum
from typing import Any

# Canonical lifecycle states
STATES = (
    "PROPOSED", "PREFLIGHTED", "OPERATOR_APPROVED", "SUBMIT_REQUESTED",
    "BROKER_ACKED", "WORKING", "PARTIALLY_FILLED", "FILLED",
    "CANCEL_REQUESTED", "CANCELLED", "REJECTED", "EXPIRED", "ERROR_RECONCILE_REQUIRED",
)


class OrderState(str, Enum):
    PROPOSED = "PROPOSED"
    PREFLIGHTED = "PREFLIGHTED"
    OPERATOR_APPROVED = "OPERATOR_APPROVED"
    SUBMIT_REQUESTED = "SUBMIT_REQUESTED"
    BROKER_ACKED = "BROKER_ACKED"
    WORKING = "WORKING"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    ERROR_RECONCILE_REQUIRED = "ERROR_RECONCILE_REQUIRED"


# Allowed transitions: from -> set(to)
_TRANSITIONS: dict[str, set[str]] = {
    "PROPOSED": {"PREFLIGHTED", "EXPIRED", "REJECTED"},
    "PREFLIGHTED": {"OPERATOR_APPROVED", "REJECTED", "EXPIRED", "PROPOSED"},
    "OPERATOR_APPROVED": {"SUBMIT_REQUESTED", "EXPIRED", "REJECTED", "PREFLIGHTED"},
    "SUBMIT_REQUESTED": {"BROKER_ACKED", "REJECTED", "ERROR_RECONCILE_REQUIRED", "CANCELLED"},
    "BROKER_ACKED": {"WORKING", "PARTIALLY_FILLED", "FILLED", "REJECTED", "CANCELLED", "ERROR_RECONCILE_REQUIRED"},
    "WORKING": {"PARTIALLY_FILLED", "FILLED", "CANCEL_REQUESTED", "CANCELLED", "REJECTED", "EXPIRED"},
    "PARTIALLY_FILLED": {"FILLED", "CANCEL_REQUESTED", "CANCELLED", "REJECTED"},
    "CANCEL_REQUESTED": {"CANCELLED", "WORKING", "ERROR_RECONCILE_REQUIRED"},
    "FILLED": set(),
    "CANCELLED": set(),
    "REJECTED": set(),
    "EXPIRED": set(),
    "ERROR_RECONCILE_REQUIRED": {"BROKER_ACKED", "WORKING", "CANCELLED", "REJECTED", "FILLED"},
}


TERMINAL = frozenset({"FILLED", "CANCELLED", "REJECTED", "EXPIRED"})


def can_transition(current: str, target: str) -> bool:
    cur = (current or "PROPOSED").upper()
    tgt = (target or "").upper()
    if cur == tgt:
        return True
    return tgt in _TRANSITIONS.get(cur, set())


def is_live_before_ack(state: str) -> bool:
    """True if state incorrectly treats order as live before broker ack."""
    s = (state or "").upper()
    return s in {"WORKING", "PARTIALLY_FILLED", "FILLED"} and s != "BROKER_ACKED"


def transition(
    current: str,
    target: str,
    *,
    correlation_id: str | None = None,
    broker_order_id: str | None = None,
    reason: str = "",
    actor: str = "system",
) -> dict:
    """Validate and record a lifecycle transition. Does not persist unless caller does."""
    cur = (current or "PROPOSED").upper()
    tgt = (target or "").upper()
    if tgt not in STATES:
        return {"ok": False, "error": f"invalid_state:{tgt}", "from": cur, "to": tgt}
    if not can_transition(cur, tgt):
        return {"ok": False, "error": f"illegal_transition:{cur}->{tgt}", "from": cur, "to": tgt}
    # Broker truth rule: cannot reach WORKING/FILLED without BROKER_ACKED path
    if tgt in ("WORKING", "PARTIALLY_FILLED", "FILLED") and cur not in (
        "BROKER_ACKED", "WORKING", "PARTIALLY_FILLED", "ERROR_RECONCILE_REQUIRED",
    ):
        return {"ok": False, "error": "broker_ack_required_before_live_state", "from": cur, "to": tgt}
    cid = correlation_id or str(uuid.uuid4())
    event = {
        "ok": True,
        "from": cur,
        "to": tgt,
        "correlation_id": cid,
        "broker_order_id": broker_order_id,
        "reason": reason,
        "actor": actor,
        "at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    try:
        from audit_ledger import record_event
        record_event(
            "order_lifecycle_transition",
            decision=tgt,
            reason=reason or f"{cur}->{tgt}",
            correlation_id=cid,
            actor=actor,
            component="order_lifecycle",
            snapshot=event,
        )
    except Exception:
        pass
    return event


def idempotency_key(intent_id: str, account_key: str, symbol: str) -> str:
    """Stable idempotency key for submit deduplication."""
    import hashlib
    raw = f"{intent_id}|{account_key}|{symbol}".encode()
    return hashlib.sha256(raw).hexdigest()[:32]


def persist_intent_state(intent_id: str, state: str, *, broker_order_id: str | None = None) -> dict:
    """Update broker_order_intents.state if DB available."""
    try:
        from db_adapter import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute(
            """UPDATE broker_order_intents SET state=%s, updated_at=NOW()
               WHERE intent_id=%s""",
            (state, intent_id),
        )
        if broker_order_id:
            cur.execute(
                """UPDATE schwab_pilot_orders SET broker_order_id=%s, status=%s, updated_at=NOW()
                   WHERE intent_id=%s AND broker_order_id IS NULL""",
                (broker_order_id, state.lower(), intent_id),
            )
        conn.commit()
        return {"ok": True, "intent_id": intent_id, "state": state}
    except Exception as e:
        return {"ok": False, "error": str(e)[:120]}