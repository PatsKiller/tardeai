#!/usr/bin/env python3
"""trade_learning_engine.py — Evaluate paper trade outcomes and strategy performance.

Generates learning hypotheses and recommendations. No active config changes.

Usage:
    .venv/bin/python scripts/trade_learning_engine.py --analyze --dry-run --json
    .venv/bin/python scripts/trade_learning_engine.py --strategy momentum_scalp --dry-run --json
"""
import argparse, json, os, sys
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")


def _f(v):
    return float(v) if isinstance(v, Decimal) else v


def _get_conn():
    from session13_db import get_conn
    return get_conn()


def analyze_strategies(conn, strategy_filter=None, window_days=90):
    """Analyze strategy performance from paper trades."""
    cur = conn.cursor()
    window_start = datetime.now(timezone.utc) - timedelta(days=window_days)

    # Strategy-level paper trade stats
    sql = """
        SELECT pt.strategy_id,
               COUNT(*) as total,
               COUNT(*) FILTER (WHERE pt.status='closed') as closed,
               COUNT(*) FILTER (WHERE pt.status='closed' AND pt.pnl > 0) as wins,
               COUNT(*) FILTER (WHERE pt.status='closed' AND pt.pnl <= 0) as losses,
               COALESCE(SUM(CASE WHEN pt.pnl > 0 THEN pt.pnl ELSE 0 END), 0) as gross_profit,
               COALESCE(SUM(CASE WHEN pt.pnl < 0 THEN ABS(pt.pnl) ELSE 0 END), 0) as gross_loss,
               AVG(pt.r_multiple) FILTER (WHERE pt.status='closed') as avg_r
        FROM paper_trades pt
        WHERE pt.created_at > %s
    """
    params = [window_start]
    if strategy_filter:
        sql += " AND pt.strategy_id = %s"
        params.append(strategy_filter)
    sql += " GROUP BY pt.strategy_id"
    cur.execute(sql, params)

    strategies = []
    for r in cur.fetchall():
        strat_id = r[0] or "unknown"
        closed = r[2] or 0
        wins = r[3] or 0
        losses = r[4] or 0
        gp = _f(r[5]) or 0
        gl = _f(r[6]) or 0

        score = {
            "strategy_id": strat_id,
            "window_start": str(window_start),
            "window_end": str(datetime.now(timezone.utc)),
            "paper_trades": r[1],
            "closed_trades": closed,
            "wins": wins,
            "losses": losses,
            "win_rate": round(wins / closed, 4) if closed > 0 else None,
            "profit_factor": round(gp / gl, 4) if gl > 0 else None,
            "expectancy_r": _f(r[7]),
            "low_sample_size": closed < 30,
        }

        # Recommendation
        if closed < 5:
            score["recommendation"] = "insufficient_data"
            score["learning_summary"] = f"Only {closed} closed trades. Need 30+ for insights."
        elif score["win_rate"] and score["win_rate"] < 0.3:
            score["recommendation"] = "review_strategy_rules"
            score["learning_summary"] = f"Low win rate {score['win_rate']:.0%}. Review entry criteria."
        elif score["profit_factor"] and score["profit_factor"] < 0.8:
            score["recommendation"] = "review_risk_reward"
            score["learning_summary"] = f"Low PF {score['profit_factor']:.2f}. Review stop/target."
        else:
            score["recommendation"] = "maintain_current"
            score["learning_summary"] = f"Performance within acceptable range."

        strategies.append(score)

    # Proposal funnel
    cur.execute("""
        SELECT COUNT(*) as total,
               COUNT(*) FILTER (WHERE status IN ('APPROVED','APPROVED_FOR_PAPER_TEST')) as approved,
               COUNT(*) FILTER (WHERE status='REJECTED') as rejected
        FROM paper_trade_proposals WHERE created_at > %s
    """, [window_start])
    funnel = cur.fetchone()

    return {
        "strategies": strategies,
        "funnel": {"total_proposals": funnel[0], "approved": funnel[1], "rejected": funnel[2]},
        "window_days": window_days,
    }


