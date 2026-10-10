#!/usr/bin/env python3
"""agent_outcome_linker.py — Link agent recommendations to measurable outcomes.

Usage:
    .venv/bin/python scripts/agent_outcome_linker.py --dry-run --json
    .venv/bin/python scripts/agent_outcome_linker.py --apply --json

Without --apply, or with --dry-run (which wins over --apply), the run is a preview: the session is READ ONLY
at the server and save_links() is never called. An --apply run writes the lane receipt
<state_root>/data/runtime/agent-outcome-linker_last.json (ok_at only on success).
"""
import argparse, json, os, sys, uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

def _f(v): return float(v) if isinstance(v, Decimal) else v
def _uid(): return f"LNK_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"

LANE_ID = "agent-outcome-linker"
#: SELECT caps in link_to_proposals / link_to_trades. A run that fills a cap may have left links behind.
PROPOSAL_LINK_LIMIT = 1000
TRADE_LINK_LIMIT = 500


def _get_conn():
    from session13_db import get_conn
    return get_conn()


def _receipt_lib():
    try:
        from lib import lane_last_receipt as lr
    except ImportError:  # imported as scripts.agent_outcome_linker
        from scripts.lib import lane_last_receipt as lr
    return lr


def _dry_report(lane_id, summary, *, would_write, json_stdout=False):
    """lane_last_receipt.dry_run_report, sent to stderr when stdout carries the script's JSON report."""
    import contextlib
    with contextlib.redirect_stdout(sys.stderr) if json_stdout else contextlib.nullcontext():
        return _receipt_lib().dry_run_report(lane_id, summary, would_write=would_write)


def link_to_proposals(conn):
    """Link recommendations to paper_trade_proposals by symbol+time."""
    cur = conn.cursor()
    cur.execute("""
        SELECT r.recommendation_id, r.symbol, r.recommendation_time, r.agent_name,
               p.id as proposal_id, p.strategy_id, p.created_at as proposal_created
        FROM agent_recommendation_registry r
        JOIN paper_trade_proposals p ON r.symbol = p.symbol
        WHERE r.recommendation_time IS NOT NULL
        AND p.created_at > r.recommendation_time
        AND p.created_at < r.recommendation_time + interval '7 days'
        AND NOT EXISTS (
            SELECT 1 FROM agent_recommendation_outcome_links l
            WHERE l.recommendation_id = r.recommendation_id AND l.proposal_id = p.id
        )
        ORDER BY r.recommendation_time DESC LIMIT %s
    """, (PROPOSAL_LINK_LIMIT,))
    links = []
    for row in cur.fetchall():
        links.append({
            "link_id": _uid(),
            "recommendation_id": row[0],
            "outcome_table": "paper_trade_proposals",
            "outcome_id": str(row[4]),
            "proposal_id": row[4],
            "symbol": row[1],
            "strategy_id": row[5],
            "outcome_type": "proposal_result",
            "link_confidence": 0.7,
            "link_reason": f"Same symbol {row[1]}, proposal within 7d of recommendation",
        })
    return links


def link_to_trades(conn):
    """Link recommendations to paper_trades by symbol+time."""
    cur = conn.cursor()
    cur.execute("""
        SELECT r.recommendation_id, r.symbol, r.recommendation_time, r.agent_name,
               pt.id as trade_id, pt.strategy_id, pt.created_at as trade_created,
               pt.status, pt.pnl, pt.r_multiple
        FROM agent_recommendation_registry r
        JOIN paper_trades pt ON r.symbol = pt.symbol
        WHERE r.recommendation_time IS NOT NULL
        AND pt.created_at > r.recommendation_time
        AND pt.created_at < r.recommendation_time + interval '14 days'
        AND NOT EXISTS (
            SELECT 1 FROM agent_recommendation_outcome_links l
            WHERE l.recommendation_id = r.recommendation_id AND l.paper_trade_id = pt.id
        )
        ORDER BY r.recommendation_time DESC LIMIT %s
    """, (TRADE_LINK_LIMIT,))
    links = []
    for row in cur.fetchall():
        links.append({
            "link_id": _uid(),
            "recommendation_id": row[0],
            "outcome_table": "paper_trades",
            "outcome_id": str(row[4]),
            "paper_trade_id": row[4],
            "symbol": row[1],
            "strategy_id": row[5],
            "outcome_type": "paper_trade",
            "link_confidence": 0.8,
            "link_reason": f"Same symbol {row[1]}, trade within 14d, status={row[7]}",
        })
    return links


