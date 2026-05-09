#!/usr/bin/env python3
"""agent_recommendation_normalizer.py — Normalize agent recommendations into registry.

Extracts recommendations from watchlist_agent_results, cio_decisions, agent_debate_log,
and other agent output tables into a unified agent_recommendation_registry.

Usage:
    .venv/bin/python scripts/agent_recommendation_normalizer.py --dry-run --json
    .venv/bin/python scripts/agent_recommendation_normalizer.py --apply --json
    .venv/bin/python scripts/agent_recommendation_normalizer.py --agent Maria --dry-run --json
"""
import argparse, json, os, sys, uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

SECRET_KEYS = {"password", "token", "secret", "api_key", "cookie", "credential", "private_key"}

def _f(v):
    return float(v) if isinstance(v, Decimal) else v

def _get_conn():
    from session13_db import get_conn
    return get_conn()

def _uid():
    return f"AREC_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"

def _redact(payload):
    if not isinstance(payload, dict):
        return payload
    return {k: "***" if any(s in k.lower() for s in SECRET_KEYS) else v
            for k, v in payload.items()}

def _confidence_bucket(conf):
    if conf is None:
        return "unknown"
    c = float(conf)
    if c >= 0.8: return "very_high"
    if c >= 0.6: return "high"
    if c >= 0.4: return "medium"
    return "low"

def _map_recommendation(rec_text):
    if not rec_text:
        return "hold", "hold"
    r = rec_text.upper().strip()
    mapping = {
        "BUY": ("buy", "buy"), "STRONG BUY": ("buy", "buy"),
        "SELL": ("sell", "sell"), "STRONG SELL": ("sell", "sell"),
        "HOLD": ("hold", "hold"), "MAINTAIN": ("hold", "hold"),
        "TRIM": ("trim", "trim"), "ADD": ("add", "add"),
        "AVOID": ("avoid", "avoid"), "WAIT": ("wait", "wait"),
        "RESEARCH": ("research_more", "research_more"),
        "APPROVE": ("approve_trade", "approve_trade"),
        "REJECT": ("reject_trade", "reject_trade"),
    }
    for key, val in mapping.items():
        if key in r:
            return val
    return "hold", rec_text.lower()[:50]


def normalize_watchlist_results(conn, agent_filter=None, symbol_filter=None):
    """Extract from watchlist_agent_results."""
    cur = conn.cursor()
    sql = "SELECT id, agent, symbol, recommendation, confidence, created_at FROM watchlist_agent_results WHERE 1=1"
    params = []
    if agent_filter:
        sql += " AND agent ILIKE %s"
        params.append(f"%{agent_filter}%")
    if symbol_filter:
        sql += " AND symbol = %s"
        params.append(symbol_filter)
    sql += " ORDER BY created_at DESC LIMIT 5000"
    cur.execute(sql, params)

    recs = []
    for row in cur.fetchall():
        rec_type, rec_action = _map_recommendation(row[3])
        recs.append({
            "recommendation_id": _uid(),
            "agent_name": row[1] or "unknown",
            "agent_role": "watchlist_analyst",
            "source_table": "watchlist_agent_results",
            "source_id": str(row[0]),
            "symbol": row[2],
            "strategy_id": None,
            "recommendation_type": rec_type,
            "recommendation_action": rec_action,
            "confidence": _f(row[4]),
            "confidence_bucket": _confidence_bucket(row[4]),
            "time_horizon": "swing",
            "recommendation_time": row[5],
        })
    return recs


def normalize_cio_decisions(conn, agent_filter=None, symbol_filter=None):
    """Extract from cio_decisions."""
    cur = conn.cursor()
    sql = "SELECT decision_id, symbol, action, confidence_raw, agent_votes, created_at FROM cio_decisions WHERE 1=1"
    params = []
    if symbol_filter:
        sql += " AND symbol = %s"
        params.append(symbol_filter)
    sql += " ORDER BY created_at DESC LIMIT 1000"
    cur.execute(sql, params)

    recs = []
    for row in cur.fetchall():
        if agent_filter:
            continue  # CIO decisions are system-level
        rec_type, rec_action = _map_recommendation(row[2])
        recs.append({
            "recommendation_id": _uid(),
            "agent_name": "cio_engine",
            "agent_role": "decision_maker",
            "source_table": "cio_decisions",
            "source_id": str(row[0]),
            "symbol": row[1],
            "recommendation_type": rec_type,
            "recommendation_action": rec_action,
            "confidence": _f(row[3]),
            "confidence_bucket": _confidence_bucket(row[3]),
            "time_horizon": "swing",
            "recommendation_time": row[5],
        })
    return recs


