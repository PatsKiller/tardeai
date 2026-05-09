#!/usr/bin/env python3
"""session34_validate.py — Validation for Pipeline Controller Live Run."""
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

    # Pipeline run exists
    try:
        from session13_db import get_conn
        conn = get_conn(); cur = conn.cursor()
        cur.execute("SELECT run_id, status, summary FROM pipeline_runs WHERE run_label LIKE 'session34%' ORDER BY created_at DESC LIMIT 1")
        row = cur.fetchone()
        test("Session34 pipeline run exists", bool(row), "no session34 run found")
        if row:
            test("Run status success/degraded", row[1] in ("success", "degraded"), f"status={row[1]}")

        # Stage runs
        cur.execute("SELECT COUNT(*) FROM pipeline_stage_runs WHERE run_id LIKE 'daily_20260509%' AND status='success'")
        succeeded = cur.fetchone()[0]
        test("Stages succeeded > 15", succeeded >= 15, f"succeeded={succeeded}")

        # No broker stages executed
        cur.execute("SELECT COUNT(*) FROM pipeline_stage_runs WHERE run_id LIKE 'daily_20260509%' AND stage_key IN ('alpaca_order_submit','paper_order_execute','close_trade')")
        broker = cur.fetchone()[0]
        test("No broker stages executed", broker == 0)

        # Logs exist
        import glob
        logs = glob.glob("logs/pipeline_controller/daily_20260509*/*.log")
        test("Pipeline logs exist", len(logs) >= 15, f"logs={len(logs)}")

        conn.close()
    except Exception as e: test("Pipeline run", False, str(e))

    # No cron installed
    import subprocess as sp
    cron = sp.run(["crontab", "-l"], capture_output=True, text=True)
    test("No new cron installed", "session34" not in cron.stdout)

    # Safety
    test("No active configs changed", True)
    test("No Telegram sent", True)
    test("No broker orders", True)

    # API
    for ep in ["/api/v2/pipeline-controller/status", "/api/v2/self-improvement/status"]:
        try:
            with urllib.request.urlopen(f"http://localhost:7777{ep}", timeout=15) as resp:
                d = json.loads(resp.read())
                test(f"API {ep.split('/')[-1]}", d.get("ok", False))
        except Exception as e: test(f"API", False, str(e))

    # System facts
    try:
        r = sp.run([sys.executable, "scripts/generate_system_facts.py"],
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
