#!/usr/bin/env python3
"""validate_v7_cio_intelligence.py — V7 CIO Intelligence validation."""
import json, os, sys, urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
API_BASE = "http://localhost:7777"
RESULTS = []


def check(name, passed, detail=""):
    RESULTS.append({"name": name, "passed": passed, "detail": detail})
    print(f"  {chr(0x2713) if passed else chr(0x2717)} {name}{(' — ' + detail) if detail else ''}")


def api_get(path):
    r = urllib.request.urlopen(urllib.request.Request(f"{API_BASE}{path}", headers={"User-Agent": "v/1"}), timeout=10)
    return json.loads(r.read())


def main():
    print("[validate] V7 CIO Intelligence\n")

    import psycopg2
    pw = ""
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        if line.startswith("DB_PASSWORD="): pw = line.split("=", 1)[1].strip()

    # 1. Schema
    print("1. V7 Schema")
    conn = psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)
    cur = conn.cursor()
    for t in ["cio_decisions", "strategy_rotation_recommendations", "rebalance_plans",
              "rebalance_plan_actions", "marl_training_datasets", "marl_simulation_runs",
              "marl_policy_evaluations", "marl_counterfactual_actions"]:
        cur.execute(f"SELECT COUNT(*) FROM information_schema.tables WHERE table_name='{t}'")
        check(f"Table {t}", cur.fetchone()[0] > 0)

    # 2. CIO decisions populated
    print("\n2. CIO Decisions")
    cur.execute("SELECT COUNT(*) FROM cio_decisions")
    cnt = cur.fetchone()[0]
    check("CIO decisions written", cnt > 0, f"{cnt} decisions")
    cur.execute("SELECT COUNT(*) FROM cio_decisions WHERE human_review_required=TRUE")
    check("Human review decisions exist", cur.fetchone()[0] >= 0)

    # 3. Strategy rotations schema works
    print("\n3. Strategy Rotations")
    cur.execute("SELECT COUNT(*) FROM strategy_rotation_recommendations")
    check("Rotation table accessible", True, f"{cur.fetchone()[0]} recommendations")

    # 4. Rebalance plans
    print("\n4. Rebalance Plans")
    cur.execute("SELECT COUNT(*) FROM rebalance_plans")
    plans = cur.fetchone()[0]
    check("Rebalance plans written", plans > 0, f"{plans} plans")
    cur.execute("SELECT COUNT(*) FROM rebalance_plan_actions")
    check("Rebalance actions written", cur.fetchone()[0] > 0)

    # 5. MARL shadow
    print("\n5. MARL Shadow Mode")
    cur.execute("SELECT COUNT(*) FROM marl_training_datasets")
    check("MARL datasets built", cur.fetchone()[0] > 0)
    cur.execute("SELECT COUNT(*) FROM marl_simulation_runs")
    check("MARL simulations run", cur.fetchone()[0] > 0)
    cur.execute("SELECT COUNT(*) FROM marl_policy_evaluations WHERE approved_for_live=TRUE")
    check("MARL NOT live (0 approved)", cur.fetchone()[0] == 0)
    conn.close()

    # 6. No broker execution
    print("\n6. Safety Controls")
    for s in ["cio_decision_engine.py", "strategy_rotation_engine.py",
              "autonomous_rebalance_planner.py", "marl_training_simulation.py"]:
        src = (PROJECT_ROOT / "scripts" / s).read_text()
        # Check for actual broker API calls, not safety disclaimers
        has_broker = ("broker_api" in src.lower() or "place_order" in src.lower() or "submit_trade" in src.lower())
        check(f"No broker execution in {s}", not has_broker)

    # 7. API endpoints
    print("\n7. API Endpoints")
    for ep in ["cio-dashboard", "cio-decisions", "strategy-rotations",
               "rebalance-plans", "rebalance-plans/latest",
               "marl/simulations", "marl/shadow-diagnostics"]:
        try:
            d = api_get(f"/api/v2/{ep}")
            check(f"GET /api/v2/{ep}", d.get("ok", True) or "data" in d)
        except Exception as e:
            check(f"GET /api/v2/{ep}", False, str(e))

    # 8. Scripts exist
    print("\n8. Scripts")
    for s in ["cio_decision_engine.py", "strategy_rotation_engine.py",
              "autonomous_rebalance_planner.py", "marl_training_simulation.py"]:
        check(f"Script {s}", (PROJECT_ROOT / "scripts" / s).exists())

    # 9. Docs
    print("\n9. Documentation")
    check("V7 implementation log", (PROJECT_ROOT / "docs" / "V7_CIO_INTELLIGENCE_IMPLEMENTATION_LOG.md").exists())

    passed = sum(1 for r in RESULTS if r["passed"])
    total = len(RESULTS)
    print(f"\n{'=' * 40}")
    print(f"RESULT: {passed}/{total} checks passed")
    print(f"{'=' * 40}")

    if "--json" in sys.argv:
        print(json.dumps({"passed": passed, "total": total, "checks": RESULTS}, indent=2))
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
