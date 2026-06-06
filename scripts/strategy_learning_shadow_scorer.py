#!/usr/bin/env python3
"""
Strategy Learning Shadow Scorer.
Computes how learning candidates would affect candidate scoring
WITHOUT changing live GO/WAIT/NO GO decisions.
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

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


def shadow_score():
    """Compare live candidate scores against learning-adjusted shadow scores."""
    from extract_strategy_learning_candidates import extract_expanded_candidates

    # Get learning candidates
    learning = extract_expanded_candidates()

    # Build strategy penalty/boost map from learning
    strategy_adjustments = {}
    for lc in learning:
        sid = lc.get("strategy")
        if not sid:
            continue
        if sid not in strategy_adjustments:
            strategy_adjustments[sid] = {"penalties": [], "boosts": [], "warnings": []}

        if lc["lesson_type"] in ("stop_too_tight", "stop_rule_review"):
            strategy_adjustments[sid]["penalties"].append({
                "delta": -3,
                "reason": lc["lesson_summary"][:60],
                "lesson_type": lc["lesson_type"],
                "confidence": lc["confidence"],
            })
        elif lc["lesson_type"] == "weak_backtest":
            strategy_adjustments[sid]["penalties"].append({
                "delta": -5,
                "reason": lc["lesson_summary"][:60],
                "lesson_type": lc["lesson_type"],
                "confidence": lc["confidence"],
            })
        elif lc["lesson_type"] == "premature_exit":
            strategy_adjustments[sid]["warnings"].append({
                "delta": 0,
                "reason": lc["lesson_summary"][:60],
                "lesson_type": lc["lesson_type"],
                "confidence": lc["confidence"],
            })
        elif lc["lesson_type"] == "sample_size_insufficient":
            strategy_adjustments[sid]["warnings"].append({
                "delta": -2,
                "reason": f"No live trades for {sid} — cannot validate",
                "lesson_type": lc["lesson_type"],
                "confidence": lc["confidence"],
            })

    # Get latest candidates from trade_ai_scans
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT ON (symbol)
            symbol, score, decision, rvol, strategy_id, run_date
        FROM (
            SELECT symbol, score, decision, rvol,
                   COALESCE(
                     (SELECT strategy_type FROM ticker_strategy_classifications
                      WHERE symbol = tas.symbol LIMIT 1),
                     'unknown'
                   ) as strategy_id,
                   run_date
            FROM trade_ai_scans tas
            WHERE run_date >= CURRENT_DATE - 1 AND score >= 30
        ) sub
        ORDER BY symbol, score DESC
        LIMIT 30
    """)
    cols = [d[0] for d in cur.description]
    candidates = [dict(zip(cols, r)) for r in cur.fetchall()]
    conn.close()

    # Shadow score each candidate
    results = []
    for c in candidates:
        sid = c.get("strategy_id", "unknown")
        original = int(c.get("score", 0))
        adj = strategy_adjustments.get(sid, {"penalties": [], "boosts": [], "warnings": []})

        total_delta = sum(p["delta"] for p in adj["penalties"]) + sum(p["delta"] for p in adj["warnings"])
        shadow = max(0, original + total_delta)

        results.append({
            "symbol": c["symbol"],
            "strategy": sid,
            "original_score": original,
            "shadow_score": shadow,
            "delta": total_delta,
            "decision": c.get("decision"),
            "learning_adjustments": adj["penalties"] + adj["warnings"],
            "adjustment_count": len(adj["penalties"]) + len(adj["warnings"]),
            "sample_size_warning": any(w["lesson_type"] == "sample_size_insufficient" for w in adj["warnings"]),
            "not_live_decision": True,
        })

    # Classify
    boosted = sum(1 for r in results if r["delta"] > 0)
    penalized = sum(1 for r in results if r["delta"] < 0)
    unchanged = sum(1 for r in results if r["delta"] == 0)

    return {
        "timestamp": datetime.now().isoformat(),
        "candidates_scored": len(results),
        "boosted": boosted,
        "penalized": penalized,
        "unchanged": unchanged,
        "learning_candidates_used": len(learning),
        "strategies_with_adjustments": len(strategy_adjustments),
        "results": results,
        "not_live": True,
    }


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--json-out", type=str, default=None)
    args = ap.parse_args()

    output = shadow_score()
    # Step 5: persist shadow scores to DB (candidate_shadow_scores), keyed to the candidate. Best-effort.
    try:
        from persist_shadow_scores import persist as _persist_shadow
        _n = _persist_shadow(output)
        print(f"  Persisted {_n} shadow scores to candidate_shadow_scores")
    except Exception as _e:
        print(f"  (shadow DB persist skipped: {_e})")
    print(f"Shadow Scoring Results")
    print(f"  Candidates: {output['candidates_scored']}")
    print(f"  Boosted: {output['boosted']}")
    print(f"  Penalized: {output['penalized']}")
    print(f"  Unchanged: {output['unchanged']}")
    print(f"  Learning candidates used: {output['learning_candidates_used']}")
    print(f"\nTop deltas:")
    for r in sorted(output["results"], key=lambda x: x["delta"])[:10]:
        if r["delta"] != 0:
            print(f"  {r['symbol']:8s} {r['strategy']:25s} {r['original_score']:3d} → {r['shadow_score']:3d} ({r['delta']:+d}) adjustments={r['adjustment_count']}")

    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(json.dumps(output, indent=2, default=str))
        print(f"\nWritten to {args.json_out}")
