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
                     evidence_hashes_json JSONB,
                     proposal_snapshot_json JSONB,
                     risk_snapshot_json JSONB,
                     quote_snapshot_json JSONB,
                     chain_snapshot_json JSONB,
                     model_snapshot_json JSONB,
                     readiness_snapshot_json JSONB,
                     operator_attestation_text TEXT,
                     status TEXT DEFAULT 'approved',
                     created_at TIMESTAMPTZ DEFAULT NOW())""")
    # Migration-safe: add the separate-hash column to pre-existing tables.
    try:
        cur.execute("ALTER TABLE evidence_bound_approvals ADD COLUMN IF NOT EXISTS evidence_hashes_json JSONB")
    except Exception:
        pass


def _hash_snapshots(snapshots: dict) -> str:
    canonical = json.dumps(snapshots, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _hash_one(snapshot: Any) -> str:
    """Canonical hash of a single bundle (dict/list/scalar). Stable across processes."""
    canonical = json.dumps(snapshot if snapshot is not None else {},
                           sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def order_spec_hash(order_spec: dict | None) -> str:
    """Canonical hash for the exact broker order payload submitted after approval."""
    return _hash_one(order_spec or {})


def compute_bundle_hashes(
    *,
    proposal_snapshot: dict | None = None,
    risk_snapshot: dict | None = None,
    quote_snapshot: dict | None = None,
    chain_snapshot: dict | None = None,
    model_snapshot: dict | None = None,
    readiness_snapshot: dict | None = None,
) -> dict:
    """Compute SEPARATE, like-to-like canonical hashes for each evidence bundle.

    Returns one hash per bundle plus an overall ``approval_evidence_hash`` that binds
    them all. Revalidation MUST compare each regenerated bundle hash against its stored
    counterpart of the SAME type — never an overall hash against a single-bundle hash
    (that comparison is meaningless and produces false blocks / false confidence).

    For the readiness bundle we prefer the readiness resolver's own ``evidence_hash``
    (when present) so that ``readiness_hash`` stored here is identical in kind to what
    ``evaluate_execution_readiness`` emits at submit time.
    """
    readiness_snapshot = readiness_snapshot or {}
    readiness_self_hash = readiness_snapshot.get("evidence_hash") if isinstance(readiness_snapshot, dict) else None
    bundles = {
        "proposal": proposal_snapshot or {},
        "risk": risk_snapshot or {},
        "quote": quote_snapshot or {},
        "chain": chain_snapshot or {},
        "model": model_snapshot or {},
        "readiness": readiness_snapshot or {},
    }
    hashes = {
        "approval_evidence_hash": _hash_snapshots(bundles),
        "proposal_snapshot_hash": _hash_one(proposal_snapshot),
        "risk_snapshot_hash": _hash_one(risk_snapshot),
        "quote_snapshot_hash": _hash_one(quote_snapshot),
        "chain_snapshot_hash": _hash_one(chain_snapshot),
        "model_snapshot_hash": _hash_one(model_snapshot),
        "readiness_hash": readiness_self_hash or _hash_one(readiness_snapshot),
    }
    return hashes


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
    bundle_hashes = compute_bundle_hashes(
        proposal_snapshot=proposal_snapshot, risk_snapshot=risk_snapshot,
        quote_snapshot=quote_snapshot, chain_snapshot=chain_snapshot,
        model_snapshot=model_snapshot, readiness_snapshot=readiness_snapshot,
    )
    # `evidence_hash` remains the overall approval-evidence binding (backward compatible).
    evidence_hash = bundle_hashes["approval_evidence_hash"]
    cid = correlation_id or str(uuid.uuid4())
    expires = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=ttl_minutes)
    cur = conn.cursor()
    _ensure_table(cur)
    cur.execute(
        """INSERT INTO evidence_bound_approvals
           (proposal_id, intent_id, correlation_id, operator_user, approval_channel,
            approved_at, expires_at, single_use, evidence_hash, evidence_hashes_json,
            proposal_snapshot_json, risk_snapshot_json, quote_snapshot_json,
            chain_snapshot_json, model_snapshot_json, readiness_snapshot_json,
            operator_attestation_text, status)
           VALUES (%s,%s,%s,%s,%s,NOW(),%s,TRUE,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb,%s,'approved')
           RETURNING id""",
        (
            proposal_id, intent_id, cid, operator_user, approval_channel, expires, evidence_hash,
            json.dumps(bundle_hashes, default=str),
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
                     snapshot={"evidence_hash": evidence_hash, "readiness_hash": bundle_hashes["readiness_hash"],
                               "intent_id": intent_id})
    except Exception:
        pass
    return {"ok": True, "approval_id": aid, "evidence_hash": evidence_hash,
            "hashes": bundle_hashes,
            "expires_at": expires.isoformat(), "correlation_id": cid}


def _confirmed_approval_context(intent_id: str) -> dict:
    """Best-effort channel/operator context for the approval that unlocked an intent."""
    conn = _conn()
    if not conn:
        return {}
    cur = conn.cursor()
    try:
        cur.execute(
            """SELECT channel, code, confirmed_at, expires_at
               FROM trade_approvals
               WHERE intent_id=%s AND status='confirmed'
               ORDER BY confirmed_at DESC NULLS LAST, id DESC LIMIT 1""",
            (intent_id,),
        )
        row = cur.fetchone()
    except Exception:
        return {}
    if not row:
        return {}
    proof = str(row[1] or "")
    return {
        "approval_channel": row[0] or "web",
        "operator_user": "operator",
        "ticker_code_proof_hash": _hash_one({"channel": row[0] or "web", "proof": proof}),
        "proof_type": "typed_ticker" if row[0] == "web" else "six_digit_code",
        "confirmed_at": row[2].isoformat() if hasattr(row[2], "isoformat") else str(row[2] or ""),
        "expires_at": row[3].isoformat() if hasattr(row[3], "isoformat") else str(row[3] or ""),
    }


def create_order_evidence_approval(
    intent,
    order_spec: dict,
    *,
    readiness_snapshot: dict | None = None,
    risk_snapshot: dict | None = None,
    quote_snapshot: dict | None = None,
    chain_snapshot: dict | None = None,
    model_snapshot: dict | None = None,
    operator_user: str | None = None,
    approval_channel: str | None = None,
) -> dict:
    """Bind a fully approved live order intent to the exact Schwab order spec.

    This is used immediately before the broker submit boundary. It does not approve
    anything by itself; callers must first verify the normal per-order 2FA approval.
    """
    iid = str(getattr(intent, "intent_id", "") or "").strip()
    if not iid:
        return {"ok": False, "error": "intent_id_required"}
    existing = fetch_approval(iid)
    if existing and not existing.get("used_at"):
        return {"ok": True, "approval_id": existing.get("id"),
                "evidence_hash": existing.get("evidence_hash"),
                "correlation_id": existing.get("correlation_id"),
                "existing": True}
    inst = getattr(intent, "instrument", None)
    ev = (getattr(getattr(intent, "meta", None), "signal_evidence", None) or {})
    ctx = _confirmed_approval_context(iid)
    spec_hash = order_spec_hash(order_spec)
    proposal_snapshot = {
        "intent_id": iid,
        "correlation_id": str(getattr(intent, "correlation_id", "") or ""),
        "account_key": getattr(intent, "account_key", None),
        "broker": getattr(intent, "broker", None),
        "symbol": (getattr(inst, "symbol", "") or "").upper(),
        "qty": getattr(getattr(intent, "quantity", None), "qty", None),
        "order_type": ev.get("order_type") or order_spec.get("orderType"),
        "stop_price": ev.get("stop_price") or order_spec.get("stopPrice"),
        "limit_price": ev.get("limit_price") or order_spec.get("price"),
        "trail_pct": ev.get("trail_pct") or order_spec.get("stopPriceOffset"),
        "time_in_force": order_spec.get("duration"),
        "current_price": ev.get("current_price"),
        "held_qty": ev.get("held_qty"),
        "residual_qty": ev.get("residual_qty"),
        "approval_channel": approval_channel or ctx.get("approval_channel") or "web",
        "proof_type": ctx.get("proof_type"),
        "ticker_code_proof_hash": ctx.get("ticker_code_proof_hash"),
        "order_spec_hash": spec_hash,
        "order_spec": order_spec,
    }
    if quote_snapshot is None and ev.get("current_price") is not None:
        quote_snapshot = {"price": ev.get("current_price"), "symbol": proposal_snapshot["symbol"]}
    res = create_evidence_approval(
        intent_id=iid,
        proposal_id=ev.get("proposal_id"),
        correlation_id=proposal_snapshot["correlation_id"] or None,
        operator_user=operator_user or ctx.get("operator_user") or "operator",
        approval_channel=approval_channel or ctx.get("approval_channel") or "web",
        proposal_snapshot=proposal_snapshot,
        risk_snapshot=risk_snapshot,
        quote_snapshot=quote_snapshot,
        chain_snapshot=chain_snapshot,
        model_snapshot=model_snapshot,
        readiness_snapshot=readiness_snapshot,
        operator_attestation=(
            f"Approved {proposal_snapshot['symbol']} {proposal_snapshot['order_type']} "
            f"{proposal_snapshot['qty']} for {proposal_snapshot['account_key']} "
            f"spec={spec_hash}"
        ),
    )
    if res.get("approval_id") is not None:
        res["evidence_id"] = res.get("approval_id")
    if res.get("hashes"):
        res["order_spec_hash"] = spec_hash
    return res


def fetch_approval(intent_id: str) -> dict | None:
    conn = _conn()
    if not conn:
        return None
    cur = conn.cursor()
    _ensure_table(cur)
    cur.execute(
        """SELECT id, proposal_id, intent_id, correlation_id, evidence_hash, expires_at,
                  used_at, status, proposal_snapshot_json, risk_snapshot_json, quote_snapshot_json,
                  readiness_snapshot_json, evidence_hashes_json, chain_snapshot_json
           FROM evidence_bound_approvals
           WHERE intent_id=%s AND status='approved'
           ORDER BY id DESC LIMIT 1""",
        (intent_id,),
    )
    row = cur.fetchone()
    if not row:
        return None
    hashes = row[12] or {}
    if isinstance(hashes, str):
        try:
            hashes = json.loads(hashes)
        except Exception:
            hashes = {}
    return {
        "id": row[0], "proposal_id": row[1], "intent_id": row[2], "correlation_id": row[3],
        "evidence_hash": row[4], "expires_at": row[5], "used_at": row[6], "status": row[7],
        "proposal_snapshot": row[8], "risk_snapshot": row[9], "quote_snapshot": row[10],
        "readiness_snapshot": row[11], "hashes": hashes, "chain_snapshot": row[13],
    }


def revalidate_before_submit(
    intent_id: str,
    *,
    current_quote: dict | None = None,
    current_readiness: dict | None = None,
    current_risk: dict | None = None,
    current_chain: dict | None = None,
    current_order_spec: dict | None = None,
    kill_switch_check: bool = True,
    require_readiness: bool = True,
) -> dict:
    """Revalidate evidence-bound approval immediately before confirm/submit.

    Comparison is strictly LIKE-TO-LIKE: each regenerated bundle hash is compared only
    against the stored hash of the SAME bundle type. We never compare the overall
    approval-evidence hash against a single-bundle (e.g. readiness) hash — that produced
    spurious blocks in the prior implementation. If a required bundle cannot be
    regenerated, we fail closed.

    Returns a dict whose ``checks`` field records each like-to-like comparison performed.
    """
    rec = fetch_approval(intent_id)
    if not rec:
        return {"ok": False, "reason": "no_evidence_bound_approval", "hard_block": True}
    stored = rec.get("hashes") or {}
    checks: list[dict] = []
    now = dt.datetime.now(dt.timezone.utc)
    if rec.get("used_at"):
        return {"ok": False, "reason": "approval_already_used_single_use", "hard_block": True}
    exp = rec.get("expires_at")
    if exp and now > exp:
        return {"ok": False, "reason": "approval_expired", "hard_block": True}

    # ── Broker order spec: exact hash match. Price/qty/account/type changes need a new approval. ──
    proposal = rec.get("proposal_snapshot") or {}
    stored_order_spec_hash = proposal.get("order_spec_hash") if isinstance(proposal, dict) else None
    if stored_order_spec_hash:
        if current_order_spec is None:
            return {"ok": False, "reason": "order_spec_bundle_unavailable_fail_closed",
                    "hard_block": True, "checks": checks}
        new_order_spec_hash = order_spec_hash(current_order_spec)
        checks.append({"bundle": "order_spec", "kind": "hash",
                       "match": new_order_spec_hash == stored_order_spec_hash})
        if new_order_spec_hash != stored_order_spec_hash:
            return {"ok": False, "reason": "order_spec_hash_changed", "hard_block": True,
                    "orig": stored_order_spec_hash, "current": new_order_spec_hash, "checks": checks}

    # ── Quote: tolerance-based (price drift), NOT hash-exact — a 1-cent move must not block. ──
    orig_quote = rec.get("quote_snapshot") or {}
    if current_quote and orig_quote:
        op = _f(orig_quote.get("mid") or orig_quote.get("price"))
        cp = _f(current_quote.get("mid") or current_quote.get("price"))
        if op > 0 and cp > 0:
            move = abs(cp - op) / op * 100.0
            checks.append({"bundle": "quote", "kind": "tolerance", "move_pct": round(move, 4),
                           "tolerance_pct": QUOTE_TOLERANCE_PCT})
            if move > QUOTE_TOLERANCE_PCT:
                return {"ok": False, "reason": f"quote_moved_{move:.2f}pct_beyond_tolerance",
                        "hard_block": True, "snapshot": {"orig": op, "current": cp}, "checks": checks}

    # ── Readiness: like-to-like readiness_hash, and hard-block status. ──
    if current_readiness and not current_readiness.get("ok"):
        return {"ok": False, "reason": "readiness_changed_to_block",
                "hard_block": True, "blocks": current_readiness.get("hard_blocks"), "checks": checks}
    stored_readiness_hash = stored.get("readiness_hash")
    if current_readiness:
        new_readiness_hash = current_readiness.get("evidence_hash") or current_readiness.get("readiness_hash")
        if stored_readiness_hash and new_readiness_hash:
            checks.append({"bundle": "readiness", "kind": "hash",
                           "match": new_readiness_hash == stored_readiness_hash})
            if new_readiness_hash != stored_readiness_hash:
                return {"ok": False, "reason": "readiness_hash_changed", "hard_block": True,
                        "orig": stored_readiness_hash, "current": new_readiness_hash, "checks": checks}
    elif require_readiness:
        # Submit context requires a regenerated readiness bundle — fail closed if absent.
        return {"ok": False, "reason": "readiness_bundle_unavailable_fail_closed",
                "hard_block": True, "checks": checks}

    # ── Risk: like-to-like risk_snapshot_hash (exact). ──
    if current_risk is not None:
        stored_risk_hash = stored.get("risk_snapshot_hash")
        new_risk_hash = _hash_one(current_risk)
        if stored_risk_hash:
            checks.append({"bundle": "risk", "kind": "hash", "match": new_risk_hash == stored_risk_hash})
            if new_risk_hash != stored_risk_hash:
                return {"ok": False, "reason": "risk_state_changed", "hard_block": True,
                        "orig": stored_risk_hash, "current": new_risk_hash, "checks": checks}
        else:
            return {"ok": False, "reason": "risk_bundle_unavailable_fail_closed",
                    "hard_block": True, "checks": checks}

    # ── Chain: like-to-like chain_snapshot_hash (material change). ──
    if current_chain is not None:
        stored_chain_hash = stored.get("chain_snapshot_hash")
        new_chain_hash = _hash_one(current_chain)
        if stored_chain_hash:
            checks.append({"bundle": "chain", "kind": "hash", "match": new_chain_hash == stored_chain_hash})
            if new_chain_hash != stored_chain_hash:
                return {"ok": False, "reason": "chain_changed_materially", "hard_block": True,
                        "orig": stored_chain_hash, "current": new_chain_hash, "checks": checks}
        else:
            return {"ok": False, "reason": "chain_bundle_unavailable_fail_closed",
                    "hard_block": True, "checks": checks}

    # ── Kill switch: re-check at submit (post-approval activation must block). ──
    if kill_switch_check:
        try:
            from brokers.kill_switches import is_blocked
            blocked, reasons = is_blocked(live_submit=True)
            if blocked:
                return {"ok": False, "reason": "kill_switch_after_approval",
                        "hard_block": True, "reasons": reasons, "checks": checks}
        except Exception:
            return {"ok": False, "reason": "kill_switch_check_failed", "hard_block": True, "checks": checks}

    return {"ok": True, "evidence_hash": rec.get("evidence_hash"),
            "readiness_hash": stored_readiness_hash, "approval_id": rec.get("id"), "checks": checks}


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
