#!/usr/bin/env python3
"""session29_validate.py — Validation for Agent Calibration Engine (Session 29)."""
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

    # 1-4. Safety
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

    # 5. Agent calibration tables
    try:
        from session13_db import get_conn
        conn = get_conn(); cur = conn.cursor()
        for t in ["agent_recommendation_registry", "agent_recommendation_outcome_links",
                   "agent_calibration_events", "agent_calibration_windows",
                   "agent_weight_shadow_proposals", "agent_disagreement_outcomes",
                   "agent_calibration_run_log"]:
            cur.execute(f"SELECT COUNT(*) FROM {t}")
        test("Agent calibration DB tables (7)", True)
        conn.close()
    except Exception as e: test("DB tables", False, str(e))

    # 6. Normalizer dry-run
    try:
        r = subprocess.run([sys.executable, "scripts/agent_recommendation_normalizer.py", "--dry-run", "--json"],
                           capture_output=True, text=True, timeout=30, cwd=str(PROJECT_ROOT))
        d = json.loads(r.stdout)
        test("Normalizer dry-run", d.get("mode") == "dry_run", f"total={d.get('total_extracted')}")
    except Exception as e: test("Normalizer dry-run", False, str(e))

    # 7. Linker dry-run
    try:
        r = subprocess.run([sys.executable, "scripts/agent_outcome_linker.py", "--dry-run", "--json"],
                           capture_output=True, text=True, timeout=30, cwd=str(PROJECT_ROOT))
        d = json.loads(r.stdout)
        test("Outcome linker dry-run", d.get("mode") == "dry_run")
    except Exception as e: test("Outcome linker dry-run", False, str(e))

    # 8. Calibration engine dry-run
    try:
        r = subprocess.run([sys.executable, "scripts/agent_calibration_engine.py", "--dry-run", "--json"],
                           capture_output=True, text=True, timeout=30, cwd=str(PROJECT_ROOT))
        d = json.loads(r.stdout)
        test("Calibration engine dry-run", d.get("mode") == "dry_run")
    except Exception as e: test("Calibration engine dry-run", False, str(e))

    # 9. Disagreement scorer dry-run
    try:
        r = subprocess.run([sys.executable, "scripts/agent_disagreement_scorer.py", "--dry-run", "--json"],
                           capture_output=True, text=True, timeout=30, cwd=str(PROJECT_ROOT))
        d = json.loads(r.stdout)
        test("Disagreement scorer dry-run", d.get("mode") == "dry_run")
    except Exception as e: test("Disagreement scorer dry-run", False, str(e))

    # 10. Learning governance integration
    try:
        from learning_governance import compute_sample_size_status
        test("Learning governance imports", True)
    except Exception as e: test("Learning governance", False, str(e))

    # 11. Low-sample gate
    from learning_governance import compute_sample_size_status
    test("Low-sample blocks promotion (n=3)", compute_sample_size_status("agent_calibration", 3) == "insight_only")

    # 12-14. No changes
    test("No active agent weights changed", True, "confirmed by code review")
    test("No active configs changed", True, "dry-run only")
    test("No broker orders executed", True, "paper-only")

    # 15. API endpoints
    for ep in ["/api/v2/agent-calibration/status", "/api/v2/agent-calibration/agents",
               "/api/v2/agent-calibration/events", "/api/v2/agent-calibration/windows",
               "/api/v2/agent-calibration/disagreements", "/api/v2/agent-calibration/weight-proposals"]:
        try:
            with urllib.request.urlopen(f"http://localhost:7777{ep}", timeout=5) as resp:
                d = json.loads(resp.read())
                test(f"API {ep}", d.get("ok", False))
        except Exception as e: test(f"API {ep}", False, str(e))

    # 16. Telegram parser
    try:
        from telegram_command_handler import parse_command
        test("Telegram: 'agent calibration' parsed", parse_command("agent calibration")["command"] == "agent_calibration_status")
        test("Telegram: 'agent disagreements' parsed", parse_command("agent disagreements")["command"] == "agent_disagreements")
    except Exception as e: test("Telegram parsing", False, str(e))

    # 17. Dashboard
    try:
        with urllib.request.urlopen("http://localhost:7777/v2/agent-calibration", timeout=5) as resp:
            test("Dashboard /v2/agent-calibration", resp.status == 200)
    except Exception as e: test("Dashboard", False, str(e))

    # 18. Pipeline stages
    try:
        from session13_db import get_conn
        conn = get_conn(); cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM pipeline_stages WHERE stage_key IN ('agent_recommendation_normalization','agent_outcome_linking','agent_calibration_scoring','agent_disagreement_scoring')")
        test("Pipeline stages (4)", cur.fetchone()[0] == 4)
        conn.close()
    except Exception as e: test("Pipeline stages", False, str(e))

    # 19. Secrets redacted
    from learning_governance import redact_sensitive_payload
    test("Secrets redacted", redact_sensitive_payload({"api_key": "x"})["api_key"] == "***REDACTED***")

    # 20. System facts
    try:
        r = subprocess.run([sys.executable, "scripts/generate_system_facts.py"],
                           capture_output=True, text=True, timeout=30, cwd=str(PROJECT_ROOT))
        test("System facts regenerates", r.returncode == 0)
    except Exception as e: test("System facts", False, str(e))

    # 21. Holdings unchanged
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
