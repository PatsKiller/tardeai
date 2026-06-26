#!/usr/bin/env python3
"""proposal_execution_readiness.py — Agnostic proposal funnel: readiness, blocks, link rates.

Proposals are account-agnostic (simulation or live destination). Read-only unless noted.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any


def _conn():
    from db_adapter import _get_conn
    return _get_conn()


def _rows(sql: str, params=None) -> list[dict]:
    conn = _conn()
    if not conn:
        return []
    try:
        import psycopg2.extras
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params or [])
            return [dict(r) for r in cur.fetchall()]
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return []


def collect_execution_readiness(*, since_days: int = 7) -> dict[str, Any]:
    """Dashboard payload: block reasons, revalidation mix, timing, link rate."""
    interval = f"{since_days} days"
    block_rows = _rows(
        f"""SELECT COALESCE(NULLIF(TRIM(risk_gate_result), ''), 'UNKNOWN') AS gate,
                   COUNT(*) AS n
            FROM paper_trade_proposals
            WHERE created_at > NOW() - INTERVAL '{interval}'
            GROUP BY 1 ORDER BY n DESC LIMIT 20"""
    )
    action_rows = _rows(
        f"""SELECT COALESCE(NULLIF(TRIM(action_state), ''), 'none') AS action_state,
                   COUNT(*) AS n
            FROM paper_trade_proposals
            WHERE created_at > NOW() - INTERVAL '{interval}'
              AND status IN ('PENDING', 'APPROVED_FOR_PAPER_TEST', 'APPROVED')
            GROUP BY 1 ORDER BY n DESC"""
    )
    created = _rows(
        f"SELECT COUNT(*) AS n FROM paper_trade_proposals WHERE created_at > NOW() - INTERVAL '{interval}'"
    )
    linked = _rows(
        f"""SELECT COUNT(*) AS n FROM paper_trade_proposals
            WHERE created_at > NOW() - INTERVAL '{interval}' AND paper_trade_id IS NOT NULL"""
    )
    approved = _rows(
        f"""SELECT COUNT(*) AS n FROM paper_trade_proposals
            WHERE created_at > NOW() - INTERVAL '{interval}'
              AND status IN ('APPROVED_FOR_PAPER_TEST', 'APPROVED')"""
    )
    pending = _rows(
        """SELECT COUNT(*) AS n FROM paper_trade_proposals
           WHERE status IN ('PENDING', 'APPROVED_FOR_PAPER_TEST', 'APPROVED')"""
    )
    broker_unrouted = _rows(
        """SELECT COUNT(*) AS n FROM paper_trade_proposals
           WHERE status IN ('PENDING', 'APPROVED_FOR_PAPER_TEST')
             AND (intended_broker ILIKE 'schwab%%' OR intended_broker ILIKE 'fidelity%%')
             AND live_submit_path IS NULL
             AND created_at < NOW() - INTERVAL '48 hours'"""
    )
    timing = _rows(
        f"""SELECT
              ROUND(AVG(EXTRACT(EPOCH FROM (updated_at - created_at)) / 3600.0)
                    FILTER (WHERE status IN ('APPROVED_FOR_PAPER_TEST','APPROVED'))::numeric, 2) AS avg_hours_to_approve,
              ROUND(AVG(EXTRACT(EPOCH FROM (NOW() - created_at)) / 3600.0)
                    FILTER (WHERE status IN ('PENDING','APPROVED_FOR_PAPER_TEST'))::numeric, 2) AS avg_pending_age_h
            FROM paper_trade_proposals
            WHERE created_at > NOW() - INTERVAL '{interval}'"""
    )
    n_created = int((created[0] or {}).get("n") or 0)
    n_linked = int((linked[0] or {}).get("n") or 0)
    link_pct = round(100.0 * n_linked / max(n_created, 1), 1)
    blocks = {r["gate"]: int(r["n"]) for r in block_rows}
    price_dominated = sum(
        n for k, n in blocks.items()
        if k and any(x in str(k).upper() for x in ("PRICE", "DRIFT", "STALE", "MOVED"))
    )
    return {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "since_days": since_days,
        "created": n_created,
        "approved": int((approved[0] or {}).get("n") or 0),
        "linked_to_execution": n_linked,
        "link_rate_pct": link_pct,
        "pending_now": int((pending[0] or {}).get("n") or 0),
        "broker_unrouted_48h": int((broker_unrouted[0] or {}).get("n") or 0),
        "risk_gate_blocks": blocks,
        "action_state_counts": {r["action_state"]: int(r["n"]) for r in action_rows},
        "avg_hours_to_approve": float((timing[0] or {}).get("avg_hours_to_approve") or 0),
        "avg_pending_age_h": float((timing[0] or {}).get("avg_pending_age_h") or 0),
        "price_block_dominant": price_dominated > sum(blocks.values()) * 0.25 if blocks else False,
        "target_link_rate_pct": float(os.getenv("PROPOSAL_TARGET_LINK_RATE_PCT", "15")),
    }


def collect_execution_link_audit(*, since_days: int = 5) -> dict[str, Any]:
    """Closed-loop: created → approved → execution-linked → closed."""
    interval = f"{since_days} days"
    funnel = _rows(
        f"""SELECT
              COUNT(*) AS created,
              COUNT(*) FILTER (WHERE status IN ('APPROVED_FOR_PAPER_TEST','APPROVED')) AS approved,
              COUNT(*) FILTER (WHERE paper_trade_id IS NOT NULL) AS execution_linked,
              COUNT(*) FILTER (WHERE live_submit_path IS NOT NULL) AS live_submit_tagged,
              COUNT(*) FILTER (WHERE status = 'EXPIRED') AS expired,
              COUNT(*) FILTER (WHERE status = 'REJECTED') AS rejected
            FROM paper_trade_proposals
            WHERE created_at > NOW() - INTERVAL '{interval}'"""
    )
    closed = _rows(
        f"""SELECT COUNT(DISTINCT p.id) AS n
            FROM paper_trade_proposals p
            JOIN paper_trades t ON t.proposal_id = p.id
            WHERE p.created_at > NOW() - INTERVAL '{interval}'
              AND t.lifecycle_state = 'closed'"""
    )
    f = funnel[0] if funnel else {}
    created = int(f.get("created") or 0)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "since_days": since_days,
        "created": created,
        "approved": int(f.get("approved") or 0),
        "execution_linked": int(f.get("execution_linked") or 0),
        "live_submit_tagged": int(f.get("live_submit_tagged") or 0),
        "closed_trades": int((closed[0] or {}).get("n") or 0),
        "expired": int(f.get("expired") or 0),
        "rejected": int(f.get("rejected") or 0),
        "approval_rate_pct": round(100 * int(f.get("approved") or 0) / max(created, 1), 1),
        "execution_link_rate_pct": round(100 * int(f.get("execution_linked") or 0) / max(created, 1), 1),
        "close_rate_pct": round(100 * int((closed[0] or {}).get("n") or 0) / max(created, 1), 1),
    }


def refresh_stale_proposal_quotes(*, limit: int = 25) -> dict[str, Any]:
    """Refresh live quotes for active proposals before revalidation (no orders)."""
    props = _rows(
        """SELECT id, symbol FROM paper_trade_proposals
           WHERE status IN ('PENDING', 'APPROVED_FOR_PAPER_TEST', 'APPROVED')
           ORDER BY updated_at ASC NULLS FIRST LIMIT %s""",
        [limit],
    )
    refreshed, errors = 0, []
    for p in props:
        try:
            from market_quote_provider import check_fresh_quote
            fq = check_fresh_quote(p["symbol"])
            if fq.get("ok") and fq.get("last_price"):
                conn = _conn()
                cur = conn.cursor()
                cur.execute(
                    """UPDATE paper_trade_proposals
                       SET current_price=%s, last_price_source=%s, last_price_checked_at=NOW(), updated_at=NOW()
                       WHERE id=%s""",
                    (fq["last_price"], fq.get("provider") or "refresh", p["id"]),
                )
                conn.commit()
                refreshed += 1
        except Exception as e:
            errors.append(f"{p.get('symbol')}: {e}")
    return {"refreshed": refreshed, "checked": len(props), "errors": errors[:5]}