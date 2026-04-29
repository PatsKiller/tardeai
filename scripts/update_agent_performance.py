#!/usr/bin/env python3
"""
update_agent_performance.py — Score agent accuracy from decision_outcomes.

Loads decision_outcomes with price data, matches to agent recommendations
from watchlist_agent_results, computes accuracy (did recommendation direction
match actual price outcome?), and writes to agent_performance_history.

CLI: python3 scripts/update_agent_performance.py [--json]
"""
import json, os, sys
from collections import defaultdict
from datetime import datetime, date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"

# Direction classification for recommendations
BULLISH_RECS = {"buy", "add", "accumulate", "hold", "outperform", "overweight", "strong_buy"}
BEARISH_RECS = {"sell", "trim", "exit", "reduce", "underperform", "underweight", "avoid"}
LOOKBACK_DAYS = 30


def _get_conn():
    import psycopg2
    pw = ""
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        if line.startswith("DB_PASSWORD="):
            pw = line.split("=", 1)[1].strip()
    return psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)


def _rec_direction(rec: str) -> str:
    """Classify a recommendation string as bullish, bearish, or neutral."""
    if not rec:
        return "neutral"
    r = rec.lower().strip().replace(" ", "_")
    if r in BULLISH_RECS:
        return "bullish"
    if r in BEARISH_RECS:
        return "bearish"
    # Keyword fallback
    if any(kw in r for kw in ["buy", "add", "hold", "accumulate"]):
        return "bullish"
    if any(kw in r for kw in ["sell", "trim", "exit", "reduce", "avoid"]):
        return "bearish"
    return "neutral"


def _outcome_direction(price_at: float, price_after: float) -> str:
    """Did the price go up or down?"""
    if price_after is None or price_at is None or price_at == 0:
        return "unknown"
    pct = (price_after - price_at) / price_at
    if pct > 0.01:
        return "bullish"
    if pct < -0.01:
        return "bearish"
    return "neutral"


def run(as_json: bool = False):
    conn = _get_conn()
    cur = conn.cursor()

    cutoff = datetime.now() - timedelta(days=LOOKBACK_DAYS)
    today = date.today()
    period_start = today - timedelta(days=LOOKBACK_DAYS)

    # Load decision_outcomes that have at least one price follow-up
    cur.execute("""
        SELECT dout.id, dout.symbol, dout.recommendation, dout.price_at_decision,
               dout.price_7d, dout.price_30d, dout.created_at
        FROM decision_outcomes dout
        WHERE dout.created_at >= %s
          AND dout.price_at_decision IS NOT NULL
          AND (dout.price_7d IS NOT NULL OR dout.price_30d IS NOT NULL)
        ORDER BY dout.created_at DESC
    """, (cutoff,))
    outcomes = cur.fetchall()

    # Load agent results for matching
    cur.execute("""
        SELECT war.id, war.symbol, war.agent, war.recommendation, war.confidence,
               war.created_at
        FROM watchlist_agent_results war
        WHERE war.created_at >= %s
          AND war.recommendation IS NOT NULL
        ORDER BY war.created_at DESC
    """, (cutoff,))
    agent_results = cur.fetchall()

    # Index agent results by symbol for matching
    agent_by_symbol = defaultdict(list)
    for ar_id, ar_sym, ar_agent, ar_rec, ar_conf, ar_created in agent_results:
        agent_by_symbol[ar_sym].append({
            "id": ar_id, "agent": ar_agent, "recommendation": ar_rec,
            "confidence": float(ar_conf or 0), "created_at": ar_created,
        })

    # Track per-agent stats
    agent_stats = defaultdict(lambda: {
        "total": 0, "correct": 0, "wrong": 0, "neutral": 0,
        "confidences": [], "overrides": 0,
    })

    matched_count = 0
    for do_id, symbol, do_rec, price_at, price_7d, price_30d, created_at in outcomes:
        # Use 7d price if available, else 30d
        price_after = price_7d if price_7d is not None else price_30d
        actual_dir = _outcome_direction(float(price_at), float(price_after))
        if actual_dir == "unknown":
            continue

        # Find matching agent recommendations for this symbol near this time
        matches = agent_by_symbol.get(symbol, [])
        for ar in matches:
            # Match: agent result created within 2 days before the decision
            if ar["created_at"] is None or created_at is None:
                continue
            delta = abs((created_at - ar["created_at"]).total_seconds())
            if delta > 172800:  # 48 hours
                continue

            rec_dir = _rec_direction(ar["recommendation"])
            if rec_dir == "neutral":
                continue

            agent = ar["agent"] or "unknown"
            agent_stats[agent]["total"] += 1
            agent_stats[agent]["confidences"].append(ar["confidence"])

            if rec_dir == actual_dir:
                agent_stats[agent]["correct"] += 1
            else:
                agent_stats[agent]["wrong"] += 1

            # Check if human overrode
            do_rec_dir = _rec_direction(do_rec)
            if do_rec_dir != "neutral" and do_rec_dir != rec_dir:
                agent_stats[agent]["overrides"] += 1

            matched_count += 1

    # Write agent_performance_history rows
    written = []
    for agent, stats in agent_stats.items():
        if stats["total"] == 0:
            continue
        accuracy = round(100.0 * stats["correct"] / stats["total"], 1)
        avg_conf = round(sum(stats["confidences"]) / len(stats["confidences"]), 3) if stats["confidences"] else 0

        cur.execute("""
            INSERT INTO agent_performance_history
                (agent, period_start, period_end, total_recommendations,
                 accuracy_pct, avg_confidence, rule_violations, human_overrides)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            agent, period_start, today, stats["total"],
            accuracy, avg_conf, 0, stats["overrides"],
        ))
        perf_id = cur.fetchone()[0]
        written.append({
            "id": perf_id,
            "agent": agent,
            "total": stats["total"],
            "correct": stats["correct"],
            "accuracy_pct": accuracy,
            "avg_confidence": avg_conf,
            "overrides": stats["overrides"],
        })

    conn.commit()
    cur.close()
    conn.close()

    if as_json:
        print(json.dumps({
            "outcomes_analyzed": len(outcomes),
            "matches_found": matched_count,
            "agents_scored": written,
        }, default=str))
    else:
        print(f"[update_agent_performance] Analyzed {len(outcomes)} outcomes, matched {matched_count} agent recommendations.")
        print(f"[update_agent_performance] Scored {len(written)} agents:")
        for w in written:
            print(f"  {w['agent']:<15} | {w['total']:>3} recs | accuracy={w['accuracy_pct']:5.1f}% | conf={w['avg_confidence']:.3f} | overrides={w['overrides']}")
        if not written:
            print("  (no agent recommendations matched to outcomes with price data)")


if __name__ == "__main__":
    run(as_json="--json" in sys.argv)
