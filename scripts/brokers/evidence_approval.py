#!/usr/bin/env python3
"""Evidence-bound operator approval — single-use, expiry, hash-tied revalidation."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import uuid
from typing import Any

APPROVAL_TTL_MIN = 30
QUOTE_TOLERANCE_PCT = 2.0


def _conn():
    from db_adapter import _get_conn
    return _get_conn()


def _ensure_table(cur) -> None:
    cur.execute("""CREATE TABLE IF NOT EXISTS evidence_bound_approvals (
                     id SERIAL PRIMARY KEY,
                     proposal_id TEXT,
                     intent_id TEXT NOT NULL,
                     correlation_id TEXT,
                     operator_user TEXT,
                     approval_channel TEXT,
                     approved_at TIMESTAMPTZ,
                     expires_at TIMESTAMPTZ,
                     single_use BOOLEAN DEFAULT TRUE,
                     used_at TIMESTAMPTZ,
                     evidence_hash TEXT NOT NULL,
                     proposal_snapshot_json JSONB,
                     risk_snapshot_json JSONB,
                     quote_snapshot_json JSONB,
                     chain_snapshot_json JSONB,
                     model_snapshot_json JSONB,
                     readiness_snapshot_json JSONB,
                     operator_attestation_text TEXT,
                     status TEXT DEFAULT 'approved',
                     created_at TIMESTAMPTZ DEFAULT NOW())""")


def _hash_snapshots(snapshots: dict) -> str:
    canonical = json.dumps(snapshots, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def create_evidence_approval(
    *,
    intent_id: str,
    proposal_id: str | None = None,
    correlation_id: str | None = None,
    operator_user: str = "operator",
    approval_channel: str = "web",
    proposal_snapshot: dict | None = None,
    risk_snapshot: dict | None = None,
    quote_snapshot: dict | None = None,
    chain_snapshot: dict | None = None,
    model_snapshot: dict | None = None,
    readiness_snapshot: dict | None = None,
    operator_attestation: str = "",
    ttl_minutes: int = APPROVAL_TTL_MIN,
) -> dict:
    """Bind operator approval to exact evidence snapshot."""
    conn = _conn()
    if not conn:
        return {"ok": False, "error": "db_unavailable"}
    snapshots = {
        "proposal": proposal_snapshot or {},
        "risk": risk_snapshot or {},
        "quote": quote_snapshot or {},
        "chain": chain_snapshot or {},
        "model": model_snapshot or {},
        "readiness": readiness_snapshot or {},
    }
    evidence_hash = _hash_snapshots(snapshots)
    cid = correlation_id or str(uuid.uuid4())
    expires = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=ttl_minutes)
    cur = conn.cursor()
    _ensure_table(cur)
    cur.execute(
        """INSERT INTO evidence_bound_approvals
           (proposal_id, intent_id, correlation_id, operator_user, approval_channel,
            approved_at, expires_at, single_use, evidence_hash,
            proposal_snapshot_json, risk_snapshot_json, quote_snapshot_json,
            chain_snapshot_json, model_snapshot_json, readiness_snapshot_json,
            operator_attestation_text, status)
           VALUES (%s,%s,%s,%s,%s,NOW(),%s,TRUE,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb,%s,'approved')
           RETURNING id""",
        (
            proposal_id, intent_id, cid, operator_user, approval_channel, expires, evidence_hash,
            json.dumps(proposal_snapshot or {}, default=str),
            json.dumps(risk_snapshot or {}, default=str),
            json.dumps(quote_snapshot or {}, default=str),
            json.dumps(chain_snapshot or {}, default=str),
            json.dumps(model_snapshot or {}, default=str),
            json.dumps(readiness_snapshot or {}, default=str),
            operator_attestation[:500],
        ),
    )
    aid = cur.fetchone()[0]
    conn.commit()
    try:
        from audit_ledger import record_event
        record_event("queue_approval", decision="approved", correlation_id=cid,
                     actor=operator_user, component="evidence_approval",
                     snapshot={"evidence_hash": evidence_hash, "intent_id": intent_id})
    except Exception:
        pass
    return {"ok": True, "approval_id": aid, "evidence_hash": evidence_hash,
            "expires_at": expires.isoformat(), "correlation_id": cid}


def fetch_approval(intent_id: str) -> dict | None:
    conn = _conn()
    if not conn:
        return None
    cur = conn.cursor()
    _ensure_table(cur)
    cur.execute(
        """SELECT id, proposal_id, intent_id, correlation_id, evidence_hash, expires_at,
                  used_at, status, proposal_snapshot_json, risk_snapshot_json, quote_snapshot_json,
                  readiness_snapshot_json
           FROM evidence_bound_approvals
           WHERE intent_id=%s AND status='approved'
           ORDER BY id DESC LIMIT 1""",
        (intent_id,),
    )
    row = cur.fetchone()
    if not row:
        return None
    return {
        "id": row[0], "proposal_id": row[1], "intent_id": row[2], "correlation_id": row[3],
        "evidence_hash": row[4], "expires_at": row[5], "used_at": row[6], "status": row[7],
        "proposal_snapshot": row[8], "risk_snapshot": row[9], "quote_snapshot": row[10],
        "readiness_snapshot": row[11],
    }


def revalidate_before_submit(
    intent_id: str,
    *,
    current_quote: dict | None = None,
    current_readiness: dict | None = None,
    kill_switch_check: bool = True,
) -> dict:
    """Revalidate evidence-bound approval immediately before confirm/submit."""
    rec = fetch_approval(intent_id)
    if not rec:
        return {"ok": False, "reason": "no_evidence_bound_approval", "hard_block": True}
    now = dt.datetime.now(dt.timezone.utc)
    if rec.get("used_at"):
        return {"ok": False, "reason": "approval_already_used_single_use", "hard_block": True}
    exp = rec.get("expires_at")
    if exp and now > exp:
        return {"ok": False, "reason": "approval_expired", "hard_block": True}
    orig_quote = rec.get("quote_snapshot") or {}
    if current_quote and orig_quote:
        op = _f(orig_quote.get("mid") or orig_quote.get("price"))
        cp = _f(current_quote.get("mid") or current_quote.get("price"))
        if op > 0 and cp > 0:
            move = abs(cp - op) / op * 100.0
            if move > QUOTE_TOLERANCE_PCT:
                return {"ok": False, "reason": f"quote_moved_{move:.2f}pct_beyond_tolerance",
                        "hard_block": True, "snapshot": {"orig": op, "current": cp}}
    if current_readiness and not current_readiness.get("ok"):
        return {"ok": False, "reason": "readiness_changed_to_block",
                "hard_block": True, "blocks": current_readiness.get("hard_blocks")}
    if kill_switch_check:
        try:
            from brokers.kill_switches import is_blocked
            blocked, reasons = is_blocked(live_submit=True)
            if blocked:
                return {"ok": False, "reason": "kill_switch_after_approval",
                        "hard_block": True, "reasons": reasons}
        except Exception:
            return {"ok": False, "reason": "kill_switch_check_failed", "hard_block": True}
    orig_hash = rec.get("evidence_hash")
    if current_readiness:
        new_hash = current_readiness.get("evidence_hash")
        if new_hash and orig_hash and new_hash != orig_hash:
            return {"ok": False, "reason": "evidence_hash_changed", "hard_block": True,
                    "orig": orig_hash, "current": new_hash}
    return {"ok": True, "evidence_hash": orig_hash, "approval_id": rec.get("id")}


def consume_approval(intent_id: str) -> bool:
    conn = _conn()
    if not conn:
        return False
    cur = conn.cursor()
    _ensure_table(cur)
    cur.execute(
        """UPDATE evidence_bound_approvals SET used_at=NOW(), status='consumed'
           WHERE intent_id=%s AND status='approved' AND used_at IS NULL""",
        (intent_id,),
    )
    n = cur.rowcount
    conn.commit()
    return n > 0


def _f(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default