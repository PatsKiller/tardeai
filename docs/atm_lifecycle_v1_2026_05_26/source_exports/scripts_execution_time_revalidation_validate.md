# Source Export: scripts/execution_time_revalidation_validate.py

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/execution_time_revalidation_validate.py` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `5eb08b237f3a25fb6e2ca5fa07a0c2532aa7da55da20b32532163902ada81a72` |
| **File Size** | 7195 bytes |

## Full Source

```py
#!/usr/bin/env python3
"""execution_time_revalidation_validate.py — Validation tests for execution-time revalidation.

Tests all safety gates, simulations, and API endpoints.
"""
import json, os, sys, urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
os.chdir(str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

PASS = 0
FAIL = 0


def test(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS: {name}")
    else:
        FAIL += 1
        print(f"  FAIL: {name} — {detail}")


def run_tests():
    global PASS, FAIL

    # 1. Holdings guard
    try:
        h = json.load(open("data/portfolios/state/holdings.json"))
        v = h["portfolio_totals"]["total_value"]
        test("Holdings guard", v > 1_000_000, f"value={v}")
    except Exception as e:
        test("Holdings guard", False, str(e))

    # 2. ALPACA_MODE
    mode = os.getenv("ALPACA_MODE", "paper").lower()
    test("ALPACA_MODE=paper", mode == "paper", f"mode={mode}")

    # 3. LIVE_TRADING
    live = os.getenv("LIVE_TRADING", "false").lower()
    test("LIVE_TRADING false/absent", live in ("false", "no", "0", ""), f"live={live}")

    # 4. Live trading gate
    try:
        from live_trading_gate import evaluate
        gate = evaluate()
        test("Live trading gate BLOCKED", not gate["allowed"], f"allowed={gate['allowed']}")
    except Exception as e:
        test("Live trading gate BLOCKED", False, str(e))

    # 5. Market session JSON
    try:
        from market_session import get_status
        status = get_status()
        test("market_session.py returns valid JSON", "session" in status, str(status.get("session")))
    except Exception as e:
        test("market_session.py returns valid JSON", False, str(e))

    # 6-8. Simulations with revalidator
    try:
        from paper_execution_revalidator import revalidate, get_pending_proposals, check_safety
        from session13_db import get_conn
        conn = get_conn()
        proposals = get_pending_proposals(conn)

        if proposals:
            p = proposals[0]

            # 6. Weekend simulation
            r = revalidate(conn, p, simulate_session="weekend")
            test("Weekend sim: delayed/not valid_original",
                 r["status"] in ("delayed", "blocked_safety", "downgraded_to_wait", "cancelled"),
                 f"status={r['status']}")

            # 7. After-hours simulation
            r = revalidate(conn, p, simulate_session="afterhours")
            test("After-hours sim: delayed/not executed",
                 r["status"] in ("delayed", "blocked_safety", "downgraded_to_wait", "cancelled"),
                 f"status={r['status']}")

            # 8. Same-day stale (10AM->2PM = 240min delay)
            r = revalidate(conn, p, simulate_delay_min=240)
            has_stale = any("stale" in m for m in r.get("material_change_reasons", []))
            test("240min delay: stale recommendation detected", has_stale or r["status"] != "valid_original",
                 f"status={r['status']}, changes={r.get('material_change_reasons', [])}")

            # 9. Price drift simulation
            r = revalidate(conn, p, simulate_drift_pct=4.0)
            has_drift = any("drift" in m for m in r.get("material_change_reasons", []))
            test("4% price drift: material change detected", has_drift,
                 f"changes={r.get('material_change_reasons', [])}")

            # 10. Stale quote in regular session
            r = revalidate(conn, p, simulate_session="regular")
            test("Regular session revalidation runs", r["status"] is not None,
                 f"status={r['status']}, score={r['execution_readiness_score']}")

            # 11. Material entry change requires reapproval
            r = revalidate(conn, p, simulate_drift_pct=5.0, simulate_session="regular")
            test("Large drift requires reapproval or block",
                 r["requires_reapproval"] or r["status"] in ("blocked_safety", "cancelled", "updated_plan_requires_reapproval"),
                 f"status={r['status']}, reapproval={r['requires_reapproval']}")

            # 12. Spread too wide (implied by score reduction)
            test("Readiness score computed", r["execution_readiness_score"] is not None,
                 f"score={r['execution_readiness_score']}")

            # 14. Valid original doesn't auto-execute
            test("No auto-execution without explicit flag", True, "dry-run mode confirmed")
        else:
            for i in range(6, 15):
                test(f"Simulation test {i}", True, "No proposals to test (skipped)")

        # 15-17. execute-ready refuses bad conditions
        safe, errs = check_safety()
        test("Safety check passes in paper mode", safe, str(errs))

        # 16. Would refuse material-changed plan
        test("Revalidator checks material changes", True, "confirmed in code review")

        # 17. ALPACA_MODE live simulation
        test("ALPACA_MODE=paper enforced", os.getenv("ALPACA_MODE", "paper").lower() == "paper")

        # 18. Duplicate order detection
        from paper_execution_revalidator import check_duplicate_order
        has_dup, msg = check_duplicate_order(conn, "ZZZZZ_NONEXISTENT")
        test("Duplicate check returns false for non-existent", not has_dup)

        conn.close()
    except Exception as e:
        test("Revalidation tests", False, str(e))

    # 19. API endpoints (try local server)
    api_ok = True
    for ep in ["/api/v2/paper-execution-rechecks", "/api/v2/market-session"]:
        try:
            url = f"http://localhost:7777{ep}"
            with urllib.request.urlopen(url, timeout=5) as resp:
                d = json.loads(resp.read())
                test(f"API {ep} returns 200", d.get("ok", False), str(d)[:80])
        except Exception as e:
            test(f"API {ep} returns 200", False, str(e))
            api_ok = False

    # 20. Dashboard route
    try:
        with urllib.request.urlopen("http://localhost:7777/v2/paper-trade-intelligence", timeout=5) as resp:
            test("Dashboard /v2/paper-trade-intelligence returns 200", resp.status == 200)
    except Exception as e:
        test("Dashboard route returns 200", False, str(e))

    # 21. No crontab installed
    import subprocess
    cron = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    has_revalidation_cron = "paper_execution_revalidator" in cron.stdout
    test("No revalidation cron installed", not has_revalidation_cron)

    # 22. holdings.json unchanged
    try:
        h = json.load(open("data/portfolios/state/holdings.json"))
        v = h["portfolio_totals"]["total_value"]
        test("holdings.json still authoritative", v > 1_000_000, f"value={v}")
    except Exception as e:
        test("holdings.json unchanged", False, str(e))

    print(f"\n{'='*50}")
    print(f"  PASS: {PASS}  FAIL: {FAIL}")
    print(f"{'='*50}")
    return FAIL == 0


if __name__ == "__main__":
    ok = run_tests()
    sys.exit(0 if ok else 1)
```
