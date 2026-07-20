#!/usr/bin/env python3
"""generate_weekly_portfolio_review.py — DB-backed weekly CIO review."""
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

    cur.execute("SELECT action, COUNT(*) as cnt FROM cio_decisions WHERE created_at > NOW()-INTERVAL '7 days' GROUP BY action ORDER BY cnt DESC")
    decisions = cur.fetchall()
    # strategy_rotation_recommendations is created by migration 019 but NOTHING
    # writes it — the v7 CIO rotation engine was schema'd and never implemented
    # (verified 2026-07-20: 0 rows ever, 6 readers). Rendering a bare "0" reads
    # as "we evaluated rotations and found none needed", which is a claim the
    # system cannot support. Distinguish no-engine from no-recommendations.
    cur.execute("SELECT COUNT(*) as cnt FROM strategy_rotation_recommendations WHERE created_at > NOW()-INTERVAL '7 days'")
    rotations = cur.fetchone()["cnt"]
    cur.execute("SELECT COUNT(*) as cnt FROM strategy_rotation_recommendations")
    _rot_ever = cur.fetchone()["cnt"]
    rotations_label = (str(rotations) if _rot_ever
                       else "n/a (no rotation producer implemented)")
    cur.execute("SELECT agent, accuracy_pct FROM agent_performance_history ORDER BY created_at DESC LIMIT 5")
    agents = cur.fetchall()
    cur.execute("SELECT scope_value, actual_accuracy, calibration_error, recommendation FROM confidence_calibration_history ORDER BY calibration_date DESC LIMIT 8")
    calibrations = cur.fetchall()
    cur.execute("SELECT COUNT(*) as cnt FROM decision_outcomes WHERE evaluated_at > NOW()-INTERVAL '7 days'")
    outcomes = cur.fetchone()["cnt"]
    cur.execute("SELECT SUM(annual_income) as income FROM income_asset_profiles")
    income = float((cur.fetchone() or {}).get("income", 0) or 0)
    conn.close()

    report = {
        "period": "weekly",
        "decisions_this_week": [{k: v for k, v in d.items()} for d in decisions],
        "rotations": rotations,
        "outcomes_evaluated": outcomes,
        "income_annual": income,
        "agent_performance": [{k: v for k, v in a.items()} for a in agents],
        "calibration": [{k: str(v) for k, v in c.items()} for c in calibrations],
    }

    lines = ["*Weekly CIO Portfolio Review*", ""]
    lines.append(f"*Decisions*: {sum(d['cnt'] for d in decisions)} total")
    for d in decisions: lines.append(f"  {d['action']}: {d['cnt']}")
    lines.append(f"Rotations: {rotations_label} | Outcomes evaluated: {outcomes}")
    lines.append(f"Income: ${income:,.0f}/yr")
    if agents:
        lines.append("*Agent Performance*")
        for a in agents: lines.append(f"  {a['agent']}: {a['accuracy_pct']}%")
    print("\n".join(lines))
    return report

if __name__ == "__main__":
    r = generate()
    if "--json" in sys.argv: print(json.dumps(r, indent=2, default=str))
