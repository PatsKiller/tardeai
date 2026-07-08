#!/usr/bin/env python3
"""broker_proposal_queue_ops.py — unified queue summary, resize-to-cap, bulk lifecycle actions."""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from typing import Any

ACTIVE = ("PENDING", "APPROVED_FOR_PAPER_TEST")
_QUEUE_SUMMARY_CACHE: tuple[float, dict] | None = None
_QUEUE_SUMMARY_TTL = float(os.getenv("BROKER_QUEUE_SUMMARY_TTL_SEC", "60"))


def _conn():
    from db_adapter import get_connection
    return get_connection()


def _active_where() -> str:
    return "status IN ('PENDING','APPROVED_FOR_PAPER_TEST')"


def compute_queue_summary(*, force: bool = False) -> dict:
    """Aggregate route-ready / blocked counts for the unified proposals queue."""
    global _QUEUE_SUMMARY_CACHE
    now = time.monotonic()
    if not force and _QUEUE_SUMMARY_CACHE and (now - _QUEUE_SUMMARY_CACHE[0]) < _QUEUE_SUMMARY_TTL:
        return dict(_QUEUE_SUMMARY_CACHE[1])

    conn = _conn()
    cur = conn.cursor()
    cur.execute(f"""
        SELECT id, symbol, status, strategy_id, proposed_shares, proposed_entry, proposed_stop,
               proposed_target1, target_account, proposed_account, proposed_rr,
               lifecycle_status, local_llm_review_status,
               llm_review_status, agent_review_status, intel_readiness
        FROM paper_trade_proposals
        WHERE {_active_where()}
    """)
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]

    pending_by_pid: dict[int, list[str]] = {}
    if rows:
        pids = [int(r["id"]) for r in rows]
        cur.execute("""
            SELECT proposal_id, agent_name FROM proposal_agent_reviews
            WHERE proposal_id = ANY(%s) AND status = 'pending'
        """, (pids,))
        for pid, agent in cur.fetchall():
            pending_by_pid.setdefault(int(pid), []).append(agent)

    route_ready = blocked = agent_pending = oversized = invalid_thesis = 0
    blocker_counts: dict[str, int] = {}
    agent_backlog: dict[str, int] = {}
    symbols: list[str] = []

    for r in rows:
        symbols.append(str(r.get("symbol") or ""))
        pid = int(r["id"])
        try:
            ev = _evaluate_row(r)
        except Exception:
            ev = {"route_ready": False, "blockers": ["evaluation_error"]}
        if ev.get("route_ready"):
            route_ready += 1
        else:
            blocked += 1
        for b in ev.get("blockers") or []:
            key = _blocker_category(b)
            blocker_counts[key] = blocker_counts.get(key, 0) + 1
        if ev.get("oversized"):
            oversized += 1
        if ev.get("invalid_thesis"):
            invalid_thesis += 1
        pending_agents = pending_by_pid.get(pid) or []
        if pending_agents:
            agent_pending += 1
            for a in pending_agents:
                agent_backlog[a] = agent_backlog.get(a, 0) + 1

    total = len(rows)
    result = {
        "ok": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total": total,
        "route_ready": route_ready,
        "blocked": blocked,
        "agent_pending": agent_pending,
        "oversized": oversized,
        "invalid_thesis": invalid_thesis,
        "blocker_counts": blocker_counts,
        "agent_backlog": agent_backlog,
        "symbols": sorted(set(s for s in symbols if s)),
        "route_ready_pct": round(100.0 * route_ready / total, 1) if total else 0.0,
    }
    _QUEUE_SUMMARY_CACHE = (now, result)
    return result


def _blocker_category(msg: str) -> str:
    m = str(msg or "").lower()
    if "sleeve" in m or "yaml" in m:
        return "strategy"
    if "trade plan" in m or "gambling" in m:
        return "trade_plan"
    if "oversight" in m or "block" in m or "agent" in m:
        return "oversight"
    if "cap" in m or "shares" in m or "risk" in m or "investment" in m:
        return "sizing"
    if "r:r" in m or "thesis" in m or "zone" in m or "drift" in m:
        return "thesis"
    return "other"


