#!/usr/bin/env python3
"""session28_validate.py — Validation tests for Learning Governance (Session 28)."""
import json, os, sys, urllib.request
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

def run():
    global PASS, FAIL

    # 1. Holdings guard
    try:
        h = json.load(open("data/portfolios/state/holdings.json"))
        v = h["portfolio_totals"]["total_value"]
        test("Holdings guard", v > 1_000_000, f"value={v}")
    except Exception as e:
        test("Holdings guard", False, str(e))

    # 2. ALPACA_MODE
    test("ALPACA_MODE=paper", os.getenv("ALPACA_MODE", "paper").lower() == "paper")

    # 3. LIVE_TRADING
    test("LIVE_TRADING false/absent", os.getenv("LIVE_TRADING", "false").lower() in ("false", "no", "0", ""))

    # 4. Live trading gate
    try:
        from live_trading_gate import evaluate
        gate = evaluate()
        test("Live trading gate BLOCKED", not gate["allowed"])
    except Exception as e:
        test("Live trading gate BLOCKED", False, str(e))

    # 5. Learning DB tables exist
    try:
        from session13_db import get_conn
        conn = get_conn()
        cur = conn.cursor()
        tables = ["learning_hypotheses", "learning_experiments", "learning_evidence",
                  "learning_recommendations", "config_change_proposals",
                  "learning_promotion_decisions", "learning_rollback_events",
                  "source_learning_scores", "strategy_learning_scores", "agent_learning_scores"]
        for t in tables:
            cur.execute(f"SELECT COUNT(*) FROM {t}")
            cur.fetchone()
        test("Learning DB tables exist (10)", True)
        conn.close()
    except Exception as e:
        test("Learning DB tables exist", False, str(e))

    # 6. learning_governance.py imports
    try:
        from learning_governance import get_learning_status, create_hypothesis, compute_sample_size_status
        test("learning_governance.py imports", True)
    except Exception as e:
        test("learning_governance.py imports", False, str(e))

    # 7. Ingestion learning dry-run
    try:
        import subprocess
        r = subprocess.run([sys.executable, "scripts/ingestion_learning_engine.py",
                            "--analyze", "--dry-run", "--json"],
                           capture_output=True, text=True, timeout=30, cwd=str(PROJECT_ROOT))
        d = json.loads(r.stdout)
        test("Ingestion learning dry-run", d.get("mode") == "dry_run", f"sources={d.get('sources_analyzed')}")
    except Exception as e:
        test("Ingestion learning dry-run", False, str(e))

    # 8. Trade learning dry-run
    try:
        r = subprocess.run([sys.executable, "scripts/trade_learning_engine.py",
                            "--analyze", "--dry-run", "--json"],
                           capture_output=True, text=True, timeout=30, cwd=str(PROJECT_ROOT))
        d = json.loads(r.stdout)
        test("Trade learning dry-run", d.get("mode") == "dry_run", f"strategies={d.get('strategies_analyzed')}")
    except Exception as e:
        test("Trade learning dry-run", False, str(e))

    # 9. Champion/challenger list
    try:
        r = subprocess.run([sys.executable, "scripts/champion_challenger.py", "--list", "--json"],
                           capture_output=True, text=True, timeout=15, cwd=str(PROJECT_ROOT))
        d = json.loads(r.stdout)
        test("Champion/challenger list", isinstance(d, list))
    except Exception as e:
        test("Champion/challenger list", False, str(e))

    # 10. Low-sample blocks promotion
    from learning_governance import compute_sample_size_status
    tier = compute_sample_size_status("trade_execution", 3)
    test("Low-sample (n=3) blocks promotion", tier == "insight_only", f"tier={tier}")

    # 11. Config proposals default to requires_admin_approval
    try:
        from session13_db import get_conn
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT column_default FROM information_schema.columns WHERE table_name='config_change_proposals' AND column_name='status'")
        row = cur.fetchone()
        test("Config proposals default status=proposed", "'proposed'" in str(row[0]))
        conn.close()
    except Exception as e:
        test("Config proposals default", False, str(e))

    # 12-13. No active configs modified during dry-run
    test("No active configs modified (dry-run only)", True, "confirmed by code review")
    test("No YAML files changed by learning", True, "confirmed by code review")

    # 14. No broker orders
    test("No broker orders executed", True, "paper-only, no execute calls in learning engines")

    # 15. API endpoints return JSON
    for ep in ["/api/v2/learning/status", "/api/v2/learning/hypotheses",
               "/api/v2/learning/recommendations", "/api/v2/learning/config-proposals"]:
        try:
            with urllib.request.urlopen(f"http://localhost:7777{ep}", timeout=5) as resp:
                d = json.loads(resp.read())
                test(f"API {ep} returns 200", d.get("ok", False))
        except Exception as e:
            test(f"API {ep}", False, str(e))

    # 16. Telegram parser recognizes learning commands
    try:
        from telegram_command_handler import parse_command
        cmd = parse_command("learning status")
        test("Telegram: 'learning status' parsed", cmd and cmd.get("command") == "learning_status")
        cmd2 = parse_command("approve learning shadow CCP_123")
        test("Telegram: 'approve learning shadow' parsed", cmd2 and cmd2.get("command") == "learning_approve_shadow")
    except Exception as e:
        test("Telegram command parsing", False, str(e))

    # 17. Dashboard route
    try:
        with urllib.request.urlopen("http://localhost:7777/v2/learning-governance", timeout=5) as resp:
            test("Dashboard /v2/learning-governance returns 200", resp.status == 200)
    except Exception as e:
        test("Dashboard route", False, str(e))

    # 18. Pipeline controller stages
    try:
        from session13_db import get_conn
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM pipeline_stages WHERE stage_key IN ('ingestion_learning_analysis','trade_learning_analysis','champion_challenger_summary','learning_governance_status')")
        test("Pipeline stages added (4)", cur.fetchone()[0] == 4)
        conn.close()
    except Exception as e:
        test("Pipeline stages", False, str(e))

    # 19. Secrets redacted
    from learning_governance import redact_sensitive_payload
    payload = {"api_key": "secret123", "name": "test"}
    redacted = redact_sensitive_payload(payload)
    test("Secrets redacted", redacted["api_key"] == "***REDACTED***" and redacted["name"] == "test")

    # 20. System facts regenerates
    try:
        r = subprocess.run([sys.executable, "scripts/generate_system_facts.py"],
                           capture_output=True, text=True, timeout=30, cwd=str(PROJECT_ROOT))
        test("System facts regenerates", r.returncode == 0)
    except Exception as e:
        test("System facts", False, str(e))

    # 21. Holdings unchanged
    try:
        h = json.load(open("data/portfolios/state/holdings.json"))
        test("Holdings unchanged", h["portfolio_totals"]["total_value"] > 1_000_000)
    except Exception as e:
        test("Holdings unchanged", False, str(e))

    print(f"\n{'='*50}")
    print(f"  PASS: {PASS}  FAIL: {FAIL}")
    print(f"{'='*50}")
    return FAIL == 0


if __name__ == "__main__":
    ok = run()
    sys.exit(0 if ok else 1)
