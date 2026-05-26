# Source Export: scripts/validate_alert_intelligence.py

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/validate_alert_intelligence.py` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `adc6a1ce0dd8a5c4c825469b60da05aa9c89cf0fa45ab881fdd3dcae342cdc15` |
| **File Size** | 7600 bytes |

## Full Source

```py
#!/usr/bin/env python3
"""validate_alert_intelligence.py — Phase 12: Alert Intelligence Pipeline validation.

Usage:
    python3 scripts/validate_alert_intelligence.py [--json]
"""
import json, os, sys, urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
API_BASE = "http://localhost:7777"
RESULTS = []

sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


def check(name: str, passed: bool, detail: str = ""):
    RESULTS.append({"name": name, "passed": passed, "detail": detail})
    icon = "\u2713" if passed else "\u2717"
    print(f"  {icon} {name}{(' — ' + detail) if detail else ''}")


def api_get(path):
    req = urllib.request.Request(f"{API_BASE}{path}", headers={"User-Agent": "validate/1.0"})
    r = urllib.request.urlopen(req, timeout=10)
    return json.loads(r.read())


def main():
    print("[validate] Alert Intelligence Pipeline\n")

    # 1. DB table exists
    print("1. DB Tables")
    try:
        import psycopg2
        pw = ""
        for line in (PROJECT_ROOT / ".env").read_text().splitlines():
            if line.startswith("DB_PASSWORD="): pw = line.split("=", 1)[1].strip()
        conn = psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM alert_events")
        cnt = cur.fetchone()[0]
        check("alert_events table exists", True, f"{cnt} rows")
        cur.execute("SELECT COUNT(*) FROM alert_event_links")
        check("alert_event_links table exists", True)
        conn.close()
    except Exception as e:
        check("DB tables", False, str(e))

    # 2. Parser tests
    print("\n2. Parsers")
    try:
        from alert_event_writer import (
            parse_stop_triggered_text, parse_stop_brief_text,
            parse_staleness_alert_text, parse_portfolio_intelligence_text,
            parse_technical_signal_text, detect_data_integrity_issues,
        )

        # Stop triggered
        r = parse_stop_triggered_text("STOP TRIGGERED: RTX @ $174.26 — stop was $180.71 | Max loss: $-29")
        check("Parse stop_triggered", r.get("symbol") == "RTX" and r.get("price") == 174.26, f"sym={r.get('symbol')} price={r.get('price')}")

        # Stop brief zero
        r2 = parse_stop_brief_text("STOP BRIEF — RTX\nPrice: $0.00 | Stop: $0.00 | Gap: 0.0%")
        check("Parse stop_brief zero", r2.get("price") == 0.0, f"price={r2.get('price')} stop={r2.get('stop_price')}")

        # Data integrity detection on zero
        dq = detect_data_integrity_issues({"alert_type": "stop_brief", "price": 0.0, "stop_price": 0.0, "parsed_payload": {}})
        check("Detect zero price/stop", dq == "invalid_zero_price_or_stop", f"status={dq}")

        # Staleness
        r3 = parse_staleness_alert_text("Portfolio data is 61h old. Pipeline running.")
        check("Parse staleness", r3.get("parsed_payload", {}).get("age_hours") == 61, f"age={r3.get('parsed_payload', {}).get('age_hours')}")

        # Technical signal
        r4 = parse_technical_signal_text("JEPI crossed BELOW SMA200 ($57.36) ($57,320)")
        check("Parse technical_signal", r4.get("symbol") == "JEPI", f"sym={r4.get('symbol')}")
        check("Technical: indicator value vs position value",
              r4.get("price") == 57.36 and r4.get("position_value") == 57320.0,
              f"price={r4.get('price')} pos_val={r4.get('position_value')}")

        # Fidelity scale anomaly
        dq2 = detect_data_integrity_issues({"alert_type": "portfolio_intelligence", "parsed_payload": {"daily_change_pct": -23.3}, "symbol": "SP500-D"})
        check("Detect Fidelity scale anomaly", dq2 == "fidelity_scale_anomaly", f"status={dq2}")

    except Exception as e:
        check("Parsers", False, str(e))

    # 3. API endpoints
    print("\n3. API Endpoints")
    try:
        d = api_get("/api/v2/alerts")
        check("GET /api/v2/alerts", "alerts" in d.get("data", d), f"count={d.get('data', d).get('count', 0)}")
    except Exception as e:
        check("GET /api/v2/alerts", False, str(e))

    try:
        d = api_get("/api/v2/alerts/debug")
        dd = d.get("data", d)
        check("GET /api/v2/alerts/debug", "total" in dd, f"total={dd.get('total')}")
        check("Zero price errors tracked", "zero_price_errors" in dd, f"count={dd.get('zero_price_errors')}")
    except Exception as e:
        check("Alerts debug", False, str(e))

    try:
        d = api_get("/api/v2/symbol/RTX/timeline")
        dd = d.get("data", d)
        check("GET /api/v2/symbol/RTX/timeline", "alerts" in dd, f"alerts={len(dd.get('alerts', []))}")
        has_jobs = len(dd.get("jobs", [])) > 0
        check("RTX has auto-created agent jobs", has_jobs, f"jobs={len(dd.get('jobs', []))}")
        has_dq = len(dd.get("data_quality_warnings", [])) > 0
        check("RTX has data quality warnings", has_dq, f"warnings={len(dd.get('data_quality_warnings', []))}")
    except Exception as e:
        check("Symbol timeline", False, str(e))

    # 4. Research card includes alerts
    print("\n4. Research Card Alerts")
    try:
        d = api_get("/api/v2/watchlist/research-card/RTX")
        dd = d.get("data", d)
        has_alerts = len(dd.get("alerts", [])) > 0
        check("Research card has alerts", has_alerts, f"alerts={len(dd.get('alerts', []))}")
        check("Research card has data_quality_warned flag", "data_quality_warned" in dd,
              f"warned={dd.get('data_quality_warned')}")
    except Exception as e:
        check("Research card alerts", False, str(e))

    # 5. Alert writer module
    print("\n5. Alert Writer")
    try:
        from alert_event_writer import save_alert_event, check_synthesis_blocked
        check("save_alert_event importable", True)
        check("check_synthesis_blocked importable", True)

        # Test synthesis blocker
        blocked = check_synthesis_blocked("RTX")
        check("RTX synthesis DQ warned", blocked.get("warned") == True, f"warned={blocked.get('warned')} reason={blocked.get('reason')}")
    except Exception as e:
        check("Alert writer", False, str(e))

    # 6. Dual-write patches
    print("\n6. Dual-Write Patches")
    try:
        import inspect
        from stop_decision_brief import process_stop_alerts
        src = inspect.getsource(process_stop_alerts)
        check("stop_decision_brief dual-write", "save_alert_event" in src, "found in process_stop_alerts")
    except Exception as e:
        check("stop_decision_brief patch", False, str(e))

    try:
        import inspect
        # portfolio_alerts strategic
        from portfolio_alerts import run_portfolio_alerts
        src2 = inspect.getsource(run_portfolio_alerts)
        check("portfolio_alerts dual-write", "save_alert_event" in src2, "found in run_portfolio_alerts")
    except Exception as e:
        check("portfolio_alerts patch", False, str(e))

    # 7. JEPI formatting fix
    print("\n7. Formatting Fixes")
    try:
        src = (PROJECT_ROOT / "scripts" / "portfolio_alerts.py").read_text()
        check("Position value labeled", "Position: $" in src, "Found 'Position: $' label")
    except Exception as e:
        check("Formatting fix", False, str(e))

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
```
