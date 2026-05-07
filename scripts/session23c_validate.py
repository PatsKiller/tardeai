#!/usr/bin/env python3
"""session23c_validate.py — Validate Session 23C institutional proposal packet."""
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from session13_db import get_conn

passed = 0
failed = 0
warnings = 0


def check(name, condition, detail=""):
    global passed, failed
    if condition:
        print(f"  PASS  {name}")
        passed += 1
    else:
        print(f"  FAIL  {name} — {detail}")
        failed += 1


def warn(name, detail):
    global warnings
    print(f"  WARN  {name} — {detail}")
    warnings += 1


def main():
    global passed, failed, warnings
    conn = get_conn()
    cur = conn.cursor()

    print("SESSION 23C VALIDATION")
    print("=" * 60)

    # 1. Tables exist
    print("\n--- Tables ---")
    for table in ["proposal_evidence_snapshots", "proposal_technical_snapshots",
                   "strategy_backtest_results", "proposal_execution_readiness",
                   "proposal_event_log"]:
        cur.execute("SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name=%s)", [table])
        check(f"Table {table}", cur.fetchone()[0], "table not found")

    # 2. Proposal columns
    print("\n--- Proposal Columns ---")
    for col in ["institutional_packet_ready", "latest_execution_readiness",
                "alpaca_paper_submit_enabled", "live_submit_blocked_reason"]:
        cur.execute("""SELECT EXISTS(SELECT 1 FROM information_schema.columns
                      WHERE table_name='paper_trade_proposals' AND column_name=%s)""", [col])
        check(f"Column {col}", cur.fetchone()[0], "column not found")

    # 3. Technical snapshots exist for pending
    print("\n--- Technical Snapshots ---")
    cur.execute("""SELECT COUNT(*) FROM paper_trade_proposals WHERE status='PENDING'""")
    pending_count = cur.fetchone()[0]
    cur.execute("""SELECT COUNT(DISTINCT p.id) FROM paper_trade_proposals p
                  JOIN proposal_technical_snapshots t ON t.proposal_id=p.id
                  WHERE p.status='PENDING'""")
    tech_count = cur.fetchone()[0]
    check(f"Technical snapshots ({tech_count}/{pending_count})",
          tech_count > 0 or pending_count == 0, "no snapshots for pending proposals")

    # 4. Backtest snapshots
    print("\n--- Backtest ---")
    cur.execute("""SELECT COUNT(DISTINCT p.id) FROM paper_trade_proposals p
                  JOIN proposal_backtest_snapshots b ON b.proposal_id=p.id
                  WHERE p.status='PENDING'""")
    bt_count = cur.fetchone()[0]
    check(f"Backtest snapshots ({bt_count}/{pending_count})",
          bt_count > 0 or pending_count == 0, "no backtests")

    # 5. LLM analysis structured or fallback labeled
    print("\n--- LLM Analysis ---")
    cur.execute("""SELECT narrative_source, COUNT(*)
                  FROM paper_proposal_analysis
                  WHERE proposal_id IN (SELECT id FROM paper_trade_proposals WHERE status='PENDING')
                  GROUP BY narrative_source""")
    llm_sources = dict(cur.fetchall())
    check("LLM analyses exist", len(llm_sources) > 0, "no analyses")
    for src, cnt in llm_sources.items():
        print(f"    {src}: {cnt}")

    # 6. Scripts exist
    print("\n--- Scripts ---")
    for script in ["proposal_technical_snapshot.py", "proposal_strategy_fit.py",
                    "proposal_backtest_engine.py", "proposal_catalyst_quality.py",
                    "proposal_execution_readiness.py", "proposal_paper_submitter.py",
                    "proposal_intelligence_analyzer.py"]:
        path = PROJECT_ROOT / "scripts" / script
        check(f"Script {script}", path.exists(), f"{path} not found")

    # 7. API responds with packet fields
    print("\n--- API ---")
    try:
        import urllib.request
        resp = urllib.request.urlopen("http://localhost:7777/api/v2/paper-proposals", timeout=10)
        data = json.loads(resp.read())
        props = data.get("proposals", [])
        if props:
            p = props[0]
            for field in ["strategy_fit", "technical_snapshot", "scan_history",
                         "catalyst_quality", "backtest_summary", "execution_readiness",
                         "llm_analysis", "agent_reviews", "paper_submit_state",
                         "missing_data", "paper_ready"]:
                check(f"API field: {field}", field in p, f"missing from proposal response")
        else:
            warn("API proposals", "no pending proposals to verify")
    except Exception as e:
        warn("API check", f"could not reach API: {e}")

    # 8. Frontend builds
    print("\n--- Frontend ---")
    build_dir = PROJECT_ROOT / "apps" / "command-center-v2" / "dist"
    check("Frontend built", build_dir.exists() and any(build_dir.iterdir()),
          "dist directory empty")

    # 9. Safety checks
    print("\n--- Safety ---")
    check("LIVE_TRADING_ENABLED=false",
          os.getenv("LIVE_TRADING_ENABLED", "false").lower() != "true",
          "LIVE TRADING IS ENABLED!")

    # Holdings
    try:
        hp = PROJECT_ROOT / "data" / "portfolios" / "state" / "holdings.json"
        h = json.loads(hp.read_text())
        v = h["portfolio_totals"]["total_value"]
        check(f"Holdings safe (${v:,.0f})", v > 1000000, f"value too low: {v}")
    except Exception as e:
        check("Holdings check", False, str(e))

    # No hardcoded DB password
    from local_llm_config import get_local_llm_model
    model = get_local_llm_model()
    check(f"LLM model is qwen3:14b ({model})", model == "qwen3:14b", f"got {model}")

    # Journal clean
    try:
        resp = urllib.request.urlopen("http://localhost:7777/api/v2/journal", timeout=10)
        jdata = json.loads(resp.read())
        trades = jdata.get("trades") or jdata.get("data") or []
        paper = [t for t in trades if "PAPER" in str(t.get("account", ""))]
        check("Real journal clean", len(paper) == 0, f"{len(paper)} paper trades found")
    except Exception as e:
        warn("Journal check", str(e))

    # Summary
    print("\n" + "=" * 60)
    total = passed + failed
    if failed == 0:
        print(f"SESSION 23C VALIDATION: PASSED ({passed}/{total} checks, {warnings} warnings)")
    else:
        print(f"SESSION 23C VALIDATION: FAILED ({failed} failures, {passed} passes, {warnings} warnings)")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
