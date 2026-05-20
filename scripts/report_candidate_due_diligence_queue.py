#!/usr/bin/env python3
"""
report_candidate_due_diligence_queue.py
Candidate Due Diligence Queue Report

Queries afterhours_candidate_snapshot for ready/watchpool/pending candidates,
joins with trade_ai_scans for enrichment data, ranks by strategy score and rvol,
and recommends next actions.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))

from dotenv import load_dotenv
load_dotenv(PROJ / ".env")

from db_adapter import _get_conn

NOW = datetime.now()

ELIGIBLE_STATUSES = (
    "ready_for_review",
    "watchpool_candidate",
    "proposal_candidate_pending_market_open_check",
)


def _q(sql: str, params=None) -> list[dict]:
    """Execute a query and return list of dicts."""
    conn = _get_conn()
    if not conn:
        return []
    try:
        import psycopg2.extras
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
            conn.commit()
            return [dict(r) for r in rows]
    except Exception as e:
        conn.rollback()
        print(f"  [dd-queue] SQL error: {e}")
        return []


def build_queue(window: str | None, limit: int = 50, verbose: bool = False) -> dict:
    """Build the due diligence queue."""
    status_placeholders = ",".join(["%s"] * len(ELIGIBLE_STATUSES))

    # Get latest candidates
    candidates = _q(
        f"SELECT a.symbol, a.readiness_status, a.top_strategy, a.top_strategy_score, "
        f"a.catalog_status, a.quote_status, a.session, a.source_screeners, "
        f"a.blockers, a.next_required_action, a.proposal_candidate_allowed, "
        f"a.executable_now, a.human_review_only, a.run_date "
        f"FROM afterhours_candidate_snapshot a "
        f"WHERE a.run_date = (SELECT MAX(run_date) FROM afterhours_candidate_snapshot) "
        f"AND a.readiness_status IN ({status_placeholders}) "
        f"ORDER BY a.top_strategy_score DESC NULLS LAST "
        f"LIMIT %s",
        (*ELIGIBLE_STATUSES, limit * 2)  # fetch extra for enrichment join
    )

    if not candidates:
        return {
            "report": "Candidate Due Diligence Queue",
            "generated_at": NOW.isoformat(),
            "window": window,
            "total_candidates": 0,
            "queue": [],
        }

    # Get latest scan data for these symbols
    symbols = [c["symbol"] for c in candidates]
    scan_data: dict[str, dict] = {}
    if symbols:
        # Use DISTINCT ON to get latest scan per symbol
        placeholders = ",".join(["%s"] * len(symbols))
        scans = _q(
            f"SELECT DISTINCT ON (symbol) symbol, score, rvol, price, change_pct, "
            f"gap_pct, catalyst, scanned_at, grade, decision "
            f"FROM trade_ai_scans "
            f"WHERE symbol IN ({placeholders}) "
            f"ORDER BY symbol, scanned_at DESC",
            tuple(symbols)
        )
        scan_data = {s["symbol"]: s for s in scans}

    # Build queue entries with recommended actions
    queue = []
    for c in candidates:
        sym = c["symbol"]
        scan = scan_data.get(sym, {})

        rvol = float(scan.get("rvol") or 0)
        gap_pct = float(scan.get("gap_pct") or 0) if scan.get("gap_pct") is not None else None
        catalyst = scan.get("catalyst") or ""
        score = scan.get("score")
        scanned_at = scan.get("scanned_at")

        # Quote freshness
        quote_stale = True
        scan_age_hours = None
        if scanned_at:
            scan_age_hours = round(
                (NOW - scanned_at.replace(tzinfo=None)).total_seconds() / 3600, 1
            )
            quote_stale = scan_age_hours > 4  # >4h is stale for DD purposes

        # Determine recommended_action
        if not catalyst or catalyst.strip() == "":
            recommended_action = "review_catalyst"
        elif quote_stale:
            recommended_action = "refresh_quote"
        elif not scan:
            recommended_action = "check_technical"
        else:
            recommended_action = "ready_for_proposal"

        entry = {
            "symbol": sym,
            "top_strategy": c.get("top_strategy"),
            "score": c.get("top_strategy_score"),
            "rvol": round(rvol, 2) if rvol else None,
            "gap_pct": round(gap_pct, 2) if gap_pct is not None else None,
            "catalyst": catalyst[:100] if catalyst else None,
            "readiness_status": c.get("readiness_status"),
            "recommended_action": recommended_action,
        }

        if verbose:
            entry["scan_score"] = score
            entry["scan_grade"] = scan.get("grade")
            entry["scan_decision"] = scan.get("decision")
            entry["scan_age_hours"] = scan_age_hours
            entry["quote_status"] = c.get("quote_status")
            entry["blockers"] = c.get("blockers")
            entry["session"] = c.get("session")
            entry["run_date"] = str(c.get("run_date"))
            entry["proposal_candidate_allowed"] = c.get("proposal_candidate_allowed")

        queue.append(entry)

    # Sort by score DESC, then rvol DESC
    queue.sort(key=lambda x: (-(x.get("score") or 0), -(x.get("rvol") or 0)))
    queue = queue[:limit]

    # Action summary
    by_action: dict[str, int] = {}
    for q in queue:
        act = q["recommended_action"]
        by_action[act] = by_action.get(act, 0) + 1

    by_readiness: dict[str, int] = {}
    for q in queue:
        st = q.get("readiness_status") or "unknown"
        by_readiness[st] = by_readiness.get(st, 0) + 1

    return {
        "report": "Candidate Due Diligence Queue",
        "generated_at": NOW.isoformat(),
        "window": window,
        "total_candidates": len(queue),
        "by_recommended_action": by_action,
        "by_readiness_status": by_readiness,
        "ready_for_proposal_count": by_action.get("ready_for_proposal", 0),
        "needs_work_count": len(queue) - by_action.get("ready_for_proposal", 0),
        "queue": queue,
    }


def render_markdown(report: dict) -> str:
    """Render DD queue as markdown."""
    lines = [
        f"# {report['report']}",
        f"Generated: {report['generated_at']}",
        f"Window: {report.get('window') or 'all'}",
        "",
        f"**Total candidates:** {report['total_candidates']}",
        f"**Ready for proposal:** {report.get('ready_for_proposal_count', 0)}",
        f"**Needs work:** {report.get('needs_work_count', 0)}",
        "",
    ]

    if report.get("by_recommended_action"):
        lines.append("## Action Summary")
        for act, cnt in sorted(report["by_recommended_action"].items()):
            lines.append(f"- **{act}:** {cnt}")
        lines.append("")

    lines.append("## Queue")
    lines.append("")
    lines.append("| # | Symbol | Strategy | Score | RVOL | Gap% | Catalyst | Readiness | Action |")
    lines.append("|---|--------|----------|-------|------|------|----------|-----------|--------|")

    for i, q in enumerate(report.get("queue", [])[:50], 1):
        cat = (q.get("catalyst") or "-")[:40]
        gap = f"{q['gap_pct']:.1f}" if q.get("gap_pct") is not None else "-"
        rvol = f"{q['rvol']:.1f}" if q.get("rvol") else "-"
        score = q.get("score") or "-"
        lines.append(
            f"| {i} | {q['symbol']} | {q.get('top_strategy') or '-'} | "
            f"{score} | {rvol} | {gap} | {cat} | "
            f"{q.get('readiness_status', '-')} | {q['recommended_action']} |"
        )

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Candidate Due Diligence Queue Report")
    parser.add_argument("--window",
                        choices=["evening", "overnight", "premarket_4am", "premarket_7am", "premarket_9am"],
                        default=None,
                        help="Time window context (advisory label)")
    parser.add_argument("--limit", type=int, default=50,
                        help="Max candidates to return (default 50)")
    parser.add_argument("--output-json", type=str, help="Write JSON report to file")
    parser.add_argument("--output-md", type=str, help="Write Markdown report to file")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    print(f"[dd-queue] Building due diligence queue (window={args.window}, limit={args.limit}) ...")
    report = build_queue(window=args.window, limit=args.limit, verbose=args.verbose)

    # Console summary
    print(f"[dd-queue] Total candidates: {report['total_candidates']}")
    print(f"[dd-queue] Ready for proposal: {report.get('ready_for_proposal_count', 0)}")
    print(f"[dd-queue] Needs work: {report.get('needs_work_count', 0)}")
    if report.get("by_recommended_action"):
        for act, cnt in report["by_recommended_action"].items():
            print(f"  {act}: {cnt}")

    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
        print(f"[dd-queue] JSON written to {args.output_json}")

    if args.output_md:
        md = render_markdown(report)
        Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_md).write_text(md)
        print(f"[dd-queue] Markdown written to {args.output_md}")

    if not args.output_json and not args.output_md:
        print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
