#!/usr/bin/env python3
"""paper_performance_governance.py — Per-strategy governance scoring for paper trading.

Computes performance metrics per strategy, checks TCA slippage and broker recon,
then assigns governance state. Live trading is permanently blocked.

PAPER ONLY. live_eligible is always false.

Usage:
    .venv/bin/python scripts/paper_performance_governance.py --dry-run
    .venv/bin/python scripts/paper_performance_governance.py --apply
"""
import argparse
import json
import logging
import sys
from datetime import datetime, timezone, date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from session13_db import get_conn
from local_llm_config import get_local_llm_model  # noqa: F401

log = logging.getLogger("perf_governance")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

# Governance constants
MIN_CLOSED_FOR_WATCHLIST = 30
MIN_PROFIT_FACTOR_CANDIDATE = 1.25
MIN_CALENDAR_DAYS_CANDIDATE = 180  # 6 months
LIVE_BLOCK_REASON = "Requires six months of validated paper results"


def get_strategy_stats(conn):
    """Get per-strategy aggregated paper trade stats."""
    cur = conn.cursor()
    cur.execute("""
        SELECT
            strategy_id,
            COUNT(*) AS trade_count,
            COUNT(*) FILTER (WHERE status = 'closed') AS closed_count,
            MIN(created_at) AS first_trade_at,
            MAX(created_at) AS last_trade_at,
            COUNT(*) FILTER (WHERE status = 'closed' AND pnl > 0) AS wins,
            COUNT(*) FILTER (WHERE status = 'closed' AND pnl <= 0) AS losses,
            AVG(r_multiple) FILTER (WHERE status = 'closed' AND r_multiple IS NOT NULL) AS avg_r,
            SUM(CASE WHEN status = 'closed' AND pnl > 0 THEN pnl ELSE 0 END) AS gross_profit,
            SUM(CASE WHEN status = 'closed' AND pnl < 0 THEN ABS(pnl) ELSE 0 END) AS gross_loss,
            ARRAY_AGG(r_multiple ORDER BY closed_at) FILTER (WHERE status = 'closed' AND r_multiple IS NOT NULL) AS r_series
        FROM paper_trades
        WHERE strategy_id IS NOT NULL
        GROUP BY strategy_id
        ORDER BY strategy_id
    """)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def get_tca_avg_slippage(conn, strategy_id):
    """Get average slippage from paper_execution_quality for a strategy."""
    cur = conn.cursor()
    cur.execute("""
        SELECT AVG(ABS(slippage_pct))
        FROM paper_execution_quality
        WHERE strategy_id = %s
          AND slippage_pct IS NOT NULL
    """, [strategy_id])
    row = cur.fetchone()
    return float(row[0]) if row and row[0] is not None else None


def get_broker_recon_issues(conn, strategy_id):
    """Get count of broker reconciliation issues for a strategy's trades."""
    cur = conn.cursor()
    cur.execute("""
        SELECT COUNT(*)
        FROM broker_reconciliation_items bri
        JOIN paper_trades pt ON pt.id = bri.paper_trade_id
        WHERE pt.strategy_id = %s
          AND bri.reconciliation_state NOT IN ('MATCHED', 'CLOSED_OK')
    """, [strategy_id])
    row = cur.fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def compute_max_drawdown_r(r_series):
    """Compute max drawdown in R terms from a series of R-multiples."""
    if not r_series:
        return None

    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0

    for r in r_series:
        if r is None:
            continue
        cumulative += float(r)
        if cumulative > peak:
            peak = cumulative
        dd = peak - cumulative
        if dd > max_dd:
            max_dd = dd

    return round(max_dd, 2) if max_dd > 0 else 0.0


def compute_expectancy(wins, losses, avg_r, win_rate):
    """Compute expectancy in R terms."""
    if wins + losses == 0 or avg_r is None:
        return None
    # Simple expectancy: (win_rate * avg_win_R) - (loss_rate * avg_loss_R)
    # Approximated using avg_r which includes all trades
    return round(float(avg_r), 4) if avg_r else None


