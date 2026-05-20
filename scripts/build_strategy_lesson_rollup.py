#!/usr/bin/env python3
"""build_strategy_lesson_rollup.py — Aggregate trade_lesson_memory into strategy-level rollups.

Groups lessons by strategy_id, computes win/loss stats, identifies repeated mistakes,
and writes to strategy_lesson_rollup. Read-only unless --apply.
"""
import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))

from db_adapter import _get_conn


def _classify_recommendation(most_common_mistake, wins, losses):
    """Determine review recommendation based on patterns."""
    if most_common_mistake == "stale_manual_exit":
        return "review_exit_rule"
    if most_common_mistake == "spread_slippage":
        return "review_entry_filter"
    if most_common_mistake == "instant_stop":
        return "review_entry_timing"
    if most_common_mistake == "missed_target":
        return "review_target_rule"
    if wins > losses:
        return "no_action"
    if losses > wins * 2:
        return "pause_strategy"
    return "monitor"


def run(args):
    conn = _get_conn()
    if conn is None:
        print("[ERROR] No database connection available.")
        return {"status": "error", "reason": "no_db_connection"}

    since_date = (datetime.now(timezone.utc) - timedelta(days=args.since_days)).date()
    cur = conn.cursor()

    # Load all lessons in the period
    cur.execute("""
        SELECT strategy_id, trade_id, pnl, r_multiple, mistake_type,
               lesson_category, confidence_delta
        FROM trade_lesson_memory
        WHERE created_at >= %s
        ORDER BY strategy_id
    """, (since_date,))
    cols = [desc[0] for desc in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]

    if not rows:
        print("[INFO] No lessons found in the period.")
        return {"status": "ok", "strategies": 0}

    # Group by strategy_id
    strategies = {}
    for row in rows:
        sid = row["strategy_id"] or "unknown"
        if sid not in strategies:
            strategies[sid] = []
        strategies[sid].append(row)

    rollups = []
    for sid, lessons in strategies.items():
        unique_trades = set(l["trade_id"] for l in lessons if l["trade_id"])
        pnls = [float(l["pnl"] or 0) for l in lessons]
        r_vals = [float(l["r_multiple"] or 0) for l in lessons if l["r_multiple"] is not None]
        wins = sum(1 for p in pnls if p > 0)
        losses_count = sum(1 for p in pnls if p < 0)

        # Mistake analysis
        mistake_counter = Counter(l["mistake_type"] for l in lessons if l["mistake_type"] and l["mistake_type"] != "none")
        most_common_mistake = mistake_counter.most_common(1)[0][0] if mistake_counter else "none"
        repeated_mistakes = [{"mistake_type": k, "count": v} for k, v in mistake_counter.items() if v >= 2]

        # Positive/negative patterns from lesson_category
        cat_counter = Counter(l["lesson_category"] for l in lessons if l["lesson_category"])
        positive_patterns = [k for k, v in cat_counter.items() if "good" in k.lower() or "positive" in k.lower()]
        negative_patterns = [k for k, v in cat_counter.items() if "bad" in k.lower() or "negative" in k.lower() or "review" in k.lower()]

        # Confidence delta summary
        deltas = Counter(l["confidence_delta"] for l in lessons if l["confidence_delta"])
        confidence_summary = f"positive:{deltas.get('positive',0)} neutral:{deltas.get('neutral',0)} negative:{deltas.get('negative',0)}"

        recommendation = _classify_recommendation(most_common_mistake, wins, losses_count)
        avg_r = round(sum(r_vals) / len(r_vals), 2) if r_vals else 0.0
        realized_pnl = round(sum(pnls), 2)

        rollup = {
            "strategy_id": sid,
            "period_start": since_date.isoformat(),
            "period_end": datetime.now(timezone.utc).date().isoformat(),
            "closed_trades": len(unique_trades),
            "wins": wins,
            "losses": losses_count,
            "avg_r": avg_r,
            "realized_pnl": realized_pnl,
            "repeated_mistakes": json.dumps(repeated_mistakes),
            "positive_patterns": json.dumps(positive_patterns),
            "negative_patterns": json.dumps(negative_patterns),
            "confidence_delta_summary": confidence_summary,
            "review_recommendation": recommendation,
        }
        rollups.append(rollup)

        if args.verbose:
            print(f"  Strategy {sid}: {len(unique_trades)} trades, "
                  f"{wins}W/{losses_count}L, avg_r={avg_r}, pnl=${realized_pnl}, "
                  f"rec={recommendation}")

    if args.apply:
        for r in rollups:
            try:
                cur.execute("""
                    INSERT INTO strategy_lesson_rollup (
                        strategy_id, period_start, period_end,
                        closed_trades, wins, losses, avg_r, realized_pnl,
                        repeated_mistakes, positive_patterns, negative_patterns,
                        confidence_delta_summary, review_recommendation,
                        human_review_only, updated_at
                    ) VALUES (
                        %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s, %s,
                        %s, %s,
                        TRUE, NOW()
                    ) ON CONFLICT (strategy_id, period_start, period_end)
                    DO UPDATE SET
                        closed_trades = EXCLUDED.closed_trades,
                        wins = EXCLUDED.wins,
                        losses = EXCLUDED.losses,
                        avg_r = EXCLUDED.avg_r,
                        realized_pnl = EXCLUDED.realized_pnl,
                        repeated_mistakes = EXCLUDED.repeated_mistakes,
                        positive_patterns = EXCLUDED.positive_patterns,
                        negative_patterns = EXCLUDED.negative_patterns,
                        confidence_delta_summary = EXCLUDED.confidence_delta_summary,
                        review_recommendation = EXCLUDED.review_recommendation,
                        updated_at = NOW()
                """, (
                    r["strategy_id"], r["period_start"], r["period_end"],
                    r["closed_trades"], r["wins"], r["losses"], r["avg_r"], r["realized_pnl"],
                    r["repeated_mistakes"], r["positive_patterns"], r["negative_patterns"],
                    r["confidence_delta_summary"], r["review_recommendation"],
                ))
            except Exception as e:
                conn.rollback()
                print(f"  [ERROR] Strategy {r['strategy_id']}: {e}")
        conn.commit()

    mode_label = "APPLY" if args.apply else "DRY-RUN"
    print(f"[{mode_label}] Strategies: {len(rollups)}, Period: {since_date} to today")

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mode": mode_label.lower().replace("-", "_"),
        "since_days": args.since_days,
        "strategies_count": len(rollups),
        "rollups": rollups,
    }

    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        print(json.dumps(report, indent=2, default=str))
    if args.output_md:
        print(f"\n## Strategy Lesson Rollup")
        print(f"- Period: last {args.since_days} days")
        print(f"- Strategies: {len(rollups)}")
        for r in rollups:
            print(f"  - **{r['strategy_id']}**: {r['closed_trades']} trades, "
                  f"{r['wins']}W/{r['losses']}L, avg_r={r['avg_r']}, "
                  f"rec={r['review_recommendation']}")

    return report


def main():
    parser = argparse.ArgumentParser(description="Build strategy lesson rollup from trade_lesson_memory")
    parser.add_argument("--since-days", type=int, default=30, help="Look back N days (default: 30)")
    parser.add_argument("--dry-run", dest="apply", action="store_false", default=False,
                        help="Preview only (default)")
    parser.add_argument("--apply", dest="apply", action="store_true",
                        help="Write rollup rows")
    parser.add_argument("--output-json", type=str, help="Output JSON path")
    parser.add_argument("--output-md", type=str, help="Output Markdown path")
    parser.add_argument("--verbose", action="store_true", help="Verbose output")
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
