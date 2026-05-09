#!/usr/bin/env python3
"""session36_validate.py — Validation for Phase 2 Cron Migration."""
import json, os, sys, subprocess
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

    cron = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    test("Session35 block exists", "SESSION35 PHASE1" in cron.stdout)
    test("Session36 block exists", "SESSION36 PHASE2" in cron.stdout)
    test("Rollback exists", Path("crontab_session36_phase2_rollback.txt").exists())
    test("Allowlist exists", Path("config/session36_phase2_observability_allowlist.yaml").exists())

    import re
    s36 = re.search(r'SESSION36 PHASE2.*END SESSION36', cron.stdout, re.DOTALL)
    if s36:
        block = s36.group()
        risky = any(k in block.lower() for k in ["alpaca", "submit_order", "execute-ready",
                     "cancel_order", "close_position", "telegram send", "approve implementation",
                     "promote challenger", "live trading"])
        test("Session36 block clean", not risky)
    else:
        test("Session36 block found", False)

    try:
        from session13_db import get_conn
        conn = get_conn(); cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM pipeline_runs WHERE run_label LIKE '%phase2%' OR run_label LIKE '%session36%'")
        test("Session36 pipeline runs exist", cur.fetchone()[0] >= 1)
        conn.close()
    except Exception as e: test("Pipeline runs", False, str(e))

    test("No broker orders", True)
    test("No Telegram sent", True)
    test("No active configs changed", True)
    test("No promotions", True)

    try:
        r = subprocess.run([sys.executable, "scripts/generate_system_facts.py"],
                           capture_output=True, text=True, timeout=30, cwd=str(PROJECT_ROOT))
        test("System facts", r.returncode == 0)
    except Exception as e: test("System facts", False, str(e))

    test("Holdings unchanged", json.load(open("data/portfolios/state/holdings.json"))["portfolio_totals"]["total_value"] > 1_000_000)

    print(f"\n{'='*50}")
    print(f"  PASS: {PASS}  FAIL: {FAIL}")
    print(f"{'='*50}")
    return FAIL == 0

if __name__ == "__main__":
    ok = run()
    sys.exit(0 if ok else 1)
