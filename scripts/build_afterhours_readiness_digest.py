#!/usr/bin/env python3
"""build_afterhours_readiness_digest.py — Build after-hours readiness digest message.

Reads from afterhours_readiness_run and afterhours_candidate_snapshot tables.
Builds digest text. Does not send.
No trades. No orders.

Usage:
    .venv/bin/python scripts/build_afterhours_readiness_digest.py --date 2026-05-19 --verbose
"""
import argparse, json, sys
from datetime import datetime, date, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))


def _q(conn, sql, params=None, fetch="all"):
    cur = conn.cursor()
    cur.execute(sql, params or [])
    if fetch == "one":
        row = cur.fetchone()
        return dict(zip([d[0] for d in cur.description], row)) if row else {}
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in rows]


def main():
    p = argparse.ArgumentParser(description="Build after-hours readiness digest")
    p.add_argument("--date", type=str, default="today")
    p.add_argument("--dry-run", action="store_true", default=True)
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    run_date = date.today().isoformat() if args.date == "today" else args.date

    from db_adapter import _get_conn
    conn = _get_conn()
    if not conn:
        print("ERROR: no DB connection"); sys.exit(1)

    # Get latest run for date
    run_row = _q(conn, """
        SELECT run_id, run_date, session, symbols_considered,
               strategy_fit_evaluated, ready_for_review,
               proposal_candidate_pending, needs_data, blocked, no_fit,
               run_status, underfilled_reason
        FROM afterhours_readiness_run
        WHERE run_date = %s
        ORDER BY started_at DESC
        LIMIT 1
    """, [run_date], fetch="one")

    if not run_row or not run_row.get("run_id"):
        print(f"No afterhours readiness run found for {run_date}")
        conn.close()
        sys.exit(0)

    snapshot_id = run_row["run_id"]
    symbols_considered = run_row.get("symbols_considered", 0)
    ready = run_row.get("ready_for_review", 0)
    pending = run_row.get("proposal_candidate_pending", 0)
    needs = run_row.get("needs_data", 0)
    blocked = run_row.get("blocked", 0)

    # Get readiness breakdown
    breakdown = _q(conn, """
        SELECT readiness_status, COUNT(*) AS cnt
        FROM afterhours_candidate_snapshot
        WHERE snapshot_id = %s
        GROUP BY readiness_status
        ORDER BY cnt DESC
    """, [snapshot_id])

    # Get top 3 ready-for-review candidates
    top_candidates = _q(conn, """
        SELECT symbol, top_strategy, top_strategy_score
        FROM afterhours_candidate_snapshot
        WHERE snapshot_id = %s AND readiness_status = 'ready_for_review'
        ORDER BY top_strategy_score DESC
        LIMIT 3
    """, [snapshot_id])

    conn.close()

    # Build digest message
    lines = [
        f"After-Hours Readiness -- {run_date}",
        f"Screeners: {symbols_considered} symbols",
        f"Ready: {ready} | Pending check: {pending} | Needs data: {needs} | Blocked: {blocked}",
        "",
    ]

    if top_candidates:
        lines.append("Top candidates:")
        for i, tc in enumerate(top_candidates, 1):
            sym = tc["symbol"]
            strat = tc.get("top_strategy") or "unknown"
            score = tc.get("top_strategy_score", 0)
            lines.append(f"{i}. {sym} -- {strat} ({score})")
        lines.append("")

    lines.append("Why no executable proposals:")
    lines.append("After-hours candidates require market-open execution check before approval.")
    lines.append("")
    lines.append("Review: Paper Proposals")

    digest = "\n".join(lines)

    if args.verbose:
        print(digest)
        if breakdown:
            print(f"\nReadiness breakdown:")
            for row in breakdown:
                print(f"  {row['readiness_status']}: {row['cnt']}")

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_date": run_date,
        "snapshot_id": snapshot_id,
        "symbols_considered": symbols_considered,
        "ready_for_review": ready,
        "proposal_candidate_pending": pending,
        "needs_data": needs,
        "blocked": blocked,
        "top_candidates": [
            {"symbol": tc["symbol"], "strategy": tc.get("top_strategy"),
             "score": tc.get("top_strategy_score", 0)}
            for tc in top_candidates
        ],
        "breakdown": {row["readiness_status"]: row["cnt"] for row in breakdown} if breakdown else {},
        "digest": digest,
    }

    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))

    if args.output_md:
        Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_md).write_text(digest)


if __name__ == "__main__":
    main()
