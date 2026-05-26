#!/usr/bin/env python3
"""generate_phase8_strategy_scorecards.py — Generate preliminary strategy scorecards.

Reads from paper_trade_lifecycle_outcomes. Writes ONLY to paper_strategy_scorecards.
All scorecards are human_review_only. Does NOT change strategy activation.

Usage:
    .venv/bin/python scripts/generate_phase8_strategy_scorecards.py --apply --verbose
"""
import argparse, json, sys
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent


def get_conn():
    import psycopg2, psycopg2.extras
    env = {}
    for line in (PROJ / ".env").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return psycopg2.connect(host=env.get("DB_HOST", "localhost"), dbname=env.get("DB_NAME", "trade_ai"),
                            user=env.get("DB_USER", "trade_ai"), password=env.get("DB_PASSWORD", ""),
                            cursor_factory=psycopg2.extras.RealDictCursor)


def main():
    p = argparse.ArgumentParser()
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    p.add_argument("--since-days", type=int, default=30)
    p.add_argument("--min-closed-trades", type=int, default=1)
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT strategy_name,
            COUNT(*) FILTER (WHERE status='closed') as closed,
            COUNT(*) FILTER (WHERE outcome_label IN ('win','target_hit')) as wins,
            COUNT(*) FILTER (WHERE outcome_label IN ('loss','stopped')) as losses,
            ROUND(AVG(r_multiple) FILTER (WHERE status='closed' AND r_multiple IS NOT NULL)::numeric, 3) as avg_r,
            ROUND(SUM(COALESCE(pnl,0)) FILTER (WHERE status='closed')::numeric, 2) as total_pnl
        FROM paper_trade_lifecycle_outcomes
        WHERE created_at > NOW() - INTERVAL '%s days'
        GROUP BY strategy_name
        HAVING COUNT(*) FILTER (WHERE status='closed') >= %s
        ORDER BY COUNT(*) FILTER (WHERE status='closed') DESC
    """, [args.since_days, args.min_closed_trades])
    strategies = cur.fetchall()

    scorecards = []
    for s in strategies:
        closed = s["closed"]
        wins = s["wins"]
        wr = round(wins / closed, 3) if closed > 0 else 0
        sample = "insufficient" if closed < 5 else "preliminary" if closed < 20 else "usable"
        rec = "observe_more" if closed < 5 else ("keep_active" if wr >= 0.4 else "review_strategy")

        card = {
            "strategy_name": s["strategy_name"],
            "closed_count": closed,
            "win_count": wins,
            "loss_count": s["losses"],
            "win_rate": wr,
            "avg_r_multiple": float(s["avg_r"]) if s["avg_r"] else None,
            "total_pnl": float(s["total_pnl"]) if s["total_pnl"] else 0,
            "sample_quality": sample,
            "recommendation": rec,
        }
        scorecards.append(card)

        if not args.dry_run:
            cur.execute("""
                INSERT INTO paper_strategy_scorecards
                    (scorecard_date, lookback_days, strategy_name, closed_count, win_count, loss_count,
                     win_rate, avg_r_multiple, total_pnl, sample_quality, recommendation, recommendation_status)
                VALUES (CURRENT_DATE, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'human_review_only')
            """, [args.since_days, card["strategy_name"], card["closed_count"], card["win_count"],
                  card["loss_count"], card["win_rate"], card["avg_r_multiple"], card["total_pnl"],
                  card["sample_quality"], card["recommendation"]])

    if not args.dry_run:
        conn.commit()
    conn.close()

    if args.verbose:
        mode = "DRY RUN" if args.dry_run else "APPLY"
        print(f"Strategy Scorecards [{mode}] — {len(scorecards)} strategies")
        for c in scorecards:
            print(f"  {c['strategy_name']:30s} closed={c['closed_count']} WR={c['win_rate']:.0%} "
                  f"R={c['avg_r_multiple'] or '?'} PnL=${c['total_pnl']:.2f} [{c['sample_quality']}]")

    if args.output_json:
        Path(args.output_json).write_text(json.dumps({"scorecards": scorecards}, indent=2, default=str))
    if args.output_md:
        md = [f"# Strategy Scorecards ({mode})", "",
              "| Strategy | Closed | WR | Avg R | PnL | Quality | Rec |",
              "|----------|--------|-----|-------|-----|---------|-----|"]
        for c in scorecards:
            md.append(f"| {c['strategy_name']} | {c['closed_count']} | {c['win_rate']:.0%} | {c['avg_r_multiple'] or '?'} | ${c['total_pnl']:.2f} | {c['sample_quality']} | {c['recommendation']} |")
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
