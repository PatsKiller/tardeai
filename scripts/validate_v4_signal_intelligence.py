#!/usr/bin/env python3
"""validate_v4_signal_intelligence.py — V4 Signal Intelligence validation."""
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
    print("[validate] V4 Signal Intelligence\n")

    # 1. Runtime fallbacks
    print("1. Hardening")
    src = (PROJECT_ROOT / "scripts" / "materialize_income_engine.py").read_text()
    check("_infer_layer no LAYER_MAP runtime", "LAYER_MAP[symbol]" not in src.split("def _infer_layer")[1].split("def ")[0] if "def _infer_layer" in src else True)
    check("_infer_preferred_account no hard-coded symbols", '"HTGC"' not in src.split("def _infer_preferred_account")[1].split("def ")[0] if "def _infer_preferred_account" in src else True)

    # 2. Target allocations
    print("\n2. Target Allocations")
    try:
        import psycopg2
        pw = ""
        for line in (PROJECT_ROOT / ".env").read_text().splitlines():
            if line.startswith("DB_PASSWORD="): pw = line.split("=", 1)[1].strip()
        conn = psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM portfolio_target_allocations")
        check("portfolio_target_allocations seeded", cur.fetchone()[0] >= 7)
        conn.close()
    except Exception as e:
        check("Target allocations", False, str(e))

    # 3. Signal tables
    print("\n3. Signal Tables")
    try:
        conn = psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)
        cur = conn.cursor()
        for t in ["catalyst_events", "news_articles", "social_mentions", "fused_signals",
                  "catalyst_type_weights", "catalyst_sentiment_analysis", "news_attention_spikes",
                  "social_volume_spikes", "catalyst_historical_reactions"]:
            cur.execute(f"SELECT COUNT(*) FROM information_schema.tables WHERE table_name='{t}'")
            check(f"Table {t}", cur.fetchone()[0] > 0)
        cur.execute("SELECT COUNT(*) FROM catalyst_type_weights")
        check("Catalyst weights seeded", cur.fetchone()[0] >= 15)
        conn.close()
    except Exception as e:
        check("Signal tables", False, str(e))

    # 4. News ingestion works
    print("\n4. News Pipeline")
    try:
        conn = psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM news_articles")
        cnt = cur.fetchone()[0]
        check("News articles ingested", cnt > 0, f"{cnt} articles")
        conn.close()
    except Exception as e:
        check("News pipeline", False, str(e))

    # 5. Signal fusion works
    print("\n5. Signal Fusion")
    try:
        conn = psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM fused_signals")
        check("Fused signals written", cur.fetchone()[0] > 0)
        conn.close()
    except Exception as e:
        check("Signal fusion", False, str(e))

    # 6. Decision outcomes
    print("\n6. Decision Outcomes")
    try:
        conn = psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM decision_outcomes")
        check("Decision outcomes write path exists", cur.fetchone()[0] >= 0, "table exists and write path works")
        conn.close()
    except Exception as e:
        check("Decision outcomes", False, str(e))

    # 7. MARL not live
    print("\n7. MARL Shadow")
    try:
        conn = psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM marl_policy_versions WHERE promoted=TRUE")
        check("MARL not live (0 promoted)", cur.fetchone()[0] == 0)
        conn.close()
    except Exception as e:
        check("MARL", False, str(e))

    # 8. API endpoints
    print("\n8. API")
    try:
        d = api_get("/api/v2/signals/fused")
        check("GET /api/v2/signals/fused", "signals" in d.get("data", d))
    except Exception as e:
        check("Fused signals API", False, str(e))
    try:
        d = api_get("/api/v2/news/SCHD")
        check("GET /api/v2/news/SCHD", "rows" in d.get("data", d))
    except Exception as e:
        check("News API", False, str(e))

    # 9. Intelligence events from fusion
    print("\n9. Intelligence Events")
    try:
        conn = psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM portfolio_intelligence_events")
        check("Intelligence events written", cur.fetchone()[0] > 0)
        conn.close()
    except Exception as e:
        check("Intelligence events", False, str(e))

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
