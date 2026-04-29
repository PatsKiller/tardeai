#!/usr/bin/env python3
"""validate_synthesis_safety.py — Phase 14: Synthesis Safety validation."""
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
    print("[validate] Synthesis Safety Engine\n")

    # 1. Schema
    print("1. DB Schema")
    try:
        import psycopg2
        pw = ""
        for line in (PROJECT_ROOT / ".env").read_text().splitlines():
            if line.startswith("DB_PASSWORD="): pw = line.split("=", 1)[1].strip()
        conn = psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)
        cur = conn.cursor()
        cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='watchlist_final_synthesis' AND column_name='decision_safety'")
        check("decision_safety column exists", cur.fetchone() is not None)
        cur.execute("SELECT COUNT(*) FROM watchlist_synthesis_safety_history")
        check("safety_history table exists", True, f"{cur.fetchone()[0]} rows")
        conn.close()
    except Exception as e:
        check("Schema", False, str(e))

    # 2. SCHD safety
    print("\n2. SCHD Safety")
    try:
        from synthesis_safety import assess_synthesis_safety
        r = assess_synthesis_safety("SCHD")
        check("SCHD is unsafe", r["decision_safety"] == "unsafe", f"safety={r['decision_safety']}")
        check("SCHD not actionable", r["actionable_allowed"] == False)
        check("SCHD overridden to HOLD", r["recommendation_after"] == "HOLD", f"after={r['recommendation_after']}")
        check("SCHD has income_protection_override", any(s["rule"] == "income_protection_override" for s in r["safety_reasons"]))
        check("SCHD has missing_target_allocation", any(s["rule"] == "missing_target_allocation_for_trim" for s in r["safety_reasons"]))
        check("SCHD has income_gap_protection", any(s["rule"] == "income_gap_protection" for s in r["safety_reasons"]))
        check("SCHD has legacy_bad_synthesis_language", any(s["rule"] == "legacy_bad_synthesis_language" for s in r["safety_reasons"]))
        check("SCHD human_review_required", r["human_review_required"] == True)
    except Exception as e:
        check("SCHD safety", False, str(e))

    # 3. Income asset cannot trim solely on RSI
    print("\n3. Income RSI Protection")
    try:
        from synthesis_safety import assess_synthesis_safety
        # SCHD already tested — verify the rule exists
        r = assess_synthesis_safety("SCHD")
        has_tech_block = any(s["rule"] == "technical_only_income_decision" for s in r["safety_reasons"])
        has_rsi_protection = has_tech_block or any(s["rule"] == "income_protection_override" for s in r["safety_reasons"])
        check("Income RSI protection active", has_rsi_protection, "income_protection_override or technical_only")
    except Exception as e:
        check("RSI protection", False, str(e))

    # 4. API returns safety fields
    print("\n4. API Safety Fields")
    try:
        d = api_get("/api/v2/watchlist/research-card/SCHD")
        data = d.get("data", d)
        synth = data.get("synthesis", {})
        check("API returns decision_safety", synth.get("decision_safety") is not None, f"safety={synth.get('decision_safety')}")
        check("API returns safety_reasons", isinstance(synth.get("safety_reasons"), list), f"count={len(synth.get('safety_reasons', []))}")
        check("API returns safety_overrides", synth.get("safety_overrides") is not None)
        check("API synthesis actionable=false", synth.get("actionable") == False)
    except Exception as e:
        check("API safety", False, str(e))

    # 5. Decision QA respects safety
    print("\n5. QA Respects Safety")
    try:
        d = api_get("/api/v2/watchlist/research-card/SCHD")
        qa = d.get("data", d).get("decision_qa", {})
        check("QA reflects unsafe", qa.get("status") in ("unsafe", "needs_human_review"), f"status={qa.get('status')}")
        check("QA actionable=false", qa.get("actionable") == False)
    except Exception as e:
        check("QA safety", False, str(e))

    # 6. Daily report
    print("\n6. Daily Report")
    try:
        from generate_daily_intelligence_report import generate_report
        report = generate_report()
        check("Report has decision_safety", "decision_safety" in report, str(report.get("decision_safety")))
        check("Report has human_reviews", "human_reviews_required" in report, f"count={report.get('human_reviews_required')}")
        check("Report has income progress", "income" in report, f"current=${report.get('income',{}).get('current',0):,.0f}")
        check("Report has unsafe count", report.get("unsafe_decisions", 0) > 0, f"unsafe={report.get('unsafe_decisions')}")
    except Exception as e:
        check("Daily report", False, str(e))

    # 7. RTX
    print("\n7. RTX Status")
    try:
        from decision_qa import assess_symbol
        r = assess_symbol("RTX")
        check("RTX not actionable", r["actionable"] == False, f"status={r['decision_quality_status']}")
        check("RTX has conflicts", len(r["conflicts_detected"]) > 0, f"conflicts={len(r['conflicts_detected'])}")
    except Exception as e:
        check("RTX", False, str(e))

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
