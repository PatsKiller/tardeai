#!/usr/bin/env python3
"""agent_outcome_linker.py — Link agent recommendations to measurable outcomes.

Usage:
    .venv/bin/python scripts/agent_outcome_linker.py --dry-run --json
    .venv/bin/python scripts/agent_outcome_linker.py --apply --json

Without --apply, or with --dry-run (which wins over --apply), the run is a preview: the session is READ ONLY
at the server and save_links() is never called. An --apply run writes the lane receipt
<state_root>/data/runtime/agent-outcome-linker_last.json (ok_at only on success).

An --apply run pages until the queue is drained or its budget is spent (--max-links / --max-seconds, default
20000 links / 100 s, inside the executor's 180 s), and records `drained`, `budget_exhausted`, `pages` and
`backlog_recommendations` so an OK receipt proves how much of the backlog is left (LQ-20261107-140).
"""
import argparse, json, os, sys, time, uuid
from collections import Counter
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
#: SELECT page sizes in link_to_proposals / link_to_trades. A page that comes back full means the run stopped
#: on its page size, not on the backlog — there is more to link.
PROPOSAL_LINK_LIMIT = 1000
TRADE_LINK_LIMIT = 500
#: A run no longer stops at the first full page (LQ-20261107-140). It repeated one page per day and hit the
#: 1500-link cap every single run, so the ~1.09M unlinked (recommendation, proposal) pairs behind the newest
#: 1500 could never drain — July alone holds 664k. The run now pages until both SELECTs come back short
#: (drained) or it spends its budget. The n8n executor kills this lane at 180 s
#: (config/n8n_run_allowlist.json: timeout_s 180), so the default budget stops well inside that: the run
#: always writes its own receipt and is never mistaken for a hang. Override with --max-links / --max-seconds.
MAX_LINKS_PER_RUN = 20000
MAX_SECONDS_PER_RUN = 100.0


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


def _page_totals(links):
    # Counter, not dict.get(k, 0): a tally that starts at zero is a count of links seen, not a data value
    # whose absence would be a wrong 0.
    return len(links), dict(Counter(lnk["outcome_type"] for lnk in links))


def _run_pages(conn, budget, clock=time.monotonic):
    """Apply pages until the queue is drained or the budget is spent (LQ-20261107-140).

    Each pass links one page per outcome table and commits it (save_links). The loop ends when both SELECTs
    come back short — that is the only honest "drained" — or when the link/time budget is gone, which the
    receipt records as budget_exhausted, so an OK run never claims it caught up when it did not.
    """
    started = clock()
    built = inserted = pages = 0
    by_type: Counter = Counter()
    proposal_full = trade_full = False
    drained = False
    while True:
        proposal_links = link_to_proposals(conn)
        trade_links = link_to_trades(conn)
        page = proposal_links + trade_links
        pages += 1
        if page:
            inserted += save_links(conn, page, dry_run=False)
            built += len(page)
            _, page_by_type = _page_totals(page)
            by_type.update(page_by_type)
        proposal_full = len(proposal_links) >= PROPOSAL_LINK_LIMIT
        trade_full = len(trade_links) >= TRADE_LINK_LIMIT
        if not (proposal_full or trade_full):
            drained = True
            break
        if built >= budget["max_links"] or (clock() - started) >= budget["max_seconds"]:
            break
    return {
        "total_links": built,
        "by_outcome_type": dict(by_type),
        "inserted": inserted,
        "pages": pages,
        "proposal_cap_hit": proposal_full,
        "trade_cap_hit": trade_full,
        "drained": drained,
        "budget_exhausted": not drained,
        "budget": budget,
    }


_BACKLOG_SQL = {
    # One row per recommendation that has a linkable outcome and no link to one. Counted per recommendation
    # (index-backed, ~0.5 s) rather than per candidate pair (1.09M rows, a full join re-scan), because the
    # number that matters for "is the backlog shrinking" is how many recommendations are still unlinked.
    "proposals": """
        SELECT count(*) FROM agent_recommendation_registry r
        WHERE r.recommendation_time IS NOT NULL
          AND EXISTS (SELECT 1 FROM paper_trade_proposals p
                      WHERE p.symbol = r.symbol
                        AND p.created_at > r.recommendation_time
                        AND p.created_at < r.recommendation_time + interval '7 days')
          AND NOT EXISTS (SELECT 1 FROM agent_recommendation_outcome_links l
                          WHERE l.recommendation_id = r.recommendation_id AND l.proposal_id IS NOT NULL)
    """,
    "trades": """
        SELECT count(*) FROM agent_recommendation_registry r
        WHERE r.recommendation_time IS NOT NULL
          AND EXISTS (SELECT 1 FROM paper_trades pt
                      WHERE pt.symbol = r.symbol
                        AND pt.created_at > r.recommendation_time
                        AND pt.created_at < r.recommendation_time + interval '14 days')
          AND NOT EXISTS (SELECT 1 FROM agent_recommendation_outcome_links l
                          WHERE l.recommendation_id = r.recommendation_id AND l.paper_trade_id IS NOT NULL)
    """,
}


