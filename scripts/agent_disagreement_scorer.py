#!/usr/bin/env python3
"""agent_disagreement_scorer.py — Score agent disagreement outcomes.

Usage:
    .venv/bin/python scripts/agent_disagreement_scorer.py --dry-run --json
    .venv/bin/python scripts/agent_disagreement_scorer.py --apply --json
"""
import argparse, json, os, sys, uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

def _f(v): return float(v) if isinstance(v, Decimal) else v
def _uid(): return f"DIS_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"

def _get_conn():
    from session13_db import get_conn
    return get_conn()


def find_disagreements(conn):
    """Find cases where agents disagreed on the same symbol."""
    cur = conn.cursor()
    # Look for same symbol with different recommendations from different agents
    cur.execute("""
        SELECT symbol, array_agg(DISTINCT agent_name) as agents,
               array_agg(DISTINCT recommendation_type) as rec_types,
               MIN(recommendation_time) as first_time,
               MAX(recommendation_time) as last_time,
               COUNT(*) as rec_count
        FROM agent_recommendation_registry
        WHERE recommendation_time > now() - interval '90 days'
        AND symbol IS NOT NULL
        GROUP BY symbol
        HAVING COUNT(DISTINCT recommendation_type) > 1
        AND COUNT(DISTINCT agent_name) > 1
        ORDER BY rec_count DESC LIMIT 100
    """)

    disagreements = []
    for row in cur.fetchall():
        symbol, agents, rec_types, first_time, last_time, count = row

        # Classify disagreement type
        types_set = set(rec_types)
        if "buy" in types_set and "sell" in types_set:
            dtype = "buy_vs_sell"
        elif "buy" in types_set and ("wait" in types_set or "avoid" in types_set):
            dtype = "buy_vs_wait"
        elif "hold" in types_set and "trim" in types_set:
            dtype = "hold_vs_trim"
        else:
            dtype = "mixed_views"

        # Check if we have a trade outcome for this symbol
        cur.execute("""
            SELECT status, pnl, r_multiple FROM paper_trades
            WHERE symbol=%s AND created_at > %s
            ORDER BY created_at DESC LIMIT 1
        """, [symbol, first_time])
        trade = cur.fetchone()

        resolved = False
        winning = None
        losing = None
        outcome_summary = "unresolved"

        if trade and trade[0] == "closed":
            resolved = True
            pnl = _f(trade[1])
            if pnl and pnl > 0:
                winning = "bullish_view"
                losing = "bearish_view"
                outcome_summary = f"trade profitable pnl={pnl:.2f}"
            elif pnl and pnl < 0:
                winning = "bearish_view"
                losing = "bullish_view"
                outcome_summary = f"trade lost pnl={pnl:.2f}"
            else:
                outcome_summary = "trade breakeven"

        disagreements.append({
            "disagreement_id": _uid(),
            "symbol": symbol,
            "agents_involved": agents,
            "disagreement_type": dtype,
            "winning_view": winning,
            "losing_view": losing,
            "outcome_summary": outcome_summary,
            "outcome_score": {"agents": agents, "rec_types": rec_types, "count": count},
            "resolved": resolved,
            "resolved_at": str(datetime.now(timezone.utc)) if resolved else None,
        })

    return disagreements


def save_disagreements(conn, disagreements, dry_run=True):
    if dry_run:
        return
    cur = conn.cursor()
    for d in disagreements:
        cur.execute("""
            INSERT INTO agent_disagreement_outcomes
                (disagreement_id, symbol, agents_involved, disagreement_type,
                 winning_view, losing_view, outcome_summary, outcome_score,
                 resolved, resolved_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (disagreement_id) DO NOTHING
        """, [d["disagreement_id"], d["symbol"],
              json.dumps(d["agents_involved"], default=str),
              d["disagreement_type"], d.get("winning_view"), d.get("losing_view"),
              d["outcome_summary"],
              json.dumps(d["outcome_score"], default=str),
              d["resolved"], d.get("resolved_at")])
    conn.commit()


def main():
    parser = argparse.ArgumentParser(description="Agent Disagreement Scorer")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    dry_run = not args.apply
    conn = _get_conn()
    try:
        disagreements = find_disagreements(conn)

        if not dry_run:
            save_disagreements(conn, disagreements)

        resolved = sum(1 for d in disagreements if d["resolved"])
        out = {
            "mode": "dry_run" if dry_run else "applied",
            "disagreements_found": len(disagreements),
            "resolved": resolved,
            "unresolved": len(disagreements) - resolved,
            "by_type": {},
        }
        for d in disagreements:
            out["by_type"][d["disagreement_type"]] = out["by_type"].get(d["disagreement_type"], 0) + 1

        if args.json:
            print(json.dumps(out, indent=2, default=str))
        else:
            print(f"Disagreements: {out['disagreements_found']} found, {resolved} resolved ({out['mode']})")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