def _evaluate_row(row: dict) -> dict:
    import broker_promote_sizing as bps
    sym = str(row.get("symbol") or "").upper()
    shares = int(row.get("proposed_shares") or 0)
    acct = str(row.get("target_account") or row.get("proposed_account") or "")
    if not acct:
        return {"route_ready": False, "blockers": ["no destination account"], "oversized": False,
                "invalid_thesis": False, "policy_max_shares": None, "evaluation": {}}
    evaluation = bps.evaluate_broker_promote(
        acct,
        str(row.get("strategy_id") or "momentum_scalp"),
        float(row.get("proposed_entry") or 0),
        float(row.get("proposed_stop") or 0),
        float(row.get("proposed_target1") or 0),
        shares,
        operator_route=False,
        proposal_id=int(row["id"]),
    )
    blockers: list[str] = list(evaluation.get("violations") or [])
    gate = str(evaluation.get("status") or "")
    if gate == "BLOCK":
        blockers.append("Gate BLOCK")
    invalid = bool(evaluation.get("trade_plan", {}).get("allowed") is False) or any(
        "r:r" in str(v).lower() or "thesis" in str(v).lower() for v in blockers
    )
    if invalid:
        blockers.append("Thesis invalid or live R:R below minimum")
    policy_cap = evaluation.get("policy_max_shares")
    oversized = policy_cap is not None and shares > int(policy_cap or 0)
    route_ready = not blockers and not oversized and shares >= 1
    return {
        "route_ready": route_ready,
        "blockers": list(dict.fromkeys(blockers)),
        "oversized": oversized,
        "invalid_thesis": invalid,
        "policy_max_shares": policy_cap,
        "evaluation": evaluation,
    }


def resize_to_policy_cap(proposal_id: int, *, operator: str = "operator") -> dict:
    """Set proposed_shares to policy_max_shares for a queue row."""
    conn = _conn()
    cur = conn.cursor()
    cur.execute(f"""
        SELECT id, symbol, proposed_shares, proposed_entry, proposed_stop, proposed_target1,
               target_account, proposed_account, strategy_id, status, lifecycle_status
        FROM paper_trade_proposals WHERE id=%s AND {_active_where()}
    """, (proposal_id,))
    row = cur.fetchone()
    if not row:
        return {"ok": False, "error": f"proposal #{proposal_id} not in active queue"}
    cols = [d[0] for d in cur.description]
    d = dict(zip(cols, row))
    ev = _evaluate_row(d)
    cap = ev.get("policy_max_shares")
    if cap is None:
        cap = (ev.get("evaluation") or {}).get("policy_max_shares")
    if not cap or int(cap) < 1:
        return {"ok": False, "error": "no policy cap available", "evaluation": ev.get("evaluation")}
    old = int(d.get("proposed_shares") or 0)
    new = int(cap)
    if new == old:
        return {"ok": True, "proposal_id": proposal_id, "symbol": d["symbol"], "shares": new, "note": "already at cap"}
    sym = d["symbol"]
    conn2 = _conn()
    cur2 = conn2.cursor()
    cur2.execute("""
        UPDATE paper_trade_proposals
        SET proposed_shares=%s, sizing_adjusted=TRUE, original_shares=COALESCE(original_shares, proposed_shares),
            adjusted_shares=%s, sizing_reason='resize_to_policy_cap', updated_at=NOW()
        WHERE id=%s
    """, (new, new, proposal_id))
    _log_event(cur2, proposal_id, sym, "resize_to_cap", f"{old}→{new} sh by {operator}")
    conn2.commit()
    return {"ok": True, "proposal_id": proposal_id, "symbol": d["symbol"], "old_shares": old, "shares": new}


def bulk_action(proposal_ids: list[int], action: str, *, reason: str = "", operator: str = "operator") -> dict:
    """reject | expire | resize_to_cap on multiple proposals."""
    action = str(action or "").lower().strip()
    if action not in ("reject", "expire", "resize_to_cap"):
        return {"ok": False, "error": f"unknown action {action}"}
    results = []
    for pid in proposal_ids:
        try:
            if action == "resize_to_cap":
                results.append(resize_to_policy_cap(int(pid), operator=operator))
            elif action == "reject":
                results.append(_reject_or_expire(int(pid), "REJECTED", reason or "operator_bulk_reject", operator))
            else:
                results.append(_reject_or_expire(int(pid), "EXPIRED", reason or "operator_bulk_expire", operator))
        except Exception as ex:
            results.append({"ok": False, "proposal_id": pid, "error": str(ex)[:120]})
    ok_n = sum(1 for r in results if r.get("ok"))
    return {"ok": ok_n > 0, "action": action, "succeeded": ok_n, "total": len(results), "results": results}


def _reject_or_expire(proposal_id: int, status: str, reason: str, operator: str) -> dict:
    conn = _conn()
    cur = conn.cursor()
    if status == "REJECTED":
        cur.execute("""
            UPDATE paper_trade_proposals
            SET status='REJECTED', rejected_at=NOW(), rejection_reason=%s, updated_at=NOW()
            WHERE id=%s AND status IN ('PENDING','APPROVED_FOR_PAPER_TEST')
            RETURNING symbol
        """, (reason, proposal_id))
    else:
        cur.execute("""
            UPDATE paper_trade_proposals
            SET status='EXPIRED', lifecycle_status='EXPIRED_MAX_WINDOW',
                expired_reason=%s, expired_at=NOW(), updated_at=NOW()
            WHERE id=%s AND status IN ('PENDING','APPROVED_FOR_PAPER_TEST')
            RETURNING symbol
        """, (reason, proposal_id))
    row = cur.fetchone()
    if not row:
        return {"ok": False, "proposal_id": proposal_id, "error": "not found or not active"}
    _log_event(cur, proposal_id, row[0], status.lower(), f"{reason} by {operator}")
    conn.commit()
    return {"ok": True, "proposal_id": proposal_id, "symbol": row[0], "status": status}


