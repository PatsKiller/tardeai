#!/usr/bin/env python3
"""
update_agent_performance.py — Score agent accuracy from decision_outcomes.

Loads decision_outcomes with price data, matches to agent recommendations
from watchlist_agent_results, computes accuracy (did recommendation direction
match actual price outcome?), and writes to agent_performance_history.

CLI: python3 scripts/update_agent_performance.py [--json] [--dry-run]

Refactor wave 2 (cron -> n8n, 2026-10-10; cron:L427):
- The connection comes from db_adapter (shared credential loader), not an inline .env password parse.
- Scoring (``score``) is SELECT-only; the INSERTs live in ``_write_rows``. ``--dry-run`` scores on a
  READ ONLY session and returns before ``_write_rows`` is reachable, reporting the rows it would add.
- A real run writes data/runtime/update_agent_performance_last.json (LaneRunReceipt@v1, ok_at only on
  success); a DB error exits non-zero. No matched recommendations is a finding, not a failure.
"""
import json, os, sys
from collections import defaultdict
from datetime import datetime, date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"

# Direction classification for recommendations
BULLISH_RECS = {"buy", "add", "accumulate", "hold", "outperform", "overweight", "strong_buy"}
BEARISH_RECS = {"sell", "trim", "exit", "reduce", "underperform", "underweight", "avoid"}
LOOKBACK_DAYS = 30


def _get_conn():
    # Shared loader (env_bootstrap / .env, timeouts) -- no inline password parse.
    from db_adapter import _get_conn as _adapter_conn

    return _adapter_conn()


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


def score(cur) -> dict:
    """READ ONLY: every statement is a SELECT. Returns outcomes/matched counts and per-agent rows."""

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

    rows = []
    for agent, stats in agent_stats.items():
        if stats["total"] == 0:
            continue
        accuracy = round(100.0 * stats["correct"] / stats["total"], 1)
        avg_conf = round(sum(stats["confidences"]) / len(stats["confidences"]), 3) if stats["confidences"] else 0
        rows.append({"agent": agent, "total": stats["total"], "correct": stats["correct"],
                     "accuracy_pct": accuracy, "avg_confidence": avg_conf, "overrides": stats["overrides"]})
    return {"outcomes": len(outcomes), "matched": matched_count, "rows": rows,
            "period_start": period_start, "period_end": today}


def _write_rows(cur, scored: dict) -> list:
    """The ONLY write: one agent_performance_history row per scored agent."""
    written = []
    for r in scored["rows"]:
        cur.execute("""
            INSERT INTO agent_performance_history
                (agent, period_start, period_end, total_recommendations,
                 accuracy_pct, avg_confidence, rule_violations, human_overrides)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            r["agent"], scored["period_start"], scored["period_end"], r["total"],
            r["accuracy_pct"], r["avg_confidence"], 0, r["overrides"],
        ))
        perf_id = cur.fetchone()[0]
        written.append({"id": perf_id, **r})
    return written


def run(as_json: bool = False, dry_run: bool = False) -> int:
    conn = _get_conn()
    if dry_run:
        from lib.lane_last_receipt import enforce_readonly

        enforce_readonly(conn)  # the server refuses any write (AGENTS.md §6)
        try:
            scored = score(conn.cursor())
            conn.rollback()
        finally:
            conn.close()
        print(json.dumps({
            "mode": "dry_run", "outcomes_analyzed": scored["outcomes"], "matches_found": scored["matched"],
            "would_write": {"table": "agent_performance_history", "rows": len(scored["rows"])},
            "agents": scored["rows"],
        }, default=str, indent=2))
        return 0

    from lib.lane_last_receipt import now_iso, write_receipt

    started_at = now_iso()
    try:
        cur = conn.cursor()
        scored = score(cur)
        written = _write_rows(cur, scored)
        conn.commit()
        cur.close()
        conn.close()
    except Exception as exc:
        write_receipt("update_agent_performance", ok=False, started_at=started_at,
                      error=f"{type(exc).__name__}: {exc}")
        raise
    outcomes, matched_count = scored["outcomes"], scored["matched"]
    write_receipt("update_agent_performance", ok=True, started_at=started_at,
                  summary={"outcomes": outcomes, "matched": matched_count, "agents_scored": len(written)})

    if as_json:
        print(json.dumps({
            "outcomes_analyzed": outcomes,
            "matches_found": matched_count,
            "agents_scored": written,
        }, default=str))
    else:
        print(f"[update_agent_performance] Analyzed {outcomes} outcomes, matched {matched_count} agent recommendations.")
        print(f"[update_agent_performance] Scored {len(written)} agents:")
        for w in written:
            print(f"  {w['agent']:<15} | {w['total']:>3} recs | accuracy={w['accuracy_pct']:5.1f}% | conf={w['avg_confidence']:.3f} | overrides={w['overrides']}")
        if not written:
            print("  (no agent recommendations matched to outcomes with price data)")
    return 0


if __name__ == "__main__":
    sys.exit(run(as_json="--json" in sys.argv, dry_run="--dry-run" in sys.argv))
