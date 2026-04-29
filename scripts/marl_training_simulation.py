#!/usr/bin/env python3
"""marl_training_simulation.py — MARL training dataset + simulation. Shadow-mode ONLY.

No live policy execution. No broker API. Research/simulation only.

Usage:
    python3 scripts/marl_training_simulation.py --build-dataset [--json]
    python3 scripts/marl_training_simulation.py --simulate [--json]
"""
import json, os, sys
from datetime import datetime, date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _get_conn():
    import psycopg2
    pw = ""
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        if line.startswith("DB_PASSWORD="): pw = line.split("=", 1)[1].strip()
    return psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)


def build_dataset() -> dict:
    """Build MARL training dataset from historical decisions + outcomes."""
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Collect decision outcomes with signal/research context
    cur.execute("""
        SELECT dout.symbol, dout.strategy_type, dout.recommendation, dout.price_at_decision,
               dout.price_7d, dout.outcome_score, dout.regret_score, dout.created_at,
               fs.fused_score, fs.catalyst_score, fs.news_score, fs.research_score,
               fs.severity as signal_severity,
               sre.baseline_action, sre.prohibited_actions
        FROM decision_outcomes dout
        LEFT JOIN LATERAL (
            SELECT fused_score, catalyst_score, news_score, research_score, severity
            FROM fused_signals WHERE symbol = dout.symbol ORDER BY created_at DESC LIMIT 1
        ) fs ON TRUE
        LEFT JOIN strategy_rule_evaluations sre ON sre.symbol = dout.symbol
        WHERE dout.price_7d IS NOT NULL
        ORDER BY dout.created_at DESC
    """)
    rows = cur.fetchall()

    dataset_id = f"ds-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
    features = []
    for r in rows:
        features.append({
            "symbol": r["symbol"],
            "strategy_type": r["strategy_type"],
            "action_taken": r["recommendation"],
            "price_at": float(r["price_at_decision"]) if r["price_at_decision"] else None,
            "price_7d": float(r["price_7d"]) if r["price_7d"] else None,
            "outcome": float(r["outcome_score"]) if r["outcome_score"] else 0,
            "regret": float(r["regret_score"]) if r["regret_score"] else 0,
            "fused_score": float(r.get("fused_score") or 0),
            "catalyst_score": float(r.get("catalyst_score") or 0),
            "news_score": float(r.get("news_score") or 0),
            "research_score": float(r.get("research_score") or 0),
            "signal_severity": r.get("signal_severity", "low"),
            "baseline_action": r.get("baseline_action"),
            "prohibited": r.get("prohibited_actions") or [],
        })

    # Persist dataset
    cur.execute("""
        INSERT INTO marl_training_datasets
            (dataset_id, row_count, start_date, end_date, feature_schema, source_tables, status)
        VALUES (%s, %s, %s, %s, %s, %s, 'shadow_only')
    """, (dataset_id, len(features),
          min(r["created_at"] for r in rows).date() if rows else date.today(),
          max(r["created_at"] for r in rows).date() if rows else date.today(),
          json.dumps({"fields": list(features[0].keys()) if features else []}, default=str),
          json.dumps(["decision_outcomes", "fused_signals", "strategy_rule_evaluations"], default=str)))

    conn.commit()
    conn.close()

    result = {"dataset_id": dataset_id, "rows": len(features), "status": "shadow_only"}
    print(f"[marl] Built dataset: {len(features)} rows (shadow_only)")
    return result


def simulate() -> dict:
    """Run counterfactual simulation on latest dataset."""
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Get latest dataset
    cur.execute("SELECT dataset_id FROM marl_training_datasets ORDER BY generated_at DESC LIMIT 1")
    ds = cur.fetchone()
    if not ds:
        conn.close()
        return {"error": "No dataset available. Run --build-dataset first."}

    # Get outcomes for counterfactual analysis
    cur.execute("""
        SELECT symbol, strategy_type, recommendation, outcome_score, regret_score
        FROM decision_outcomes WHERE price_7d IS NOT NULL
        ORDER BY created_at DESC LIMIT 100
    """)
    outcomes = cur.fetchall()

    sim_id = f"sim-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
    counterfactuals = 0
    total_regret = 0
    alt_actions = ["HOLD", "ADD_REVIEW", "TRIM_REVIEW"]

    for o in outcomes:
        actual = o["recommendation"]
        outcome = float(o["outcome_score"] or 0)
        regret = float(o["regret_score"] or 0)
        total_regret += regret

        # Simple counterfactual: if we had done HOLD instead
        if actual not in ("HOLD",) and regret > 2:
            cur.execute("""
                INSERT INTO marl_counterfactual_actions
                    (symbol, strategy_type, observed_action, marl_action,
                     rule_allowed, decision_qa_allowed, counterfactual_reward)
                VALUES (%s, %s, %s, 'HOLD', TRUE, TRUE, %s)
            """, (o["symbol"], o["strategy_type"], actual, round(-regret, 2)))
            counterfactuals += 1

    # Store simulation run
    cur.execute("""
        INSERT INTO marl_simulation_runs
            (simulation_id, dataset_id, policy_version, status, metrics, notes)
        VALUES (%s, %s, 'shadow_v1', 'completed', %s, %s)
    """, (sim_id, ds["dataset_id"],
          json.dumps({"outcomes_analyzed": len(outcomes), "counterfactuals": counterfactuals,
                      "total_regret": round(total_regret, 2), "avg_regret": round(total_regret / len(outcomes), 2) if outcomes else 0}, default=str),
          "Shadow-mode simulation. No live execution."))

    conn.commit()
    conn.close()

    result = {
        "simulation_id": sim_id,
        "outcomes_analyzed": len(outcomes),
        "counterfactuals": counterfactuals,
        "total_regret": round(total_regret, 2),
        "status": "shadow_only",
        "note": "MARL is shadow-mode only. No live execution.",
    }
    print(f"[marl] Simulation: {len(outcomes)} outcomes, {counterfactuals} counterfactuals, regret={total_regret:.1f} (shadow_only)")
    return result


if __name__ == "__main__":
    if "--build-dataset" in sys.argv:
        r = build_dataset()
        if "--json" in sys.argv: print(json.dumps(r, indent=2, default=str))
    elif "--simulate" in sys.argv:
        r = simulate()
        if "--json" in sys.argv: print(json.dumps(r, indent=2, default=str))
    else:
        print("Usage: --build-dataset [--json] | --simulate [--json]")
        print("NOTE: MARL is shadow-mode ONLY. No live policy execution.")
