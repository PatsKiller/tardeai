#!/usr/bin/env python3
"""autonomous_rebalance_planner.py — Draft rebalance plans. No broker execution.

Creates human-reviewable rebalance plans from CIO decisions + rotation recommendations.

STATUS (audit finding M3, docs/audits/CIO_PLATFORM_AUDIT_2026-08-27.md): not
scheduled anywhere — no cron or systemd entry exists for this script. It
reads exclusively from the `cio_decisions` table, which is populated only by
scripts/cio_decision_engine.py, whose own cron entry has been `# DISABLED`
since 2026-08-08. The platform's actual daily rebalance path
(scripts/portfolio_rebalancer.py, cron 15 7 * * 1-5) is independent of both
by deliberate operator decision (see docs/cio/ARCHITECTURE.md "Where CIO
Desk does not participate at all") — daily drift-alerting stays mechanical,
not CIO-gated, for latency/cost reasons. This script is therefore currently
dead code with no live input source, not "autonomous" in any operational
sense. Kept for its human-review-gated plan structure in case CIO-gated
rebalancing is revisited later; do not assume it runs.

Usage:
    python3 scripts/autonomous_rebalance_planner.py --run [--json]
    python3 scripts/autonomous_rebalance_planner.py --plan latest [--json]
"""
import json, os, sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"


def _get_conn():
    import psycopg2
    pw = ""
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        if line.startswith("DB_PASSWORD="): pw = line.split("=", 1)[1].strip()
    return psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)


def create_rebalance_plan() -> dict:
    """Create a draft rebalance plan from pending CIO decisions and rotations."""
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    plan_id = f"plan-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"

    # Get pending CIO decisions that suggest action
    cur.execute("""
        SELECT * FROM cio_decisions
        WHERE status = 'proposed' AND action NOT IN ('HOLD', 'BLOCKED')
        ORDER BY
            CASE priority WHEN 'critical' THEN 1 WHEN 'high' THEN 2 WHEN 'normal' THEN 3 ELSE 4 END,
            confidence_raw DESC
        LIMIT 20
    """)
    decisions = cur.fetchall()

    # Get pending rotation recommendations
    cur.execute("SELECT * FROM strategy_rotation_recommendations WHERE status='proposed' ORDER BY confidence DESC LIMIT 5")
    rotations = cur.fetchall()

    # Holdings for position sizing
    holdings = json.loads((STATE_DIR / "holdings.json").read_text()) if (STATE_DIR / "holdings.json").exists() else {}
    total_portfolio = sum(info.get("total_value", 0) for info in holdings.get("account_summaries", {}).values())

    # Income goals
    cur.execute("SELECT target_income FROM portfolio_income_goals LIMIT 1")
    goal = cur.fetchone()
    target_income = float(goal["target_income"]) if goal else 55000

    # Build plan actions
    actions = []
    total_trade_value = 0
    total_income_change = 0
    any_hr = False

    for d in decisions:
        sym = d["symbol"]
        action = d["action"]
        weight = float(d.get("expected_allocation_impact", 0) or 0)
        income = float(d.get("expected_income_impact", 0) or 0)

        # Get account info
        sym_holdings = [h for h in holdings.get("holdings", []) if h.get("symbol") == sym]
        account = sym_holdings[0].get("account_id", "unknown") if sym_holdings else "unknown"
        mv = sum(float(h.get("market_value", 0) or 0) for h in sym_holdings)

        # Estimate dollar amount (conservative: 10% of position for review actions)
        dollar_est = round(mv * 0.1, 0) if action in ("TRIM_REVIEW", "ADD_REVIEW") else 0
        hr = d.get("human_review_required", True)

        action_id = f"{plan_id}-{sym.lower()}"
        actions.append({
            "action_id": action_id,
            "symbol": sym,
            "account": account,
            "action": action,
            "dollar_amount": dollar_est,
            "reason": d.get("rationale", "")[:200],
            "source_decision_id": d["decision_id"],
            "safety_status": d.get("decision_safety", "pending"),
            "human_review_required": hr,
        })
        total_trade_value += dollar_est
        total_income_change += income if "ADD" in action else -income if "TRIM" in action else 0
        if hr:
            any_hr = True

    for rot in rotations:
        action_id = f"{plan_id}-rot-{rot['rotation_id'][-6:]}"
        dollar_est = round(total_portfolio * float(rot.get("rotation_amount_pct", 0) or 0) / 100, 0)
        actions.append({
            "action_id": action_id,
            "symbol": None,
            "account": None,
            "action": "ROTATION",
            "dollar_amount": dollar_est,
            "reason": rot.get("rationale", "")[:200],
            "source_rotation_id": rot["rotation_id"],
            "safety_status": "pending",
            "human_review_required": True,
        })
        total_trade_value += dollar_est
        any_hr = True

    # Persist plan
    summary = f"Draft plan: {len(actions)} actions, ${total_trade_value:,.0f} estimated trade value. {sum(1 for a in actions if a['human_review_required'])} need human review."
    cur.execute("""
        INSERT INTO rebalance_plans
            (plan_id, plan_status, total_trade_value, expected_income_change,
             plan_summary, human_review_required)
        VALUES (%s, 'draft', %s, %s, %s, %s)
    """, (plan_id, total_trade_value, total_income_change, summary[:500], any_hr))

    for a in actions:
        cur.execute("""
            INSERT INTO rebalance_plan_actions
                (action_id, plan_id, symbol, account, action, dollar_amount,
                 reason, source_decision_id, source_rotation_id, safety_status, human_review_required)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (a["action_id"], plan_id, a.get("symbol"), a.get("account"), a["action"],
              a["dollar_amount"], a.get("reason"), a.get("source_decision_id"),
              a.get("source_rotation_id"), a["safety_status"], a["human_review_required"]))

    conn.commit()
    conn.close()

    result = {
        "plan_id": plan_id,
        "actions": len(actions),
        "total_trade_value": total_trade_value,
        "income_change": total_income_change,
        "human_review_required": any_hr,
        "summary": summary,
    }
    print(f"[rebalance] {summary}")
    return result


if __name__ == "__main__":
    if "--run" in sys.argv:
        result = create_rebalance_plan()
        if "--json" in sys.argv:
            print(json.dumps(result, indent=2, default=str))
    elif "--plan" in sys.argv:
        import psycopg2.extras
        conn = _get_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM rebalance_plans ORDER BY generated_at DESC LIMIT 1")
        plan = cur.fetchone()
        if plan:
            cur.execute("SELECT * FROM rebalance_plan_actions WHERE plan_id=%s", (plan["plan_id"],))
            actions = cur.fetchall()
            print(json.dumps({"plan": dict(plan), "actions": [dict(a) for a in actions]}, indent=2, default=str))
        conn.close()
    else:
        print("Usage: --run [--json] | --plan latest [--json]")
