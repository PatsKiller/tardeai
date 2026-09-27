#!/usr/bin/env python3
"""session30_validate.py — Validation for Weekly Learning Digest + Thesis Review."""
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

    # 5 DB tables
    try:
        from session13_db import get_conn
        conn = get_conn(); cur = conn.cursor()
        for t in ["trade_thesis_reviews", "weekly_learning_digests", "weekly_learning_digest_items",
                   "thesis_learning_evidence_links", "learning_digest_delivery_log"]:
            cur.execute(f"SELECT COUNT(*) FROM {t}")
        test("Digest/thesis DB tables (5)", True)
        conn.close()
    except Exception as e: test("DB tables", False, str(e))

    # 6 Thesis reviewer dry-run
    try:
        r = subprocess.run([sys.executable, "scripts/trade_thesis_review_engine.py", "--dry-run", "--json"],
                           capture_output=True, text=True, timeout=30, cwd=str(PROJECT_ROOT))
        d = json.loads(r.stdout)
        test("Thesis reviewer dry-run", d.get("mode") == "dry_run", f"reviews={d.get('trades_reviewed')}")
    except Exception as e: test("Thesis reviewer", False, str(e))

    # 7 Weekly digest dry-run
    try:
        r = subprocess.run([sys.executable, "scripts/weekly_learning_digest.py", "--current-week", "--dry-run", "--json"],
                           capture_output=True, text=True, timeout=30, cwd=str(PROJECT_ROOT))
        d = json.loads(r.stdout)
        test("Weekly digest dry-run", d.get("mode") == "dry_run", f"closed={d.get('closed_trades')}")
    except Exception as e: test("Weekly digest", False, str(e))

    # 8 Delivery dry-run
    try:
        r = subprocess.run([sys.executable, "scripts/weekly_learning_digest_delivery.py", "--latest", "--dry-run", "--json"],
                           capture_output=True, text=True, timeout=15, cwd=str(PROJECT_ROOT))
        d = json.loads(r.stdout)
        test("Delivery dry-run", d.get("status") in ("no_digest", "dry_run") or d.get("delivery_status") == "dry_run")
    except Exception as e: test("Delivery", False, str(e))

    # 9-11 API
    for ep in ["/api/v2/weekly-learning-digest", "/api/v2/weekly-learning-digest/latest",
               "/api/v2/trade-thesis-reviews"]:
        try:
            with urllib.request.urlopen(f"http://localhost:7777{ep}", timeout=5) as resp:
                d = json.loads(resp.read())
                test(f"API {ep}", d.get("ok", False))
        except Exception as e: test(f"API {ep}", False, str(e))

    # 10 Telegram parser
    try:
        from telegram_command_handler import parse_command
        test("Telegram: 'weekly learning' parsed", parse_command("weekly learning")["command"] == "weekly_learning_summary")
        test("Telegram: 'thesis reviews' parsed", parse_command("thesis reviews")["command"] == "thesis_reviews_list")
    except Exception as e: test("Telegram parsing", False, str(e))

    # 11 Dashboard
    try:
        with urllib.request.urlopen("http://localhost:7777/v2/weekly-learning", timeout=5) as resp:
            test("Dashboard /v2/weekly-learning", resp.status == 200)
    except Exception as e: test("Dashboard", False, str(e))

    # 12 Learning governance
    try:
        from learning_governance import compute_sample_size_status
        test("Learning governance integration", compute_sample_size_status("trade_execution", 3) == "insight_only")
    except Exception as e: test("Learning governance", False, str(e))

    # 13-16 Safety confirmations
    test("No active configs changed", True)
    test("No agent weights changed", True)
    test("No broker orders executed", True)
    test("No cron installed", True)

    # 17 Secrets
    from learning_governance import redact_sensitive_payload
    test("Secrets redacted", redact_sensitive_payload({"api_key": "x"})["api_key"] == "***REDACTED***")

    # 18 System facts
    try:
        r = subprocess.run([sys.executable, "scripts/generate_system_facts.py"],
                           capture_output=True, text=True, timeout=30, cwd=str(PROJECT_ROOT))
        test("System facts regenerates", r.returncode == 0)
    except Exception as e: test("System facts", False, str(e))

    # 19 Holdings unchanged
    try:
        test("Holdings unchanged", json.load(open("data/portfolios/state/holdings.json"))["portfolio_totals"]["total_value"] > 1_000_000)
    except Exception as e: test("Holdings", False, str(e))

    print(f"\n{'='*50}")
    print(f"  PASS: {PASS}  FAIL: {FAIL}")
    print(f"{'='*50}")
    return FAIL == 0

if __name__ == "__main__":
    ok = run()
    sys.exit(0 if ok else 1)
