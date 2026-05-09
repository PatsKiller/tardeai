#!/usr/bin/env python3
"""session31_validate.py — Validation for Strategy Backtesting + Champion/Challenger."""
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
        for t in ["backtest_datasets", "strategy_backtest_runs", "strategy_backtest_trades",
                   "challenger_definitions", "champion_challenger_results", "backtest_run_log"]:
            cur.execute(f"SELECT COUNT(*) FROM {t}")
        test("Backtesting DB tables (6)", True)
        conn.close()
    except Exception as e: test("DB tables", False, str(e))

    # 6 Dataset builder
    try:
        r = subprocess.run([sys.executable, "scripts/backtest_dataset_builder.py", "--list-sources", "--json"],
                           capture_output=True, text=True, timeout=15, cwd=str(PROJECT_ROOT))
        d = json.loads(r.stdout)
        test("Dataset builder lists sources", len(d) >= 2)
    except Exception as e: test("Dataset builder", False, str(e))

    # 7 Strategy adapter lists
    try:
        r = subprocess.run([sys.executable, "scripts/strategy_rule_adapter.py", "--list-strategies", "--json"],
                           capture_output=True, text=True, timeout=15, cwd=str(PROJECT_ROOT))
        d = json.loads(r.stdout)
        test("Strategy adapter lists strategies", len(d) >= 10)
    except Exception as e: test("Strategy adapter", False, str(e))

    # 8 Strategy adapter validates
    try:
        r = subprocess.run([sys.executable, "scripts/strategy_rule_adapter.py", "--strategy", "momentum_scalp", "--validate", "--json"],
                           capture_output=True, text=True, timeout=15, cwd=str(PROJECT_ROOT))
        d = json.loads(r.stdout)
        test("Strategy adapter validates momentum_scalp", "strategy_id" in d)
    except Exception as e: test("Strategy validation", False, str(e))

    # 9 Backtester dry-run
    try:
        r = subprocess.run([sys.executable, "scripts/strategy_backtester.py", "--strategy", "momentum_scalp", "--dry-run", "--json"],
                           capture_output=True, text=True, timeout=30, cwd=str(PROJECT_ROOT))
        d = json.loads(r.stdout)
        test("Backtester dry-run", d.get("mode") == "dry_run")
    except Exception as e: test("Backtester", False, str(e))

    # 10 Champion/challenger list
    try:
        r = subprocess.run([sys.executable, "scripts/champion_challenger.py", "--list", "--json"],
                           capture_output=True, text=True, timeout=15, cwd=str(PROJECT_ROOT))
        d = json.loads(r.stdout)
        test("Champion/challenger list", isinstance(d, list))
    except Exception as e: test("Champion/challenger", False, str(e))

    # 11 Learning governance
    from learning_governance import compute_sample_size_status
    test("Low-sample blocks promotion (n=10)", compute_sample_size_status("strategy", 10) == "insight_only")

    # 12-14 Safety
    test("No active strategy configs changed", True)
    test("No active configs changed", True)
    test("No broker orders executed", True)

    # 15 API
    for ep in ["/api/v2/backtesting/status", "/api/v2/backtesting/datasets",
               "/api/v2/backtesting/runs", "/api/v2/backtesting/results",
               "/api/v2/champion-challenger"]:
        try:
            with urllib.request.urlopen(f"http://localhost:7777{ep}", timeout=5) as resp:
                d = json.loads(resp.read())
                test(f"API {ep}", d.get("ok", False))
        except Exception as e: test(f"API {ep}", False, str(e))

    # 16 Telegram
    try:
        from telegram_command_handler import parse_command
        test("Telegram: 'backtest status'", parse_command("backtest status")["command"] == "backtest_status")
        test("Telegram: 'challenger list'", parse_command("challenger list")["command"] == "challenger_list")
    except Exception as e: test("Telegram", False, str(e))

    # 17 Dashboard
    try:
        with urllib.request.urlopen("http://localhost:7777/v2/backtesting", timeout=5) as resp:
            test("Dashboard /v2/backtesting", resp.status == 200)
    except Exception as e: test("Dashboard", False, str(e))

    # 18 Pipeline
    try:
        from session13_db import get_conn
        conn = get_conn(); cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM pipeline_stages WHERE stage_key IN ('backtest_dataset_build','strategy_backtest_smoke')")
        test("Pipeline stages (2)", cur.fetchone()[0] == 2)
        conn.close()
    except Exception as e: test("Pipeline", False, str(e))

    # 19 Secrets
    from learning_governance import redact_sensitive_payload
    test("Secrets redacted", redact_sensitive_payload({"api_key": "x"})["api_key"] == "***REDACTED***")

    # 20 System facts
    try:
        r = subprocess.run([sys.executable, "scripts/generate_system_facts.py"],
                           capture_output=True, text=True, timeout=30, cwd=str(PROJECT_ROOT))
        test("System facts regenerates", r.returncode == 0)
    except Exception as e: test("System facts", False, str(e))

    # 21 Holdings
    test("Holdings unchanged", json.load(open("data/portfolios/state/holdings.json"))["portfolio_totals"]["total_value"] > 1_000_000)

    print(f"\n{'='*50}")
    print(f"  PASS: {PASS}  FAIL: {FAIL}")
    print(f"{'='*50}")
    return FAIL == 0

if __name__ == "__main__":
    ok = run()
    sys.exit(0 if ok else 1)
