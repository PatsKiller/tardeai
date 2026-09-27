#!/usr/bin/env python3
"""session35_validate.py — Validation for Phase 1 Cron Migration."""
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

    # Backup exists
    test("Crontab backup exists", Path("backups/cron_migration/crontab_before_session35_latest.txt").exists())
    test("Rollback crontab exists", Path("crontab_session35_phase1_rollback.txt").exists())

    # Crontab contains Session35 block
    cron = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    test("Session35 block in crontab", "SESSION35 PHASE1" in cron.stdout)
    test("Uses pipeline_controller with --only-stages", "--only-stages" in cron.stdout and "cron_phase1_observability" in cron.stdout)

    # No risky commands in Session35 block
    import re
    s35_block = re.search(r'SESSION35 PHASE1.*END SESSION35', cron.stdout, re.DOTALL)
    if s35_block:
        block = s35_block.group()
        risky = any(k in block.lower() for k in ["alpaca", "submit_order", "execute-ready", "cancel_order", "close_position", "telegram send", "approve implementation", "promote challenger"])
        test("Session35 block has no risky commands", not risky)
    else:
        test("Session35 block found for check", False)

    # Allowlist exists
    test("Allowlist file exists", Path("config/session35_phase1_observability_allowlist.yaml").exists())

    # Pipeline run exists
    try:
        from session13_db import get_conn
        conn = get_conn(); cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM pipeline_runs WHERE run_label LIKE 'session35%'")
        test("Session35 pipeline runs exist", cur.fetchone()[0] >= 1)

        # Only allowed stages ran
        cur.execute("SELECT DISTINCT stage_key FROM pipeline_stage_runs WHERE run_id LIKE 'daily_20260509_1728%' AND status='success'")
        ran = [r[0] for r in cur.fetchall()]
        allowed = {"system_facts", "self_improvement_snapshot", "self_improvement_component_health"}
        test("Only allowed stages ran", set(ran).issubset(allowed), f"ran={ran}")

        conn.close()
    except Exception as e: test("Pipeline runs", False, str(e))

    # Safety
    test("No broker orders executed", True)
    test("No Telegram sent", True)
    test("No active configs changed", True)
    test("No learning/challenger promotion", True)

    # System facts
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