def reconcile_sleeve_strategies(*, dry_run: bool = False) -> dict:
    """Map watchlist sleeve labels to executable YAML strategy_ids."""
    import broker_strategy_resolver as bsr
    conn = _conn()
    cur = conn.cursor()
    cur.execute(f"""
        SELECT id, symbol, strategy_id, sizing_basis
        FROM paper_trade_proposals
        WHERE {_active_where()}
          AND lower(strategy_id) = ANY(%s)
    """, (list(bsr.WATCHLIST_SLEEVES),))
    cols = [d[0] for d in cur.description]
    updated = []
    for row in cur.fetchall():
        d = dict(zip(cols, row))
        sym = str(d["symbol"]).upper()
        sleeve = str(d["strategy_id"])
        resolved = bsr.resolve_executable_strategy(sym, sleeve)
        new_sid = resolved["strategy_id"]
        if not new_sid or new_sid == sleeve:
            mapped = bsr.SLEEVE_TO_STRATEGY.get(sleeve)
            if mapped and mapped != sleeve:
                new_sid = mapped
            else:
                continue
        updated.append({"id": d["id"], "symbol": sym, "from": sleeve, "to": new_sid})
        if dry_run:
            continue
        basis = d.get("sizing_basis") or {}
        if isinstance(basis, str):
            try:
                basis = json.loads(basis)
            except Exception:
                basis = {}
        if not isinstance(basis, dict):
            basis = {}
        basis.update({
            "watchlist_sleeve": sleeve,
            "strategy_resolve_source": resolved.get("resolve_source"),
            "strategy_reconciled_at": datetime.now(timezone.utc).isoformat(),
        })
        cur.execute("""
            UPDATE paper_trade_proposals
            SET strategy_id=%s,
                sizing_basis=COALESCE(sizing_basis, '{}'::jsonb) || %s::jsonb,
                updated_at=NOW()
            WHERE id=%s
        """, (new_sid, json.dumps(basis), int(d["id"])))
        _log_event(cur, int(d["id"]), sym, "strategy_reconciled", f"{sleeve}→{new_sid}")
    if not dry_run:
        conn.commit()
    return {"ok": True, "dry_run": dry_run, "updated": len(updated), "details": updated}


def lifecycle_events(proposal_id: int, limit: int = 20) -> list[dict]:
    conn = _conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, event_type, lifecycle_status, message, created_at
        FROM proposal_lifecycle_events
        WHERE proposal_id=%s
        ORDER BY created_at DESC
        LIMIT %s
    """, (proposal_id, int(limit)))
    cols = [d[0] for d in cur.description]
    return [{k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in zip(cols, r)}
            for r in cur.fetchall()]


def _log_event(cur, proposal_id: int, symbol: str, event_type: str, message: str) -> None:
    try:
        cur.execute("""
            INSERT INTO proposal_lifecycle_events (proposal_id, symbol, event_type, message, lifecycle_status)
            VALUES (%s,%s,%s,%s,%s)
        """, (proposal_id, symbol, event_type, message[:500], event_type))
    except Exception:
        pass


def mature_llm_stage_2b(proposal_ids: list[int] | None = None) -> dict:
    """Run local LLM review through decision chunk (stage 2) for pending proposals."""
    conn = _conn()
    cur = conn.cursor()
    if proposal_ids:
        cur.execute(f"""
            SELECT id FROM paper_trade_proposals
            WHERE id = ANY(%s) AND {_active_where()}
        """, (proposal_ids,))
    else:
        cur.execute(f"""
            SELECT id FROM paper_trade_proposals
            WHERE {_active_where()}
              AND COALESCE(llm_review_stage,'') NOT IN ('decision','risk','catalyst')
        """)
    ids = [int(r[0]) for r in cur.fetchall()]
    ran = []
    for pid in ids[:15]:
        try:
            from proposal_llm_reviewer import review_proposal
            out = review_proposal(conn, pid)
            stage = out.get("llm_review_stage") if isinstance(out, dict) else None
            ran.append({"proposal_id": pid, "ok": bool(out), "stage": stage})
        except Exception as ex:
            ran.append({"proposal_id": pid, "ok": False, "error": str(ex)[:120]})
    return {"ok": True, "reviewed": len(ran), "results": ran}