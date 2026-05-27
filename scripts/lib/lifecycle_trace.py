"""lifecycle_trace.py — Utility for prospect→signal→proposal traceability."""
import hashlib, json
from datetime import datetime, timezone


STRATEGY_FAMILIES = {
    "momentum_scalp": "momentum", "gap_and_go": "momentum",
    "swing_breakout": "swing", "swing_trade": "swing", "earnings_catalyst": "swing",
    "earnings_pre_buildup": "swing", "earnings_post_momentum": "swing",
    "fib_retracement_bounce": "swing", "speculative_growth": "swing",
    "dividend_growth_compounder": "income", "reit_income": "income",
    "high_yield_income_bdc": "income", "bond_income": "income",
    "covered_call_income": "income", "income_add": "income",
    "international_dividend": "income",
    "core_growth_compounder": "position", "core_index": "position",
    "defense_thesis": "position", "tax_loss_harvest": "position",
    "sector_rotation": "position", "recovery_watch": "income",
    "cash_or_stable": "position",
}


def normalize_symbol(s):
    return (s or "").strip().upper()


def normalize_strategy(s):
    return (s or "").strip().lower().replace(" ", "_")


def make_trace_id(symbol, strategy_id, source_system="atm", source_id=None):
    sym = normalize_symbol(symbol)
    sid = normalize_strategy(strategy_id)
    key = f"{sym}|{sid}|{source_system}|{source_id or 'auto'}"
    return f"tr-{hashlib.sha256(key.encode()).hexdigest()[:16]}"


def safe_json(obj):
    try:
        return json.dumps(obj, default=str)
    except Exception:
        return "{}"


def find_or_create_trace(conn, symbol, strategy_id, source_stage, source_system="atm",
                         source_id=None, signal_id=None, proposal_id=None,
                         paper_trade_id=None, score=None, reason=None, dry_run=False):
    sym = normalize_symbol(symbol)
    sid = normalize_strategy(strategy_id)
    tid = make_trace_id(sym, sid, source_system, source_id)
    family = STRATEGY_FAMILIES.get(sid, "unknown")

    if dry_run:
        return tid, True

    cur = conn.cursor()
    cur.execute("SELECT trace_id FROM lifecycle_trace WHERE trace_id=%s", [tid])
    exists = cur.fetchone()
    if exists:
        # Update with more specific data if available
        updates = []
        params = []
        if signal_id:
            updates.append("signal_id=COALESCE(signal_id,%s)")
            params.append(signal_id)
        if proposal_id:
            updates.append("proposal_id=COALESCE(proposal_id,%s)")
            params.append(proposal_id)
        if paper_trade_id:
            updates.append("paper_trade_id=COALESCE(paper_trade_id,%s)")
            params.append(paper_trade_id)
        if updates:
            updates.append("updated_at=NOW()")
            updates.append("current_stage=%s")
            params.append(source_stage)
            params.append(tid)
            cur.execute(f"UPDATE lifecycle_trace SET {', '.join(updates)} WHERE trace_id=%s", params)
            conn.commit()
        return tid, False

    cur.execute("""INSERT INTO lifecycle_trace
        (trace_id, symbol, strategy_id, strategy_family, source_stage, current_stage,
         source_system, signal_id, proposal_id, paper_trade_id, score, reason)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        [tid, sym, sid, family, source_stage, source_stage,
         source_system, signal_id, proposal_id, paper_trade_id, score, reason])
    conn.commit()
    return tid, True


def append_trace_event(conn, trace_id, stage, event_type, source_script=None,
                       source_table=None, source_id=None, status=None, message=None,
                       payload=None, dry_run=False):
    if dry_run:
        return
    try:
        cur = conn.cursor()
        cur.execute("""INSERT INTO lifecycle_trace_events
            (trace_id, stage, event_type, source_script, source_table, source_id, status, message, payload)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            [trace_id, stage, event_type, source_script, source_table,
             source_id, status, message, safe_json(payload) if payload else None])
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass


def detect_duplicate_proposals(conn, dry_run=False):
    cur = conn.cursor()
    cur.execute("""
        SELECT symbol, strategy_id, count(*) as cnt,
               array_agg(id ORDER BY created_at) as ids
        FROM paper_trade_proposals
        WHERE signal_decision IS NULL OR signal_decision NOT IN ('expired_stale', 'rejected')
        GROUP BY symbol, strategy_id
        HAVING count(*) > 1
        ORDER BY count(*) DESC
    """)
    groups = []
    for row in cur.fetchall():
        sym, sid, cnt, ids = row
        key = f"{(sym or '').upper()}|{sid or ''}"
        canonical = ids[0] if ids else None
        dupes = ids[1:] if ids and len(ids) > 1 else []
        groups.append({
            "duplicate_key": key,
            "symbol": sym,
            "strategy_id": sid,
            "canonical_proposal_id": canonical,
            "duplicate_proposal_ids": dupes,
            "duplicate_count": cnt,
            "recommended_action": "Review: keep canonical, mark others as duplicate after operator approval",
        })
        if not dry_run:
            try:
                cur2 = conn.cursor()
                cur2.execute("""INSERT INTO proposal_dedup_audit
                    (duplicate_key, symbol, strategy_id, canonical_proposal_id,
                     duplicate_proposal_ids, duplicate_count, recommended_action)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT DO NOTHING""",
                    [key, sym, sid, str(canonical), json.dumps(dupes),
                     cnt, "Review: keep canonical, mark others as duplicate"])
                conn.commit()
            except Exception:
                try:
                    conn.rollback()
                except Exception:
                    pass
    return groups
