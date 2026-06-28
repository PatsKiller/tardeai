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


# ── Broker-truth status taxonomy (P0-5) ────────────────────────────────────────────
# Normalized broker statuses we recognize. Anything else normalizes to "unknown" and is
# routed to ERROR_RECONCILE_REQUIRED — internal state must never outrun broker truth.
NORMALIZED_STATUSES = (
    "queued", "working", "pending_activation", "accepted", "filled",
    "partially_filled", "canceled", "rejected", "expired", "unknown",
)

# Raw Schwab order statuses → our normalized vocabulary.
_RAW_TO_NORMALIZED = {
    "queued": "queued",
    "working": "working",
    "pending_activation": "pending_activation",
    "accepted": "accepted",
    "new": "accepted",
    "pending_acknowledgement": "accepted",
    "awaiting_parent_order": "pending_activation",
    "awaiting_condition": "pending_activation",
    "awaiting_manual_review": "pending_activation",
    "awaiting_release_time": "pending_activation",
    "awaiting_stop_condition": "pending_activation",
    "awaiting_ur_out": "working",
    "pending_cancel": "working",
    "pending_replace": "working",
    "replaced": "working",
    "filled": "filled",
    "partially_filled": "partially_filled",
    "canceled": "canceled",
    "cancelled": "canceled",
    "rejected": "rejected",
    "expired": "expired",
}

# Normalized status → canonical lifecycle state.
_NORMALIZED_TO_STATE = {
    "queued": "BROKER_ACKED",
    "pending_activation": "BROKER_ACKED",
    "accepted": "BROKER_ACKED",
    "working": "WORKING",
    "partially_filled": "PARTIALLY_FILLED",
    "filled": "FILLED",
    "canceled": "CANCELLED",
    "rejected": "REJECTED",
    "expired": "EXPIRED",
    "unknown": "ERROR_RECONCILE_REQUIRED",
}

# Local pilot/intent statuses considered an ACTIVE (open) submit for idempotency.
_ACTIVE_SUBMIT_STATUSES = frozenset({
    "submitting", "submitted", "submit_requested", "operator_approved",
    "broker_acked", "working", "accepted", "queued", "pending_activation",
    "partially_filled",
})


def normalize_broker_status(raw_status: str | None, *, filled_qty: float | None = None,
                            total_qty: float | None = None) -> dict:
    """Map a raw broker status (+ optional fill quantities) to the normalized taxonomy
    and a canonical lifecycle state. Partial fills are preserved explicitly.

    Fill quantities take precedence over an ambiguous raw status: if the broker reports
    a non-terminal status but ``0 < filled < total`` we treat it as ``partially_filled``;
    if ``filled >= total > 0`` we treat it as ``filled``. We NEVER infer FILLED/WORKING
    from anything other than broker truth.
    """
    norm = _RAW_TO_NORMALIZED.get(str(raw_status or "").strip().lower(), "unknown")
    fq = _num(filled_qty)
    tq = _num(total_qty)
    if tq and tq > 0 and fq is not None:
        if fq >= tq:
            norm = "filled"
        elif fq > 0 and norm not in ("rejected", "canceled", "expired"):
            norm = "partially_filled"
    state = _NORMALIZED_TO_STATE.get(norm, "ERROR_RECONCILE_REQUIRED")
    return {
        "raw": raw_status,
        "normalized": norm,
        "lifecycle_state": state,
        "is_live": state in ("WORKING", "PARTIALLY_FILLED", "FILLED"),
        "is_terminal": state in TERMINAL,
        "filled_qty": fq,
        "total_qty": tq,
    }


def apply_broker_status(current_state: str, raw_status: str | None, *,
                        broker_order_id: str | None = None,
                        filled_qty: float | None = None,
                        total_qty: float | None = None) -> dict:
    """Resolve the target lifecycle state from broker truth, enforcing:

      * FILLED/WORKING/PARTIALLY_FILLED require a broker order id (proof of ack). Without
        one, the order is routed to ERROR_RECONCILE_REQUIRED rather than a live state.
      * The transition itself must be legal from ``current_state``.
    """
    norm = normalize_broker_status(raw_status, filled_qty=filled_qty, total_qty=total_qty)
    target = norm["lifecycle_state"]
    if target in ("WORKING", "PARTIALLY_FILLED", "FILLED") and not broker_order_id:
        return {"ok": False, "reason": "live_state_requires_broker_order_id",
                "from": current_state, "would_be": target,
                "to": "ERROR_RECONCILE_REQUIRED", "normalized": norm}
    ev = transition(current_state, target, broker_order_id=broker_order_id,
                    reason=f"broker_status:{norm['normalized']}")
    return {"ok": ev.get("ok", False), "from": current_state, "to": target,
            "normalized": norm, "transition": ev}


def is_duplicate_active_submit(idem_key: str, existing: list[dict]) -> bool:
    """True if an ACTIVE (non-terminal, non-error) submit already exists for this
    idempotency key. Prevents a second live submit for the same intent/account/symbol."""
    for e in existing or []:
        if e.get("idempotency_key") != idem_key:
            continue
        if str(e.get("status", "")).strip().lower() in _ACTIVE_SUBMIT_STATUSES:
            return True
    return False


def submit_requires_reconcile(status: str, *, broker_order_id: str | None,
                              age_minutes: float, max_age_minutes: float = 30) -> bool:
    """A SUBMIT_REQUESTED/submitting row with no broker ack older than the threshold must
    be reconciled (GET broker truth) BEFORE any retry — never blind-retried."""
    s = str(status or "").strip().lower()
    if s not in ("submit_requested", "submitting", "submitted"):
        return False
    if broker_order_id:
        return False
    return age_minutes is not None and float(age_minutes) >= float(max_age_minutes)


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


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