def backlog_counts(conn):
    """Recommendations still waiting for a link, as {"proposals": n, "trades": n}.

    An unreadable count stays None — never 0 — so a receipt can say "backlog unknown" instead of a confident
    zero. A failed statement aborts the transaction, so the rollback below is part of the contract.
    """
    out = {}
    for key, sql in _BACKLOG_SQL.items():
        try:
            cur = conn.cursor()
            cur.execute(sql)
            row = cur.fetchone()
            out[key] = int(row[0]) if row and row[0] is not None else None
        except Exception as exc:
            # The count is unknown (recorded as None above), so nothing is hidden. A failed statement left the
            # transaction aborted; clearing it is what lets the rest of the run continue.
            out[key] = None
            try:
                conn.rollback()
            except Exception as rb_exc:
                print(f"backlog_counts: {key} count failed ({type(exc).__name__}) and the rollback failed too "
                      f"({type(rb_exc).__name__})", file=sys.stderr)
    return out


def main():
    parser = argparse.ArgumentParser(description="Agent Outcome Linker")
    parser.add_argument("--dry-run", action="store_true", help="preview only; wins over --apply")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--max-links", type=int, default=MAX_LINKS_PER_RUN,
                        help=f"stop a run after this many links (default {MAX_LINKS_PER_RUN})")
    parser.add_argument("--max-seconds", type=float, default=MAX_SECONDS_PER_RUN,
                        help=f"stop a run after this many seconds (default {MAX_SECONDS_PER_RUN}; "
                             "the n8n executor kills the lane at 180)")
    parser.add_argument("--agent", help="Filter by agent")
    parser.add_argument("--symbol", help="Filter by symbol")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    dry_run = args.dry_run or not args.apply
    budget = {"max_links": max(1, int(args.max_links)), "max_seconds": max(1.0, float(args.max_seconds))}
    started = datetime.now(timezone.utc).isoformat()
    out: dict = {"mode": "dry_run" if dry_run else "applied"}
    try:
        conn = _get_conn()
        if dry_run:
            _receipt_lib().enforce_readonly(conn)
        try:
            if dry_run:
                # A dry run may look at exactly one page: nothing is written, so a second page would return
                # the same rows forever. The backlog counts are what say how much a real run would face.
                proposal_links = link_to_proposals(conn)
                trade_links = link_to_trades(conn)
                all_links = proposal_links + trade_links
                total, by_type = _page_totals(all_links)
                out.update({
                    "total_links": total,
                    "by_outcome_type": by_type,
                    # a full page means the SELECT page size, not the backlog, decided this run's size
                    "proposal_cap_hit": len(proposal_links) >= PROPOSAL_LINK_LIMIT,
                    "trade_cap_hit": len(trade_links) >= TRADE_LINK_LIMIT,
                    "pages": 1,
                    "budget": budget,
                })
                # Structural (AGENTS.md §6): save_links is not reachable from this branch.
                out["inserted"] = 0
                out["would_insert"] = total
            else:
                out.update(_run_pages(conn, budget))
            out["backlog_recommendations"] = backlog_counts(conn)
        finally:
            conn.close()
    except Exception as exc:
        if not dry_run:
            _receipt_lib().write_lane_receipt(LANE_ID, ok=False, exit_code=1, started_at=started,
                                              script="agent_outcome_linker.py", summary=out,
                                              error=f"{type(exc).__name__}: {exc}",
                                              output={"produced_count": 0, "attempted_count": 0, "skipped_reasons": {"dependency_unavailable": 1}})
        raise

    if args.json:
        print(json.dumps(out, indent=2, default=str))
    else:
        backlog = out.get("backlog_recommendations") or {}
        backlog_txt = ", ".join(f"{k}={v if v is not None else 'unknown'}" for k, v in backlog.items()) or "unknown"
        print(f"Linker: {out['total_links']} links ({out['mode']})"
              + (" [page full: backlog exceeds this run]" if out["proposal_cap_hit"] or out["trade_cap_hit"] else "")
              + f" [unlinked recommendations: {backlog_txt}]")
    if dry_run:
        _dry_report(LANE_ID, out, would_write=["agent_recommendation_outcome_links"],
            json_stdout=args.json)
    else:
        _receipt_lib().write_lane_receipt(LANE_ID, ok=True, exit_code=0, started_at=started,
                                          script="agent_outcome_linker.py", summary=out, output=lane_output(out))
    return 0


def lane_output(out: dict) -> dict:
    """LaneRunReceipt@v2 output fields (n8n expected_output, unit: rows inserted into
    agent_recommendation_outcome_links). attempted = links built this run; a link not inserted hit ON CONFLICT."""
    inserted, built = int(out.get("inserted") or 0), int(out.get("total_links") or 0)
    return {
        "produced_count": inserted,
        "attempted_count": max(built, inserted),
        "skipped_reasons": {"already_linked": max(built - inserted, 0)},
        "empty_reason": "no_new_input" if inserted == 0 else None,
    }


if __name__ == "__main__":
    sys.exit(main())
