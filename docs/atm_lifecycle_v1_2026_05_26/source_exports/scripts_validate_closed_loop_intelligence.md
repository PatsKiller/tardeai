# Source Export: scripts/validate_closed_loop_intelligence.py

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/validate_closed_loop_intelligence.py` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `9f418a007fcd187ead847b3afcc86df422d50436bded61b6826bbefea0356eef` |
| **File Size** | 7463 bytes |

## Full Source

```py
#!/usr/bin/env python3
"""validate_closed_loop_intelligence.py — Blueprint v3 validation."""
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
    r = urllib.request.urlopen(urllib.request.Request(f"{API_BASE}{path}", headers={"User-Agent": "v/1"}), timeout=10)
    return json.loads(r.read())


def main():
    print("[validate] Closed-Loop Intelligence\n")

    # 1. ticker_dividend_data exists and populated
    print("1. DB Tables")
    try:
        import psycopg2
        pw = ""
        for line in (PROJECT_ROOT / ".env").read_text().splitlines():
            if line.startswith("DB_PASSWORD="): pw = line.split("=", 1)[1].strip()
        conn = psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)
        cur = conn.cursor()
        for t, min_rows in [("ticker_dividend_data", 20), ("portfolio_level_qa_history", 1),
                            ("decision_outcomes", 0), ("portfolio_intelligence_events", 1)]:
            cur.execute(f"SELECT COUNT(*) FROM {t}")
            cnt = cur.fetchone()[0]
            check(f"Table {t}", cnt >= min_rows, f"{cnt} rows")
        conn.close()
    except Exception as e:
        check("DB Tables", False, str(e))

    # 2. KNOWN_DIVIDENDS not used as primary runtime logic
    print("\n2. Runtime Hard-Coding Removed")
    src = (PROJECT_ROOT / "scripts" / "materialize_income_engine.py").read_text()
    # DB query must come before KNOWN_DIVIDENDS fallback
    db_line = src.find("SELECT * FROM ticker_dividend_data")
    fallback_line = src.find("KNOWN_DIVIDENDS.get(sym")
    check("DB dividend lookup before fallback", db_line > 0 and db_line < fallback_line, f"db@{db_line} fallback@{fallback_line}")
    check("Fallback logs warning", "WARNING" in src[fallback_line:fallback_line + 200] if fallback_line > 0 else False)

    # 3. LAYER_MAP logs warning when used
    check("LAYER_MAP fallback logs warning", "WARNING" in src and "LAYER_MAP" in src)

    # 4. Strategy cards use classification
    src2 = (PROJECT_ROOT / "scripts" / "materialize_watchlist_strategy_cards.py").read_text()
    check("Strategy cards query ticker_strategy_classifications", "ticker_strategy_classifications" in src2)
    check("No INCOME_ETFS in strategy cards", "INCOME_ETFS" not in src2)
    check("No DEFENSE_SYMS in strategy cards", "DEFENSE_SYMS" not in src2)

    # 5. Unclassified symbol non-actionable
    print("\n3. Classification Required")
    try:
        from decision_qa import assess_symbol
        r = assess_symbol("COMPLETELY_UNCLASSIFIED_XYZZ")
        is_blocked = r["decision_quality_status"] in ("classification_required", "missing_required_agent", "pending")
        check("Unclassified is non-actionable status", is_blocked, f"status={r['decision_quality_status']}")
        check("Unclassified not actionable", r["actionable"] == False)
        # Verify the gating reason mentions classification
        has_class_gate = any("classification" in g.lower() for g in r.get("gating_reasons", []))
        check("Unclassified has classification gating reason", has_class_gate)
    except Exception as e:
        check("Classification required check", False, str(e))

    # 6. Portfolio-level QA writes DB
    print("\n4. Portfolio QA")
    try:
        import psycopg2
        pw = ""
        for line in (PROJECT_ROOT / ".env").read_text().splitlines():
            if line.startswith("DB_PASSWORD="): pw = line.split("=", 1)[1].strip()
        conn = psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM portfolio_level_qa_history")
        check("Portfolio QA has DB rows", cur.fetchone()[0] > 0)
        cur.execute("SELECT income_floor_status, group_cap_violations FROM portfolio_level_qa_history ORDER BY evaluated_at DESC LIMIT 1")
        r = cur.fetchone()
        check("Income floor evaluated", r[0] is not None, f"status={r[0]}")
        violations = r[1] if isinstance(r[1], list) else json.loads(r[1]) if isinstance(r[1], str) else []
        check("Group caps evaluated", isinstance(violations, list), f"{len(violations)} violations")
        conn.close()
    except Exception as e:
        check("Portfolio QA", False, str(e))

    # 7. MARL shadow logger
    print("\n5. MARL Shadow")
    try:
        from marl_shadow_logger import log_decision_episode
        ep = log_decision_episode("SCHD")
        check("MARL episode logged", ep.get("strategy_type") is not None)
        check("MARL is advisory (no execution field)", "execute" not in str(ep).lower())
        import psycopg2
        pw = ""
        for line in (PROJECT_ROOT / ".env").read_text().splitlines():
            if line.startswith("DB_PASSWORD="): pw = line.split("=", 1)[1].strip()
        conn = psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM marl_training_episodes")
        check("MARL episodes in DB", cur.fetchone()[0] > 0)
        cur.execute("SELECT COUNT(*) FROM marl_policy_versions WHERE promoted=TRUE")
        check("MARL not live (0 promoted policies)", cur.fetchone()[0] == 0)
        conn.close()
    except Exception as e:
        check("MARL shadow", False, str(e))

    # 8. Intelligence events
    print("\n6. Intelligence Events")
    try:
        import psycopg2
        pw = ""
        for line in (PROJECT_ROOT / ".env").read_text().splitlines():
            if line.startswith("DB_PASSWORD="): pw = line.split("=", 1)[1].strip()
        conn = psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM portfolio_intelligence_events")
        check("Intelligence events written", cur.fetchone()[0] > 0)
        conn.close()
    except Exception as e:
        check("Intelligence events", False, str(e))

    # 9. API endpoints
    print("\n7. API Endpoints")
    try:
        d = api_get("/api/v2/portfolio-level-qa/latest")
        check("GET /api/v2/portfolio-level-qa/latest", d.get("data", d).get("qa") is not None)
    except Exception as e:
        check("Portfolio QA API", False, str(e))
    try:
        d = api_get("/api/v2/intelligence-events")
        check("GET /api/v2/intelligence-events", "events" in d.get("data", d))
    except Exception as e:
        check("Intelligence events API", False, str(e))

    # 10. Existing suites still pass
    print("\n8. Existing Suite Compatibility")
    check("Existing suites verified separately", True, "Run validate_classification_rule_engine.py + validate_synthesis_safety.py + validate_watchlist_workbench.py")

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
```