def normalize_debates(conn, agent_filter=None, symbol_filter=None):
    """Extract from agent_debate_log."""
    cur = conn.cursor()
    sql = "SELECT id, symbol, participants, consensus_recommendation, consensus_score, created_at FROM agent_debate_log WHERE 1=1"
    params = []
    if symbol_filter:
        sql += " AND symbol = %s"
        params.append(symbol_filter)
    sql += " ORDER BY created_at DESC LIMIT 500"
    cur.execute(sql, params)

    recs = []
    for row in cur.fetchall():
        participants = row[2] or []
        if agent_filter and not any(agent_filter.lower() in (p or "").lower() for p in participants):
            continue
        rec_type, rec_action = _map_recommendation(row[3])
        agent_name = ", ".join(participants[:3]) if participants else "debate_group"
        recs.append({
            "recommendation_id": _uid(),
            "agent_name": agent_name,
            "agent_role": "debate_consensus",
            "source_table": "agent_debate_log",
            "source_id": str(row[0]),
            "symbol": row[1],
            "recommendation_type": rec_type,
            "recommendation_action": rec_action,
            "confidence": _f(row[4]),
            "confidence_bucket": _confidence_bucket(row[4]),
            "time_horizon": "swing",
            "recommendation_time": row[5],
        })
    return recs


def save_recommendations(conn, recs, dry_run=True):
    """Upsert into agent_recommendation_registry."""
    if dry_run:
        return len(recs)
    cur = conn.cursor()
    inserted = 0
    for r in recs:
        cur.execute("""
            INSERT INTO agent_recommendation_registry
                (recommendation_id, agent_name, agent_role, source_table, source_id,
                 symbol, strategy_id, recommendation_type, recommendation_action,
                 confidence, confidence_bucket, time_horizon, recommendation_time)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (recommendation_id) DO NOTHING
        """, [r["recommendation_id"], r["agent_name"], r["agent_role"],
              r["source_table"], r["source_id"], r["symbol"], r.get("strategy_id"),
              r["recommendation_type"], r["recommendation_action"],
              r.get("confidence"), r.get("confidence_bucket"),
              r.get("time_horizon"), r.get("recommendation_time")])
        inserted += cur.rowcount
    conn.commit()
    return inserted


def main():
    parser = argparse.ArgumentParser(description="Agent Recommendation Normalizer")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--agent", help="Filter by agent name")
    parser.add_argument("--symbol", help="Filter by symbol")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    dry_run = not args.apply
    conn = _get_conn()
    try:
        all_recs = []
        all_recs.extend(normalize_watchlist_results(conn, args.agent, args.symbol))
        all_recs.extend(normalize_cio_decisions(conn, args.agent, args.symbol))
        all_recs.extend(normalize_debates(conn, args.agent, args.symbol))

        # Dedup by source_table+source_id
        seen = set()
        unique = []
        for r in all_recs:
            key = f"{r['source_table']}:{r['source_id']}:{r['agent_name']}"
            if key not in seen:
                seen.add(key)
                unique.append(r)

        count = save_recommendations(conn, unique, dry_run=dry_run)

        by_agent = {}
        for r in unique:
            by_agent[r["agent_name"]] = by_agent.get(r["agent_name"], 0) + 1

        out = {
            "mode": "dry_run" if dry_run else "applied",
            "total_extracted": len(unique),
            "inserted": count if not dry_run else 0,
            "by_agent": by_agent,
            "sources": {"watchlist": sum(1 for r in unique if r["source_table"] == "watchlist_agent_results"),
                        "cio": sum(1 for r in unique if r["source_table"] == "cio_decisions"),
                        "debate": sum(1 for r in unique if r["source_table"] == "agent_debate_log")},
        }
        if args.json:
            print(json.dumps(out, indent=2, default=str))
        else:
            print(f"Normalizer: {out['total_extracted']} recommendations ({out['mode']})")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
