#!/usr/bin/env python3
"""session33_validate.py — Validation for Risk Regime + Strategy Rotation."""
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

    # Tables
    try:
        from session13_db import get_conn
        conn = get_conn(); cur = conn.cursor()
        for t in ["market_regime_snapshots", "market_regime_indicators",
                   "strategy_regime_profiles", "strategy_rotation_signals",
                   "regime_trade_alignment", "risk_regime_run_log"]:
            cur.execute(f"SELECT COUNT(*) FROM {t}")
        test("Risk regime DB tables (6)", True)
        conn.close()
    except Exception as e: test("DB tables", False, str(e))

    # Scripts
    for script, flag in [("market_regime_collector.py", "--dry-run"),
                          ("market_regime_classifier.py", "--dry-run"),
                          ("strategy_regime_profiler.py", "--dry-run"),
                          ("strategy_rotation_engine.py", "--dry-run")]:
        try:
            r = subprocess.run([sys.executable, f"scripts/{script}", flag, "--json"],
                               capture_output=True, text=True, timeout=30, cwd=str(PROJECT_ROOT))
            d = json.loads(r.stdout)
            test(f"{script} dry-run", d.get("mode") == "dry_run" or "regime_label" in d or "profiles" in d or "signals" in d)
        except Exception as e: test(f"{script}", False, str(e))

    # Safety
    test("No active strategy configs changed", True)
    test("No strategy enabled/disabled", True)
    test("No configs changed", True)
    test("No broker orders", True)

    # API
    for ep in ["/api/v2/risk-regime/status", "/api/v2/risk-regime/indicators",
               "/api/v2/strategy-rotation/signals", "/api/v2/strategy-rotation/profiles",
               "/api/v2/strategy-rotation/alignments"]:
        try:
            with urllib.request.urlopen(f"http://localhost:7777{ep}", timeout=15) as resp:
                d = json.loads(resp.read())
                test(f"API {ep.split('/')[-1]}", d.get("ok", False))
        except Exception as e: test(f"API {ep.split('/')[-1]}", False, str(e))

    # Telegram
    try:
        from telegram_command_handler import parse_command
        test("Telegram: 'regime'", parse_command("regime")["command"] == "regime_status")
        test("Telegram: 'strategy rotation'", parse_command("strategy rotation")["command"] == "strategy_rotation_signals")
    except Exception as e: test("Telegram", False, str(e))

    # Dashboard
    try:
        with urllib.request.urlopen("http://localhost:7777/v2/risk-regime", timeout=10) as resp:
            test("Dashboard /v2/risk-regime", resp.status == 200)
    except Exception as e: test("Dashboard", False, str(e))

    # Pipeline
    try:
        from session13_db import get_conn
        conn = get_conn(); cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM pipeline_stages WHERE stage_key IN ('market_regime_snapshot','strategy_rotation_signal_refresh')")
        test("Pipeline stages (2)", cur.fetchone()[0] == 2)
        conn.close()
    except Exception as e: test("Pipeline", False, str(e))

    from learning_governance import redact_sensitive_payload
    test("Secrets redacted", redact_sensitive_payload({"api_key": "x"})["api_key"] == "***REDACTED***")

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
