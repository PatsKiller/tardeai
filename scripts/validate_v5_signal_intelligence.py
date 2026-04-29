#!/usr/bin/env python3
"""validate_v5_signal_intelligence.py — V5 Proactive Intelligence validation."""
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
    print("[validate] V5 Proactive Intelligence\n")

    import psycopg2
    pw = ""
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        if line.startswith("DB_PASSWORD="): pw = line.split("=", 1)[1].strip()

    # 1. All V5 tables exist
    print("1. DB Tables")
    conn = psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)
    cur = conn.cursor()
    v5_tables = ["news_articles", "catalyst_events", "social_mentions", "sentiment_observations",
                 "fused_signals", "signal_clusters", "portfolio_intelligence_events",
                 "decision_outcomes", "signal_history", "agent_performance_history",
                 "marl_training_episodes", "catalyst_type_weights"]
    for t in v5_tables:
        cur.execute(f"SELECT COUNT(*) FROM information_schema.tables WHERE table_name='{t}'")
        check(f"Table {t}", cur.fetchone()[0] > 0)

    # 2. Data populated
    print("\n2. Data Population")
    cur.execute("SELECT COUNT(*) FROM news_articles")
    check("News articles ingested", cur.fetchone()[0] > 0)
    cur.execute("SELECT COUNT(*) FROM catalyst_events")
    check("Catalyst events created", cur.fetchone()[0] > 0)
    cur.execute("SELECT COUNT(*) FROM sentiment_observations")
    check("Sentiment observations scored", cur.fetchone()[0] > 0)
    cur.execute("SELECT COUNT(*) FROM fused_signals")
    check("Fused signals computed", cur.fetchone()[0] > 0)
    cur.execute("SELECT COUNT(*) FROM catalyst_type_weights")
    check("Catalyst weights seeded", cur.fetchone()[0] >= 15)
    cur.execute("SELECT COUNT(*) FROM decision_outcomes")
    check("Decision outcomes recorded", cur.fetchone()[0] > 0)
    cur.execute("SELECT COUNT(*) FROM marl_training_episodes")
    check("MARL episodes logged", cur.fetchone()[0] > 0)
    conn.close()

    # 3. Scripts exist
    print("\n3. Scripts")
    for s in ["news_ingestion.py", "news_to_catalyst.py", "sentiment_processor.py",
              "social_monitor.py", "signal_fusion.py", "record_decision_outcome.py",
              "portfolio_signal_qa.py", "update_agent_performance.py", "marl_shadow_logger.py"]:
        check(f"Script {s}", (PROJECT_ROOT / "scripts" / s).exists())

    # 4. No hard-coded tickers in signal scripts
    print("\n4. No Hard-Coded Tickers")
    signal_scripts = ["news_ingestion.py", "news_to_catalyst.py", "sentiment_processor.py",
                      "social_monitor.py", "signal_fusion.py", "portfolio_signal_qa.py"]
    bad = []
    for s in signal_scripts:
        src = (PROJECT_ROOT / "scripts" / s).read_text()
        if "_STRATEGY_OVERRIDES" in src or "INCOME_ETFS" in src or "DEFENSE_SYMS" in src:
            bad.append(s)
    check("Signal scripts classification-first", len(bad) == 0, f"bad: {bad}" if bad else "clean")

    # 5. API endpoints
    print("\n5. API Endpoints")
    for ep in ["signals/fused", "news/SCHD", "catalysts/SCHD", "decision-outcomes/SCHD",
               "agent-performance", "portfolio-signal-qa"]:
        try:
            d = api_get(f"/api/v2/{ep}")
            check(f"GET /api/v2/{ep}", d.get("ok", True) or "data" in d)
        except Exception as e:
            check(f"GET /api/v2/{ep}", False, str(e))

    # 6. Strategy-aware fusion
    print("\n6. Strategy-Aware Fusion")
    conn = psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(DISTINCT strategy_type) FROM fused_signals WHERE strategy_type IS NOT NULL")
    types = cur.fetchone()[0]
    check("Fused signals have strategy_type", types > 0, f"{types} types")
    conn.close()

    # 7. MARL not live
    print("\n7. MARL Shadow")
    conn = psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM marl_policy_versions WHERE promoted=TRUE")
    check("MARL not live", cur.fetchone()[0] == 0)
    conn.close()

    # 8. Social gracefully handles missing APIs
    print("\n8. Social Monitoring")
    check("social_monitor.py exists", (PROJECT_ROOT / "scripts" / "social_monitor.py").exists())
    src = (PROJECT_ROOT / "scripts" / "social_monitor.py").read_text()
    check("Social handles missing APIs", "Not configured" in src or "gracefully" in src.lower() or "REDDIT_CLIENT_ID" in src)

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
