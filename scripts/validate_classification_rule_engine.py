#!/usr/bin/env python3
"""validate_classification_rule_engine.py — Phase 15: Classification Rule Engine validation."""
import json, os, sys, urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
API_BASE = "http://localhost:7777"
RESULTS = []
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


def check(name, passed, detail=""):
    RESULTS.append({"name": name, "passed": passed, "detail": detail})
    print(f"  {chr(0x2713) if passed else chr(0x2717)} {name}{(' — ' + detail) if detail else ''}")


def api_get(path):
    r = urllib.request.urlopen(urllib.request.Request(f"{API_BASE}{path}", headers={"User-Agent": "validate/1.0"}), timeout=10)
    return json.loads(r.read())


def main():
    print("[validate] Classification Rule Engine\n")

    # 1. Schema
    print("1. DB Tables")
    try:
        import psycopg2
        pw = ""
        for line in (PROJECT_ROOT / ".env").read_text().splitlines():
            if line.startswith("DB_PASSWORD="): pw = line.split("=", 1)[1].strip()
        conn = psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)
        cur = conn.cursor()
        for t in ['strategy_registry', 'ticker_strategy_classifications', 'ticker_classification_history',
                  'strategy_group_caps', 'strategy_rule_sets', 'strategy_rule_evaluations',
                  'agent_classification_suggestions', 'agent_conflicts',
                  'marl_policy_versions', 'marl_suggestions', 'marl_training_episodes']:
            cur.execute(f"SELECT COUNT(*) FROM information_schema.tables WHERE table_name='{t}'")
            exists = cur.fetchone()[0] > 0
            check(f"Table {t}", exists)
        cur.execute("SELECT COUNT(*) FROM strategy_registry")
        check("Strategy registry has 15 types", cur.fetchone()[0] >= 15)
        cur.execute("SELECT COUNT(*) FROM ticker_strategy_classifications WHERE active=TRUE")
        cnt = cur.fetchone()[0]
        check("Classifications seeded", cnt >= 40, f"{cnt} classifications")
        cur.execute("SELECT COUNT(*) FROM strategy_group_caps")
        check("Group caps seeded", cur.fetchone()[0] >= 6)
        cur.execute("SELECT COUNT(*) FROM strategy_rule_sets WHERE active=TRUE")
        check("Composite rules seeded", cur.fetchone()[0] >= 10)
        conn.close()
    except Exception as e:
        check("Schema", False, str(e))

    # 2. No hard-coded ticker logic in rule engine
    print("\n2. No Hard-Coded Tickers in Engine")
    try:
        src = (PROJECT_ROOT / "scripts" / "strategy_rule_engine.py").read_text()
        # Check that no ticker symbol sets exist as executable logic
        bad_patterns = ["INCOME_ETFS", "DEFENSE_SYMS", "_STRATEGY_OVERRIDES", "LAYER_MAP", "KNOWN_DIVIDENDS"]
        found = [p for p in bad_patterns if p in src]
        check("No hard-coded ticker sets in rule engine", len(found) == 0, f"found: {found}" if found else "clean")
    except Exception as e:
        check("Hard-coded check", False, str(e))

    # 3. Classification-first evaluation
    print("\n3. Classification-First Evaluation")
    try:
        from strategy_rule_engine import classify_symbol, evaluate_strategy_rules
        c = classify_symbol("SCHD")
        check("SCHD classified via DB", c is not None and c["strategy_type"] == "dividend_growth_compounder")

        r = evaluate_strategy_rules("SCHD")
        check("SCHD evaluates via classification", r["strategy_type"] == "dividend_growth_compounder")
        check("SCHD has prohibited actions", len(r["prohibited_actions"]) > 0, str(r["prohibited_actions"][:3]))

        # JEPI through covered_call_income
        c2 = classify_symbol("JEPI")
        check("JEPI = covered_call_income", c2 is not None and c2["strategy_type"] == "covered_call_income")

        # PFLT through high_yield_income_bdc
        c3 = classify_symbol("PFLT")
        check("PFLT = high_yield_income_bdc", c3 is not None and c3["strategy_type"] == "high_yield_income_bdc")

        # RKLB through speculative_growth
        c4 = classify_symbol("RKLB")
        check("RKLB = speculative_growth", c4 is not None and c4["strategy_type"] == "speculative_growth")

        # Defense through classification
        c5 = classify_symbol("RTX")
        check("RTX = defense_thesis", c5 is not None and c5["strategy_type"] == "defense_thesis")
    except Exception as e:
        check("Classification evaluation", False, str(e))

    # 4. Unknown symbol handling
    print("\n4. Unknown Symbol")
    try:
        r = evaluate_strategy_rules("COMPLETELY_FAKE_TICKER_XYZ")
        check("Unknown = CLASSIFICATION_REQUIRED", r["baseline_action"] == "CLASSIFICATION_REQUIRED")
        check("Unknown requires human review", r["human_review_required"] == True)
    except Exception as e:
        check("Unknown symbol", False, str(e))

    # 5. Agent classification
    print("\n5. Agent Classification")
    try:
        from strategy_rule_engine import propose_classification
        propose_classification("TEST_AGENT_CLASS", "speculative_growth", agent="maria", confidence=0.6, rationale="test")
        import psycopg2
        pw = ""
        for line in (PROJECT_ROOT / ".env").read_text().splitlines():
            if line.startswith("DB_PASSWORD="): pw = line.split("=", 1)[1].strip()
        conn = psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)
        cur = conn.cursor()
        cur.execute("SELECT status FROM agent_classification_suggestions WHERE symbol='TEST_AGENT_CLASS' ORDER BY created_at DESC LIMIT 1")
        r = cur.fetchone()
        check("Agent suggestion stored", r is not None and r[0] == "pending", f"status={r[0] if r else '?'}")
        # Low confidence should NOT auto-accept
        c = classify_symbol("TEST_AGENT_CLASS")
        check("Low confidence not auto-accepted", c is None)
        # Cleanup
        cur.execute("DELETE FROM agent_classification_suggestions WHERE symbol='TEST_AGENT_CLASS'")
        conn.commit()
        conn.close()
    except Exception as e:
        check("Agent classification", False, str(e))

    # 6. API endpoints
    print("\n6. API Endpoints")
    try:
        d = api_get("/api/v2/classifications")
        check("GET /api/v2/classifications", d.get("data", d).get("count", 0) >= 40)
    except Exception as e:
        check("Classifications API", False, str(e))

    try:
        d = api_get("/api/v2/classifications/SCHD")
        c = d.get("data", d).get("classification", {})
        check("GET /api/v2/classifications/SCHD", c.get("strategy_type") == "dividend_growth_compounder")
    except Exception as e:
        check("Classification detail", False, str(e))

    try:
        d = api_get("/api/v2/strategy-rules")
        check("GET /api/v2/strategy-rules", d.get("data", d).get("count", 0) > 0)
    except Exception as e:
        check("Strategy rules", False, str(e))

    # 7. MARL tables exist but not live
    print("\n7. MARL Shadow Mode")
    try:
        import psycopg2
        pw = ""
        for line in (PROJECT_ROOT / ".env").read_text().splitlines():
            if line.startswith("DB_PASSWORD="): pw = line.split("=", 1)[1].strip()
        conn = psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM marl_policy_versions")
        check("MARL tables exist", True)
        check("MARL not live (0 policies)", cur.fetchone()[0] == 0)
        conn.close()
    except Exception as e:
        check("MARL", False, str(e))

    # 8. Research card includes classification
    print("\n8. Research Card Integration")
    try:
        d = api_get("/api/v2/watchlist/research-card/SCHD")
        data = d.get("data", d)
        sr = data.get("strategy_rules", {})
        check("Research card has strategy_rules", sr.get("strategy_type") == "dividend_growth_compounder")
    except Exception as e:
        check("Research card", False, str(e))

    # Summary
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
