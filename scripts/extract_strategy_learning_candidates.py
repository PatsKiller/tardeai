#!/usr/bin/env python3
"""
Extract strategy learning candidates from journal, backtests, and postmortems.
Produces machine-readable learning queue candidates.
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

# Load .env
env_path = PROJECT_ROOT / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip("'\"")
            if k and k not in os.environ:
                os.environ[k] = v


def get_conn():
    import psycopg2
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"), port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "trade_ai"), user=os.getenv("DB_USER", "trade_ai"),
        password=os.getenv("DB_PASSWORD", ""),
    )


def extract_candidates():
    """Extract learning candidates from all lesson sources."""
    conn = get_conn()
    cur = conn.cursor()
    candidates = []

    # Source 1: Closed trades with stop defects
    cur.execute("""
        SELECT id, symbol, strategy_id, entry_price, stop_loss, target_1, pnl, exit_reason,
               max_favorable_excursion, max_adverse_excursion
        FROM paper_trades WHERE status = 'closed'
    """)
    cols = [d[0] for d in cur.description]
    for row in cur.fetchall():
        t = dict(zip(cols, row))
        entry = float(t["entry_price"] or 0)
        stop = float(t["stop_loss"] or 0)
        target = float(t["target_1"] or 0)
        mfe = float(t["max_favorable_excursion"] or 0)

        # Stop defect: stop >= entry
        if entry > 0 and stop > 0 and stop >= entry:
            candidates.append({
                "source_type": "exit_forensics",
                "source_id": t["id"],
                "strategy": t["strategy_id"],
                "symbol": t["symbol"],
                "lesson_type": "stop_too_tight",
                "lesson_summary": f"Stop ${stop:.2f} >= entry ${entry:.2f} — guaranteed loss. Stop placement validation needed.",
                "evidence_count": 1,
                "sample_size": 1,
                "confidence": 0.9,
                "proposed_change": "Add stop < entry guard to bracket order creation",
                "proposed_change_type": "validation_rule",
                "risk_level": "HIGH",
                "no_live_mutation": True,
            })

        # Premature exit: MFE > 5% after stop-out
        if t["exit_reason"] in ("stop_hit", "stop_hit_instant") and mfe > 5:
            candidates.append({
                "source_type": "post_exit_analysis",
                "source_id": t["id"],
                "strategy": t["strategy_id"],
                "symbol": t["symbol"],
                "lesson_type": "premature_exit",
                "lesson_summary": f"Stopped out but MFE was +{mfe:.1f}% — price moved significantly in intended direction after exit.",
                "evidence_count": 1,
                "sample_size": 1,
                "confidence": 0.5,
                "proposed_change": "Consider trailing stop or wider initial stop for this strategy",
                "proposed_change_type": "stop_rule_review",
                "risk_level": "MEDIUM",
                "no_live_mutation": True,
            })

    # Source 2: Strategy backtest results with weak performance
    cur.execute("""
        SELECT sbt.strategy_id,
               ROUND(AVG(CASE WHEN sbt.pnl > 0 THEN 1.0 ELSE 0.0 END) * 100, 1) as win_rate,
               COUNT(*) as sample,
               ROUND(AVG(sbt.r_multiple)::numeric, 2) as avg_r
        FROM strategy_backtest_trades sbt
        WHERE sbt.strategy_id IS NOT NULL AND sbt.strategy_id != '' AND sbt.strategy_id != 'unknown'
        GROUP BY sbt.strategy_id
        HAVING COUNT(*) >= 5
    """)
    for row in cur.fetchall():
        sid, wr, sample, avg_r = row
        if float(wr or 0) < 35 and int(sample or 0) >= 10:
            candidates.append({
                "source_type": "backtest_analysis",
                "source_id": None,
                "strategy": sid,
                "symbol": None,
                "lesson_type": "weak_backtest",
                "lesson_summary": f"Strategy {sid} backtest: {wr}% win rate, avg R {avg_r}, n={sample}. Below minimum viability.",
                "evidence_count": int(sample),
                "sample_size": int(sample),
                "confidence": 0.6 if int(sample) >= 20 else 0.4,
                "proposed_change": f"Review {sid} strategy parameters or pause if win rate doesn't improve",
                "proposed_change_type": "strategy_review",
                "risk_level": "MEDIUM",
                "no_live_mutation": True,
            })

    # Source 3: Journal completeness gaps
    cur.execute("""
        SELECT
            COUNT(*) as total,
            COUNT(*) FILTER (WHERE hold_time_min IS NULL) as missing_hold,
            COUNT(*) FILTER (WHERE pnl IS NULL) as missing_pnl,
            COUNT(*) FILTER (WHERE max_favorable_excursion IS NULL) as missing_mfe
        FROM paper_trades WHERE status = 'closed'
    """)
    row = cur.fetchone()
    total, missing_hold, missing_pnl, missing_mfe = row
    if missing_hold > total * 0.5:
        candidates.append({
            "source_type": "journal_completeness",
            "source_id": None,
            "strategy": None,
            "symbol": None,
            "lesson_type": "data_quality",
            "lesson_summary": f"hold_time missing on {missing_hold}/{total} closed trades ({100*missing_hold//total}%). Learning cannot determine optimal hold periods.",
            "evidence_count": total,
            "sample_size": total,
            "confidence": 0.9,
            "proposed_change": "Instrument hold_time_min capture at trade close",
            "proposed_change_type": "instrumentation",
            "risk_level": "HIGH",
            "no_live_mutation": True,
        })

    conn.close()
    return candidates


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--json-out", type=str, default=None)
    args = ap.parse_args()

    candidates = extract_candidates()
    print(f"Learning candidates: {len(candidates)}")
    for c in candidates:
        print(f"  [{c['lesson_type']:20s}] {c['strategy'] or 'system':20s} conf={c['confidence']:.1f} | {c['lesson_summary'][:60]}")

    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(json.dumps(candidates, indent=2, default=str))
        print(f"\nWritten to {args.json_out}")


def extract_expanded_candidates():
    """Mine additional candidates from postmortems, backtests, and catalyst data."""
    conn = get_conn()
    cur = conn.cursor()
    candidates = extract_candidates()  # Start with base 11

    # Source 4: Postmortem reviews linked to trades
    cur.execute("""
        SELECT ptr.id, ptr.paper_trade_id, ptr.tier, LEFT(ptr.review_text, 200) as review,
               pt.symbol, pt.strategy_id
        FROM paper_trade_multi_reviews ptr
        JOIN paper_trades pt ON pt.id = ptr.paper_trade_id
        WHERE ptr.review_text IS NOT NULL AND ptr.review_text != ''
          AND ptr.review_text ILIKE '%%stop%%'
    """)
    for row in cur.fetchall():
        rid, tid, tier, review, sym, sid = row
        candidates.append({
            "source_type": "postmortem",
            "source_id": tid,
            "strategy": sid,
            "symbol": sym,
            "lesson_type": "stop_rule_review",
            "lesson_summary": f"Postmortem ({tier}) for {sym} ({sid}): {(review or '')[:80]}",
            "evidence_count": 1,
            "sample_size": 1,
            "confidence": 0.5,
            "proposed_change": "Review stop placement rules for this strategy",
            "proposed_change_type": "stop_rule_review",
            "risk_level": "MEDIUM",
            "no_live_mutation": True,
        })

    # Source 5: Strategies with no closed trades (untested)
    cur.execute("""
        SELECT DISTINCT strategy_id FROM strategy_backtest_trades
        WHERE strategy_id IS NOT NULL AND strategy_id != '' AND strategy_id != 'unknown'
        EXCEPT
        SELECT DISTINCT strategy_id FROM paper_trades WHERE status = 'closed' AND strategy_id IS NOT NULL
    """)
    untested = [r[0] for r in cur.fetchall()]
    for sid in untested[:5]:
        candidates.append({
            "source_type": "coverage_gap",
            "source_id": None,
            "strategy": sid,
            "symbol": None,
            "lesson_type": "sample_size_insufficient",
            "lesson_summary": f"Strategy {sid} has backtest data but ZERO closed paper trades. Cannot validate live performance.",
            "evidence_count": 0,
            "sample_size": 0,
            "confidence": 0.3,
            "proposed_change": "Need live trade data before trusting backtest parameters",
            "proposed_change_type": "observation",
            "risk_level": "LOW",
            "no_live_mutation": True,
        })

    # Source 6: Exit time gaps (learning completeness)
    cur.execute("""
        SELECT COUNT(*) FROM paper_trades
        WHERE status = 'closed' AND exit_time IS NULL AND closed_at IS NOT NULL
    """)
    missing_exit_time = cur.fetchone()[0]
    if missing_exit_time > 0:
        candidates.append({
            "source_type": "journal_completeness",
            "source_id": None,
            "strategy": None,
            "symbol": None,
            "lesson_type": "data_quality",
            "lesson_summary": f"exit_time missing on {missing_exit_time} closed trades. Cannot compute accurate hold periods or post-exit analysis.",
            "evidence_count": missing_exit_time,
            "sample_size": missing_exit_time,
            "confidence": 0.8,
            "proposed_change": "Ensure exit_time is written at trade close",
            "proposed_change_type": "instrumentation",
            "risk_level": "MEDIUM",
            "no_live_mutation": True,
        })

    conn.close()

    # Deduplicate by lesson_summary hash
    seen = set()
    deduped = []
    for c in candidates:
        key = f"{c['lesson_type']}:{c.get('strategy')}:{c.get('symbol')}"
        if key not in seen:
            seen.add(key)
            deduped.append(c)

    return deduped