def generate_hypotheses(conn, analysis, dry_run=True):
    """Generate trade learning hypotheses."""
    from learning_governance import (create_hypothesis, add_evidence,
                                     create_recommendation, compute_sample_size_status)
    hypotheses = []

    for strat in analysis["strategies"]:
        if strat["recommendation"] == "maintain_current":
            continue
        if strat["recommendation"] == "insufficient_data":
            # Still create insight hypothesis
            tier = "insight_only"
        else:
            tier = compute_sample_size_status("strategy", strat["closed_trades"])

        title = f"Strategy '{strat['strategy_id']}': {strat['recommendation']}"
        h = {"title": title, "domain": "strategy", "type": strat["recommendation"],
             "description": strat["learning_summary"], "sample_size": strat["closed_trades"],
             "sample_tier": tier, "strategy_id": strat["strategy_id"]}

        if not dry_run:
            hid = create_hypothesis(conn, title, "strategy", "strategy_rule_change",
                                    strat["learning_summary"],
                                    strategy_id=strat["strategy_id"],
                                    sample_size=strat["closed_trades"],
                                    payload=strat)
            add_evidence(conn, hid, "closed_trade", strat,
                         supports=strat["recommendation"] != "maintain_current",
                         strategy_id=strat["strategy_id"],
                         source_table="paper_trades")
            if tier != "insight_only" and strat["recommendation"] != "insufficient_data":
                create_recommendation(conn, hid, "strategy", strat["recommendation"],
                                      title, strat["learning_summary"],
                                      sample_size=strat["closed_trades"],
                                      risk_level="medium")
            h["hypothesis_id"] = hid

        hypotheses.append(h)

    return hypotheses


def save_scores(conn, analysis, dry_run=True):
    if dry_run:
        return
    cur = conn.cursor()
    for s in analysis["strategies"]:
        cur.execute("""
            INSERT INTO strategy_learning_scores
                (strategy_id, window_start, window_end, paper_trades, closed_trades,
                 wins, losses, win_rate, profit_factor, expectancy_r,
                 low_sample_size, learning_summary, recommendation, payload)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (strategy_id, window_start, window_end) DO UPDATE SET
                closed_trades=EXCLUDED.closed_trades, wins=EXCLUDED.wins, losses=EXCLUDED.losses,
                win_rate=EXCLUDED.win_rate, profit_factor=EXCLUDED.profit_factor,
                recommendation=EXCLUDED.recommendation
        """, [s["strategy_id"], s["window_start"], s["window_end"],
              s["paper_trades"], s["closed_trades"], s["wins"], s["losses"],
              s.get("win_rate"), s.get("profit_factor"), s.get("expectancy_r"),
              s["low_sample_size"], s.get("learning_summary"), s["recommendation"],
              json.dumps(s, default=str)])
    conn.commit()


def main():
    parser = argparse.ArgumentParser(description="Trade Learning Engine")
    parser.add_argument("--analyze", action="store_true")
    parser.add_argument("--strategy", help="Filter by strategy_id")
    parser.add_argument("--symbol", help="Filter by symbol")
    parser.add_argument("--create-proposals", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--window-days", type=int, default=90)
    args = parser.parse_args()

    conn = _get_conn()
    try:
        if args.analyze or args.strategy:
            analysis = analyze_strategies(conn, strategy_filter=args.strategy,
                                          window_days=args.window_days)
            hypotheses = generate_hypotheses(conn, analysis, dry_run=args.dry_run)
            save_scores(conn, analysis, dry_run=args.dry_run)

            out = {
                "mode": "dry_run" if args.dry_run else "applied",
                "strategies_analyzed": len(analysis["strategies"]),
                "hypotheses_generated": len(hypotheses),
                "funnel": analysis["funnel"],
                "window_days": args.window_days,
                "low_sample_warning": all(s["low_sample_size"] for s in analysis["strategies"]),
            }
            if args.json:
                out["strategies"] = analysis["strategies"]
                out["hypotheses"] = hypotheses
                print(json.dumps(out, indent=2, default=str))
            else:
                print(f"Trade Learning: {out['strategies_analyzed']} strategies, "
                      f"{out['hypotheses_generated']} hypotheses ({out['mode']})")
                if out["low_sample_warning"]:
                    print("  WARNING: All strategies have low sample size (<30 closed trades)")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