def classify_governance(stats, tca_avg_slip, recon_issues):
    """Classify governance state for a strategy."""
    closed = stats["closed_count"] or 0
    wins = stats.get("wins", 0) or 0
    losses = stats.get("losses", 0) or 0
    gross_profit = float(stats.get("gross_profit") or 0)
    gross_loss = float(stats.get("gross_loss") or 0)
    avg_r = float(stats["avg_r"]) if stats.get("avg_r") is not None else None

    # Win rate
    win_rate = round(wins / closed * 100, 1) if closed > 0 else None

    # Profit factor
    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else None

    # Expectancy
    expectancy_r = compute_expectancy(wins, losses, avg_r, win_rate)

    # Max drawdown
    max_dd_r = compute_max_drawdown_r(stats.get("r_series"))

    # Calendar days
    first = stats.get("first_trade_at")
    last = stats.get("last_trade_at")
    if first and last:
        calendar_days = (last - first).days
    else:
        calendar_days = 0

    # Window dates
    window_start = first.date() if first else date.today()
    window_end = last.date() if last else date.today()

    # Governance state classification
    governance_state = "PAPER_ONLY"

    if closed >= MIN_CLOSED_FOR_WATCHLIST and expectancy_r is not None and expectancy_r > 0:
        governance_state = "WATCHLIST"

        if (calendar_days >= MIN_CALENDAR_DAYS_CANDIDATE
                and profit_factor is not None
                and profit_factor >= MIN_PROFIT_FACTOR_CANDIDATE):
            governance_state = "CANDIDATE_FOR_REVIEW"

            # Check all rules for live eligibility review
            all_pass = True
            if recon_issues and recon_issues > 0:
                all_pass = False
            if tca_avg_slip is not None and tca_avg_slip > 0.5:
                all_pass = False
            if max_dd_r is not None and max_dd_r > 5.0:
                all_pass = False

            if all_pass:
                governance_state = "LIVE_ELIGIBLE_REVIEW_REQUIRED"

    return {
        "strategy_id": stats["strategy_id"],
        "window_start": window_start,
        "window_end": window_end,
        "calendar_days": calendar_days,
        "paper_trades": stats["trade_count"],
        "closed_trades": closed,
        "win_rate": win_rate,
        "avg_r": round(float(avg_r), 4) if avg_r is not None else None,
        "expectancy_r": expectancy_r,
        "profit_factor": profit_factor,
        "max_drawdown_r": max_dd_r,
        "tca_avg_slippage_pct": round(tca_avg_slip, 4) if tca_avg_slip is not None else None,
        "broker_recon_issues": recon_issues or 0,
        "governance_state": governance_state,
        "live_eligible": False,
        "live_block_reason": LIVE_BLOCK_REASON,
    }


def insert_result(conn, result):
    """Insert governance result into DB."""
    cur = conn.cursor()
    payload = {
        "wins": result.get("_wins"),
        "losses": result.get("_losses"),
        "gross_profit": result.get("_gross_profit"),
        "gross_loss": result.get("_gross_loss"),
    }
    cur.execute("""
        INSERT INTO paper_performance_governance
            (strategy_id, window_start, window_end, calendar_days,
             paper_trades, closed_trades, win_rate, avg_r,
             expectancy_r, profit_factor, max_drawdown_r,
             tca_avg_slippage_pct, broker_recon_issues,
             governance_state, live_eligible, live_block_reason, payload)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, [
        result["strategy_id"], result["window_start"], result["window_end"],
        result["calendar_days"], result["paper_trades"], result["closed_trades"],
        result["win_rate"], result["avg_r"], result["expectancy_r"],
        result["profit_factor"], result["max_drawdown_r"],
        result["tca_avg_slippage_pct"], result["broker_recon_issues"],
        result["governance_state"], False, LIVE_BLOCK_REASON,
        json.dumps(payload, default=str),
    ])
    conn.commit()


def main():
    parser = argparse.ArgumentParser(description="Paper performance governance scorer")
    parser.add_argument("--dry-run", action="store_true", help="Compute but do not write to DB")
    parser.add_argument("--apply", action="store_true", help="Write results to DB")
    args = parser.parse_args()

    if not args.dry_run and not args.apply:
        parser.error("Specify --dry-run or --apply")

    conn = get_conn()
    try:
        strategies = get_strategy_stats(conn)

        if not strategies:
            output = {"status": "no_data", "message": "No paper trades found for any strategy", "results": []}
            print(json.dumps(output, indent=2, default=str))
            return

        results = []
        for stats in strategies:
            tca_avg_slip = get_tca_avg_slippage(conn, stats["strategy_id"])
            recon_issues = get_broker_recon_issues(conn, stats["strategy_id"])

            result = classify_governance(stats, tca_avg_slip, recon_issues)

            # Stash raw values for payload (not for output)
            result["_wins"] = stats.get("wins")
            result["_losses"] = stats.get("losses")
            result["_gross_profit"] = float(stats.get("gross_profit") or 0)
            result["_gross_loss"] = float(stats.get("gross_loss") or 0)

            if args.apply:
                insert_result(conn, result)
                log.info(f"Inserted governance for {result['strategy_id']}: "
                         f"{result['governance_state']} "
                         f"(closed={result['closed_trades']}, PF={result['profit_factor']})")

            # Remove internal keys before output
            for k in ("_wins", "_losses", "_gross_profit", "_gross_loss"):
                result.pop(k, None)

            results.append(result)

        # Summary
        state_counts = {}
        for r in results:
            s = r["governance_state"]
            state_counts[s] = state_counts.get(s, 0) + 1

        output = {
            "status": "dry_run" if args.dry_run else "applied",
            "strategies_evaluated": len(results),
            "governance_summary": state_counts,
            "all_live_eligible": False,
            "live_block_reason": LIVE_BLOCK_REASON,
            "results": results,
        }
        print(json.dumps(output, indent=2, default=str))

    finally:
        conn.close()


if __name__ == "__main__":
    main()
