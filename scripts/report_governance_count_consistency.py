#!/usr/bin/env python3
"""report_governance_count_consistency.py — Cross-check trade counts vs scorecards.

Read-only. No trades, no orders, no mutations.

Queries:
  - paper_trades closed/open counts
  - paper_performance_governance strategy-level governance data
  - paper_strategy_scorecards strategy scorecard counts
  - Identifies mismatches where closed trades exist but scorecards show 0

Usage:
    .venv/bin/python scripts/report_governance_count_consistency.py --verbose
    .venv/bin/python scripts/report_governance_count_consistency.py --output-json /tmp/gov_consistency.json
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))
from db_adapter import _get_conn
from dotenv import load_dotenv
load_dotenv(PROJ / ".env")


def _safe_query(conn, sql, params=None):
    """Execute a read-only query, return result or None on error."""
    if conn is None:
        return None
    try:
        import psycopg2.extras
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return cur.fetchall()
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        return None


def _safe_query_one(conn, sql, params=None):
    rows = _safe_query(conn, sql, params)
    if rows:
        return rows[0]
    return None


def _table_exists(conn, table_name):
    row = _safe_query_one(
        conn,
        "SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name=%s",
        (table_name,),
    )
    return row is not None


def main():
    p = argparse.ArgumentParser(description="Governance count consistency check (read-only)")
    p.add_argument("--output-json", type=str, help="Write JSON report to this path")
    p.add_argument("--output-md", type=str, help="Write Markdown report to this path")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    now = datetime.now(timezone.utc)
    conn = _get_conn()
    if conn is None:
        print("ERROR: Could not connect to database.")
        sys.exit(1)

    # ── 1. Paper trades counts ──────────────────────────────────────────────
    closed_trades = 0
    open_trades = 0
    strategies_with_closed = {}
    strategies_with_open = {}

    if _table_exists(conn, "paper_trades"):
        row = _safe_query_one(conn, "SELECT count(*) AS cnt FROM paper_trades WHERE status='closed'")
        closed_trades = (row or {}).get("cnt", 0)

        row = _safe_query_one(conn, "SELECT count(*) AS cnt FROM paper_trades WHERE status='open'")
        open_trades = (row or {}).get("cnt", 0)

        # Closed trades by strategy
        rows = _safe_query(
            conn,
            """SELECT COALESCE(strategy_id, 'unassigned') AS strategy_id, count(*) AS cnt
               FROM paper_trades WHERE status='closed'
               GROUP BY strategy_id ORDER BY cnt DESC"""
        )
        if rows:
            for r in rows:
                strategies_with_closed[r["strategy_id"]] = r["cnt"]

        # Open trades by strategy
        rows = _safe_query(
            conn,
            """SELECT COALESCE(strategy_id, 'unassigned') AS strategy_id, count(*) AS cnt
               FROM paper_trades WHERE status='open'
               GROUP BY strategy_id ORDER BY cnt DESC"""
        )
        if rows:
            for r in rows:
                strategies_with_open[r["strategy_id"]] = r["cnt"]

    if args.verbose:
        print(f"Paper trades: {closed_trades} closed, {open_trades} open")
        print(f"  Closed by strategy: {strategies_with_closed}")
        print(f"  Open by strategy:   {strategies_with_open}")

    # ── 2. Governance data ──────────────────────────────────────────────────
    governance_rows = []
    governance_strategy_count = 0
    governance_total_closed = 0

    if _table_exists(conn, "paper_performance_governance"):
        rows = _safe_query(
            conn,
            """SELECT strategy_id, closed_trades, win_rate, avg_r, expectancy_r,
                      governance_state, live_eligible, live_block_reason,
                      window_start, window_end
               FROM paper_performance_governance
               ORDER BY created_at DESC"""
        )
        if rows:
            # Take the most recent entry per strategy
            seen = set()
            for r in rows:
                sid = r["strategy_id"]
                if sid not in seen:
                    seen.add(sid)
                    governance_rows.append(dict(r))
            governance_strategy_count = len(governance_rows)
            governance_total_closed = sum(r.get("closed_trades", 0) or 0 for r in governance_rows)

    if args.verbose:
        print(f"\nGovernance: {governance_strategy_count} strategies, {governance_total_closed} total closed trades reported")
        for g in governance_rows:
            print(f"  {g['strategy_id']}: closed={g.get('closed_trades', 0)}  "
                  f"wr={g.get('win_rate', 'n/a')}  state={g.get('governance_state', '?')}  "
                  f"eligible={g.get('live_eligible', '?')}")

    # ── 3. Strategy scorecards ──────────────────────────────────────────────
    scorecard_rows = []
    scorecard_strategy_count = 0
    scorecard_total_closed = 0

    if _table_exists(conn, "paper_strategy_scorecards"):
        rows = _safe_query(
            conn,
            """SELECT strategy_name, closed_count, win_count, loss_count,
                      win_rate, avg_r_multiple, total_pnl, expectancy_r,
                      sample_quality, recommendation, scorecard_date
               FROM paper_strategy_scorecards
               ORDER BY scorecard_date DESC, strategy_name"""
        )
        if rows:
            # Take the most recent entry per strategy
            seen = set()
            for r in rows:
                sid = r["strategy_name"]
                if sid not in seen:
                    seen.add(sid)
                    scorecard_rows.append(dict(r))
            scorecard_strategy_count = len(scorecard_rows)
            scorecard_total_closed = sum(r.get("closed_count", 0) or 0 for r in scorecard_rows)

    if args.verbose:
        print(f"\nScorecards: {scorecard_strategy_count} strategies, {scorecard_total_closed} total closed in scorecards")
        for s in scorecard_rows:
            print(f"  {s['strategy_name']}: closed={s.get('closed_count', 0)}  "
                  f"wr={s.get('win_rate', 'n/a')}  quality={s.get('sample_quality', '?')}  "
                  f"rec={s.get('recommendation', '?')}")

    # ── 4. Mismatch analysis ───────────────────────────────────────────────
    mismatch = False
    explanation = ""
    recommended_fix = ""

    # Mismatch 1: closed trades exist but scorecard shows 0
    if closed_trades > 0 and scorecard_total_closed == 0:
        mismatch = True
        n_strats = len(strategies_with_closed)
        explanation = (
            f"{closed_trades} closed trades exist across {n_strats} "
            f"{'strategy' if n_strats == 1 else 'strategies'}, but no strategy scorecards "
            f"have been materialized (scorecard closed_count total = 0)."
        )
        recommended_fix = (
            "Run the scorecard materializer to generate strategy scorecards from closed trades. "
            "Check that paper_strategy_scorecards is being populated by the governance pipeline."
        )

    # Mismatch 2: closed trades exist, scorecards exist, but counts diverge significantly
    elif closed_trades > 0 and scorecard_total_closed > 0:
        diff = abs(closed_trades - scorecard_total_closed)
        if diff > max(2, closed_trades * 0.15):
            mismatch = True
            explanation = (
                f"Closed trade count ({closed_trades}) and scorecard total ({scorecard_total_closed}) "
                f"differ by {diff}. This may indicate trades not assigned to a strategy, "
                f"stale scorecards, or trades excluded by minimum sample-size filters."
            )
            unassigned = strategies_with_closed.get("unassigned", 0) + strategies_with_closed.get(None, 0)
            if unassigned > 0:
                explanation += f" {unassigned} closed trades have no strategy assignment."
            recommended_fix = (
                "Verify all closed trades have a strategy_id. Re-run scorecard materializer. "
                "Check if minimum sample-size filter is excluding strategies with few trades."
            )

    # Mismatch 3: governance says live_eligible but scorecard says insufficient sample
    elif governance_rows and scorecard_rows:
        eligible_strats = {g["strategy_id"] for g in governance_rows if g.get("live_eligible")}
        poor_quality = {s["strategy_name"] for s in scorecard_rows
                        if s.get("sample_quality") in ("insufficient", "poor", "minimal")}
        contradictions = eligible_strats & poor_quality
        if contradictions:
            mismatch = True
            explanation = (
                f"Strategies marked live_eligible in governance but with insufficient sample quality "
                f"in scorecards: {', '.join(sorted(contradictions))}."
            )
            recommended_fix = (
                "Review governance criteria vs scorecard sample_quality thresholds. "
                "Governance may need to incorporate scorecard quality checks."
            )

    if not mismatch and closed_trades > 0:
        n_strats = len(strategies_with_closed)
        explanation = (
            f"{closed_trades} closed trades spread across {n_strats} strategies. "
            f"Scorecard reports {scorecard_total_closed} closed trades across "
            f"{scorecard_strategy_count} strategies. Counts are consistent."
        )
        recommended_fix = "None required."

    if closed_trades == 0:
        explanation = "No closed trades yet. Scorecards and governance will populate after first trade closure."
        recommended_fix = "None required -- system is pre-trade."

    report = {
        "generated_at": now.isoformat(),
        "closed_trades": closed_trades,
        "open_trades": open_trades,
        "strategies_with_closed_trades": strategies_with_closed,
        "strategies_with_open_trades": strategies_with_open,
        "governance_strategy_count": governance_strategy_count,
        "governance_total_closed_reported": governance_total_closed,
        "scorecard_strategy_count": scorecard_strategy_count,
        "scorecard_total_closed": scorecard_total_closed,
        "mismatch": mismatch,
        "explanation": explanation,
        "recommended_fix": recommended_fix,
        "governance_detail": governance_rows,
        "scorecard_detail": [{k: v for k, v in s.items()} for s in scorecard_rows],
    }

    if args.verbose:
        print(f"\n{'='*60}")
        print(f"  MISMATCH: {mismatch}")
        print(f"  {explanation}")
        if mismatch:
            print(f"  FIX: {recommended_fix}")
        print(f"{'='*60}")

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
        if args.verbose:
            print(f"  JSON written to {args.output_json}")

    if args.output_md:
        md = []
        md.append(f"# Governance Count Consistency  {now.date().isoformat()}")
        md.append(f"\n**Mismatch:** {'YES' if mismatch else 'No'}")
        md.append(f"\n| Metric | Value |")
        md.append(f"|--------|-------|")
        md.append(f"| Closed trades (paper_trades) | {closed_trades} |")
        md.append(f"| Open trades (paper_trades) | {open_trades} |")
        md.append(f"| Governance strategies | {governance_strategy_count} |")
        md.append(f"| Governance total closed | {governance_total_closed} |")
        md.append(f"| Scorecard strategies | {scorecard_strategy_count} |")
        md.append(f"| Scorecard total closed | {scorecard_total_closed} |")
        md.append(f"\n**Explanation:** {explanation}")
        if mismatch:
            md.append(f"\n**Recommended fix:** {recommended_fix}")
        if scorecard_rows:
            md.append(f"\n## Strategy Scorecards")
            md.append(f"| Strategy | Closed | Win Rate | Quality | Recommendation |")
            md.append(f"|----------|--------|----------|---------|----------------|")
            for s in scorecard_rows:
                wr = f"{float(s['win_rate']):.1%}" if s.get("win_rate") is not None else "n/a"
                md.append(
                    f"| {s['strategy_name']} | {s.get('closed_count', 0)} | {wr} | "
                    f"{s.get('sample_quality', '?')} | {s.get('recommendation', '?')} |"
                )
        Path(args.output_md).write_text("\n".join(md))
        if args.verbose:
            print(f"  Markdown written to {args.output_md}")

    # Print compact JSON to stdout (without detail arrays)
    compact = {k: v for k, v in report.items() if k not in ("governance_detail", "scorecard_detail")}
    print(json.dumps(compact, indent=2, default=str))


if __name__ == "__main__":
    main()