def save_links(conn, links, dry_run=True):
    if dry_run:
        return len(links)
    cur = conn.cursor()
    inserted = 0
    for lnk in links:
        cur.execute("""
            INSERT INTO agent_recommendation_outcome_links
                (link_id, recommendation_id, outcome_table, outcome_id,
                 paper_trade_id, proposal_id, symbol, strategy_id,
                 outcome_type, link_confidence, link_reason)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (link_id) DO NOTHING
        """, [lnk["link_id"], lnk["recommendation_id"], lnk["outcome_table"],
              lnk.get("outcome_id"), lnk.get("paper_trade_id"), lnk.get("proposal_id"),
              lnk["symbol"], lnk.get("strategy_id"), lnk["outcome_type"],
              lnk["link_confidence"], lnk["link_reason"]])
        inserted += cur.rowcount
    conn.commit()
    return inserted


def main():
    parser = argparse.ArgumentParser(description="Agent Outcome Linker")
    parser.add_argument("--dry-run", action="store_true", help="preview only; wins over --apply")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--agent", help="Filter by agent")
    parser.add_argument("--symbol", help="Filter by symbol")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    dry_run = args.dry_run or not args.apply
    started = datetime.now(timezone.utc).isoformat()
    out: dict = {"mode": "dry_run" if dry_run else "applied"}
    try:
        conn = _get_conn()
        if dry_run:
            _receipt_lib().enforce_readonly(conn)
        try:
            proposal_links = link_to_proposals(conn)
            trade_links = link_to_trades(conn)
            all_links = proposal_links + trade_links
            by_type = {}
            for lnk in all_links:
                by_type[lnk["outcome_type"]] = by_type.get(lnk["outcome_type"], 0) + 1
            out.update({
                "total_links": len(all_links),
                "by_outcome_type": by_type,
                # a full page means the SELECT cap, not the backlog, decided this run's size
                "proposal_cap_hit": len(proposal_links) >= PROPOSAL_LINK_LIMIT,
                "trade_cap_hit": len(trade_links) >= TRADE_LINK_LIMIT,
            })
            if dry_run:
                # Structural (AGENTS.md §6): save_links is not reachable from this branch.
                out["inserted"] = 0
                out["would_insert"] = len(all_links)
            else:
                out["inserted"] = save_links(conn, all_links, dry_run=False)
        finally:
            conn.close()
    except Exception as exc:
        if not dry_run:
            _receipt_lib().write_lane_receipt(LANE_ID, ok=False, exit_code=1, started_at=started,
                                              script="agent_outcome_linker.py", summary=out,
                                              error=f"{type(exc).__name__}: {exc}")
        raise

    if args.json:
        print(json.dumps(out, indent=2, default=str))
    else:
        print(f"Linker: {out['total_links']} links ({out['mode']})"
              + (" [cap hit: backlog may exceed one run]" if out["proposal_cap_hit"] or out["trade_cap_hit"] else ""))
    if dry_run:
        _dry_report(LANE_ID, out, would_write=["agent_recommendation_outcome_links"],
            json_stdout=args.json)
    else:
        _receipt_lib().write_lane_receipt(LANE_ID, ok=True, exit_code=0, started_at=started,
                                          script="agent_outcome_linker.py", summary=out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
