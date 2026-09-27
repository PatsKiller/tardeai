#!/usr/bin/env python3
"""session18c_validate.py — Session 18C auto-proposal stage validation."""
import json, os, sys, subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

def get_conn():
    import psycopg2
    return psycopg2.connect(host=os.getenv("DB_HOST","127.0.0.1"), port=os.getenv("DB_PORT","5432"),
                            dbname=os.getenv("DB_NAME","trade_ai"), user=os.getenv("DB_USER","trade_ai"),
                            password=os.getenv("DB_PASSWORD"))

def check(label, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}{f' — {detail}' if detail else ''}")
    return condition

def main():
    print("\n" + "=" * 60)
    print("  SESSION 18C VALIDATION: Auto-Proposal Stage 18f")
    print("=" * 60 + "\n")
    conn = get_conn()
    cur = conn.cursor()
    p, f = 0, 0

    # 1. auto_proposal_runs exists
    cur.execute("SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='auto_proposal_runs')")
    if check("auto_proposal_runs table exists", cur.fetchone()[0]): p+=1
    else: f+=1

    # 2. auto_proposal_decisions exists
    cur.execute("SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='auto_proposal_decisions')")
    if check("auto_proposal_decisions table exists", cur.fetchone()[0]): p+=1
    else: f+=1

    # 3. auto_proposal_generator imports
    try:
        import ast; ast.parse((PROJECT_ROOT / "scripts/auto_proposal_generator.py").read_text())
        if check("auto_proposal_generator.py syntax", True): p+=1
        else: f+=1
    except Exception as e:
        if check("auto_proposal_generator.py syntax", False, str(e)): p+=1
        else: f+=1

    # 4. Dry run works
    r = subprocess.run([str(PROJECT_ROOT / ".venv/bin/python"), str(PROJECT_ROOT / "scripts/auto_proposal_generator.py"),
                        "--today", "--dry-run"], capture_output=True, text=True, timeout=30)
    if check("Dry run executes", r.returncode == 0, r.stdout.strip()[-80:] if r.stdout else r.stderr[:80]): p+=1
    else: f+=1

    # 5. Apply run created or skipped with reasons
    cur.execute("SELECT COUNT(*) FROM auto_proposal_runs WHERE run_date=CURRENT_DATE AND status='COMPLETED'")
    runs = cur.fetchone()[0]
    if check("Apply run completed", runs > 0, f"{runs} completed runs"): p+=1
    else: f+=1

    # 6. No duplicates
    cur.execute("""SELECT source_signal_id, COUNT(*) FROM paper_trade_proposals
                   WHERE source_signal_id IS NOT NULL AND status IN ('PENDING','APPROVED','MODIFIED','BROKER_SUBMITTED')
                   GROUP BY source_signal_id HAVING COUNT(*) > 1""")
    dups = cur.fetchall()
    if check("No duplicate proposals per signal", len(dups) == 0): p+=1
    else: f+=1

    # 7. Risk-rejected not inserted as PENDING
    cur.execute("""SELECT COUNT(*) FROM auto_proposal_decisions
                   WHERE decision='SKIPPED_RISK_GATE' AND proposal_id IS NOT NULL""")
    bad = cur.fetchone()[0]
    if check("Risk-rejected not created as proposals", bad == 0): p+=1
    else: f+=1

    # 8. Orchestrator contains stage 18f
    orch = (PROJECT_ROOT / "scripts/trade_ai_orchestrator.py").read_text()
    if check("Orchestrator has stage 18f", "auto_proposal" in orch and "18f" in orch): p+=1
    else: f+=1

    # 9. Pipeline health includes auto_proposals
    import urllib.request
    try:
        resp = urllib.request.urlopen("http://localhost:7777/api/v2/pipeline-run-health", timeout=10)
        data = json.loads(resp.read())
        inner = data.get("data", data)
        has_ap = "auto_proposals" in inner and inner["auto_proposals"] is not None
        if check("Pipeline health has auto_proposals", has_ap): p+=1
        else: f+=1
    except Exception as e:
        if check("Pipeline health endpoint", False, str(e)): p+=1
        else: f+=1

    # 10. Auto-proposal diagnostics endpoint
    try:
        resp = urllib.request.urlopen("http://localhost:7777/api/v2/auto-proposal-diagnostics", timeout=10)
        data = json.loads(resp.read())
        inner = data.get("data", data)
        if check("Auto-proposal diagnostics endpoint", inner.get("ok"), f"runs={len(inner.get('runs',[]))} decisions={len(inner.get('decisions',[]))}"): p+=1
        else: f+=1
    except Exception as e:
        if check("Auto-proposal diagnostics", False, str(e)): p+=1
        else: f+=1

    # 11. Multi-strategy routing works
    cur.execute("SELECT COUNT(DISTINCT strategy_id) FROM strategy_signals WHERE fired_at::date=CURRENT_DATE")
    strat_count = cur.fetchone()[0]
    if check("Multi-strategy routing", strat_count >= 1, f"{strat_count} strategies with signals today"): p+=1
    else: f+=1

    # 12. Real journal clean
    try:
        resp = urllib.request.urlopen("http://localhost:7777/api/v2/journal", timeout=10)
        data = json.loads(resp.read())
        inner = data.get("data", data)
        trades = inner.get("trades") or inner.get("data") or []
        paper = [t for t in trades if "PAPER" in str(t.get("account",""))]
        if check("Real journal clean", len(paper) == 0, f"{len(trades)} trades, 0 paper"): p+=1
        else: f+=1
    except Exception as e:
        if check("Journal check", False, str(e)): p+=1
        else: f+=1

    # 13. No hardcoded secrets in new files
    r = subprocess.run(["grep", "-l", "1AHC_w9F", "scripts/auto_proposal_generator.py"],
                       capture_output=True, text=True, cwd=str(PROJECT_ROOT))
    if check("No hardcoded DB in auto_proposal_generator", r.returncode != 0): p+=1
    else: f+=1

    # 14. Holdings unchanged
    try:
        h = json.load(open(PROJECT_ROOT / "data/portfolios/state/holdings.json"))
        v = h["portfolio_totals"]["total_value"]
        if check("Holdings intact", v > 1000000, f"${v:,.0f}"): p+=1
        else: f+=1
    except Exception as e:
        if check("Holdings", False, str(e)): p+=1
        else: f+=1

    # 15. Frontend build
    r = subprocess.run(["npm", "run", "build"], capture_output=True, text=True,
                       cwd=str(PROJECT_ROOT / "apps/command-center-v2"), timeout=60)
    if check("Frontend build", r.returncode == 0): p+=1
    else: f+=1

    conn.close()
    print(f"\n{'='*60}")
    if f == 0:
        print(f"  SESSION 18C VALIDATION: PASSED ({p}/{p+f})")
    else:
        print(f"  SESSION 18C VALIDATION: {f} FAILURES ({p}/{p+f} passed)")
    print(f"{'='*60}\n")
    return 0 if f == 0 else 1

if __name__ == "__main__":
    sys.exit(main())
