#!/usr/bin/env python3
"""generate_monthly_income_review.py — DB-backed monthly income + CIO review."""
import json, os, sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

def _get_conn():
    import psycopg2
    pw = ""
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        if line.startswith("DB_PASSWORD="): pw = line.split("=", 1)[1].strip()
    return psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)

def generate():
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("SELECT * FROM portfolio_income_goals LIMIT 1")
    goals = cur.fetchone() or {}
    cur.execute("SELECT * FROM income_projection_history ORDER BY snapshot_date DESC LIMIT 1")
    proj = cur.fetchone() or {}
    cur.execute("SELECT group_allocations FROM portfolio_level_qa_history ORDER BY evaluated_at DESC LIMIT 1")
    qa = cur.fetchone()
    allocs = qa.get("group_allocations", {}) if qa else {}
    cur.execute("SELECT COUNT(*) as cnt FROM cio_decisions WHERE created_at > NOW()-INTERVAL '30 days'")
    dec_count = cur.fetchone()["cnt"]
    cur.execute("SELECT COUNT(*) as cnt FROM marl_simulation_runs")
    marl_count = cur.fetchone()["cnt"]
    cur.execute("SELECT strategy_type, COUNT(*) as cnt FROM decision_outcomes WHERE created_at > NOW()-INTERVAL '30 days' GROUP BY strategy_type ORDER BY cnt DESC")
    outcomes_by_type = cur.fetchall()
    conn.close()

    report = {
        "period": "monthly",
        "income_current": float(proj.get("total_annual_income", 0) or 0),
        "income_target": float(goals.get("target_income", 55000)),
        "income_gap": float(proj.get("income_gap_to_target", 0) or 0),
        "target_pct": float(proj.get("target_goal_pct", 0) or 0),
        "group_allocations": allocs,
        "decisions_30d": dec_count,
        "marl_simulations": marl_count,
        "outcomes_by_strategy": [{k: v for k, v in o.items()} for o in outcomes_by_type],
    }

    lines = ["*Monthly Income + CIO Review*", ""]
    lines.append(f"Income: ${report['income_current']:,.0f}/yr ({report['target_pct']:.0f}% of ${report['income_target']:,.0f} target)")
    lines.append(f"Gap: ${report['income_gap']:,.0f}")
    lines.append(f"Decisions (30d): {dec_count} | MARL sims: {marl_count}")
    if outcomes_by_type:
        lines.append("*Outcomes by Strategy*")
        for o in outcomes_by_type: lines.append(f"  {o['strategy_type']}: {o['cnt']}")
    print("\n".join(lines))
    return report

if __name__ == "__main__":
    r = generate()
    if "--json" in sys.argv: print(json.dumps(r, indent=2, default=str))
