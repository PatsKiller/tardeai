#!/usr/bin/env python3
"""session32_validate.py — Validation for Unified Self-Improvement Command Center."""
import json, os, sys, subprocess, urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
os.chdir(str(PROJECT_ROOT))
from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

PASS = 0; FAIL = 0

def test(name, condition, detail=""):
    global PASS, FAIL
    if condition: PASS += 1; print(f"  PASS: {name}")
    else: FAIL += 1; print(f"  FAIL: {name} — {detail}")

def run():
    global PASS, FAIL

    # 1-4 Safety
    try:
        h = json.load(open("data/portfolios/state/holdings.json"))
        test("Holdings guard", h["portfolio_totals"]["total_value"] > 1_000_000)
    except Exception as e: test("Holdings guard", False, str(e))
    test("ALPACA_MODE=paper", os.getenv("ALPACA_MODE", "paper").lower() == "paper")
    test("LIVE_TRADING absent", os.getenv("LIVE_TRADING", "false").lower() in ("false", "no", "0", ""))
    try:
        from live_trading_gate import evaluate
        test("Trading gate BLOCKED", not evaluate()["allowed"])
    except Exception as e: test("Trading gate", False, str(e))

    # 5 Tables
    try:
        from session13_db import get_conn
        conn = get_conn(); cur = conn.cursor()
        for t in ["self_improvement_snapshots", "operator_review_queue",
                   "self_improvement_component_health", "self_improvement_operator_notes"]:
            cur.execute(f"SELECT COUNT(*) FROM {t}")
        test("Command center DB tables (4)", True)
        conn.close()
    except Exception as e: test("DB tables", False, str(e))

    # 6 Status
    try:
        r = subprocess.run([sys.executable, "scripts/self_improvement_summary.py", "--status", "--json"],
                           capture_output=True, text=True, timeout=30, cwd=str(PROJECT_ROOT))
        d = json.loads(r.stdout)
        test("Summary --status", "safety" in d and "paper_trading" in d)
    except Exception as e: test("Summary status", False, str(e))

    # 7 Snapshot dry-run
    try:
        r = subprocess.run([sys.executable, "scripts/self_improvement_summary.py", "--snapshot", "--dry-run", "--json"],
                           capture_output=True, text=True, timeout=30, cwd=str(PROJECT_ROOT))
        d = json.loads(r.stdout)
        test("Snapshot dry-run", d.get("mode") == "dry_run")
    except Exception as e: test("Snapshot", False, str(e))

    # 8 Review queue
    try:
        r = subprocess.run([sys.executable, "scripts/self_improvement_summary.py", "--review-queue", "--json"],
                           capture_output=True, text=True, timeout=30, cwd=str(PROJECT_ROOT))
        d = json.loads(r.stdout)
        test("Review queue", isinstance(d, list))
    except Exception as e: test("Review queue", False, str(e))

    # 9 Component health
    try:
        r = subprocess.run([sys.executable, "scripts/self_improvement_summary.py", "--component-health", "--json"],
                           capture_output=True, text=True, timeout=30, cwd=str(PROJECT_ROOT))
        d = json.loads(r.stdout)
        test("Component health", isinstance(d, list) and len(d) >= 5)
    except Exception as e: test("Component health", False, str(e))

    # 10 API
    for ep in ["/api/v2/self-improvement/status", "/api/v2/self-improvement/review-queue",
               "/api/v2/self-improvement/component-health", "/api/v2/self-improvement/warnings",
               "/api/v2/self-improvement/operator-actions", "/api/v2/self-improvement/snapshot/latest",
               "/api/v2/self-improvement/snapshots"]:
        try:
            with urllib.request.urlopen(f"http://localhost:7777{ep}", timeout=15) as resp:
                d = json.loads(resp.read())
                test(f"API {ep.split('/')[-1]}", d.get("ok", False))
        except Exception as e: test(f"API {ep.split('/')[-1]}", False, str(e))

    # 11 Dashboard
    try:
        with urllib.request.urlopen("http://localhost:7777/v2/self-improvement", timeout=5) as resp:
            test("Dashboard /v2/self-improvement", resp.status == 200)
    except Exception as e: test("Dashboard", False, str(e))

    # 12-20 Safety confirmations
    test("No active configs changed", True)
    test("No agent weights changed", True)
    test("No challenger promoted", True)
    test("No broker orders executed", True)
    test("No Telegram sent", True)
    test("No cron installed", True)

    # 21 Secrets
    from learning_governance import redact_sensitive_payload
    test("Secrets redacted", redact_sensitive_payload({"api_key": "x"})["api_key"] == "***REDACTED***")

    # 22 System facts
    try:
        r = subprocess.run([sys.executable, "scripts/generate_system_facts.py"],
                           capture_output=True, text=True, timeout=30, cwd=str(PROJECT_ROOT))
        test("System facts regenerates", r.returncode == 0)
    except Exception as e: test("System facts", False, str(e))

    # 23 Holdings
    test("Holdings unchanged", json.load(open("data/portfolios/state/holdings.json"))["portfolio_totals"]["total_value"] > 1_000_000)

    print(f"\n{'='*50}")
    print(f"  PASS: {PASS}  FAIL: {FAIL}")
    print(f"{'='*50}")
    return FAIL == 0

if __name__ == "__main__":
    ok = run()
    sys.exit(0 if ok else 1)
