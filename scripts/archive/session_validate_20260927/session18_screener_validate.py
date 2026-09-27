#!/usr/bin/env python3
"""session18_screener_validate.py — Session 18 screener/freshness/signal validation."""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")


def get_conn():
    import psycopg2
    password = os.getenv("DB_PASSWORD")
    if not password:
        raise RuntimeError("DB_PASSWORD missing from .env")
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "trade_ai"),
        user=os.getenv("DB_USER", "trade_ai"),
        password=password,
    )


def check(label, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}{f' — {detail}' if detail else ''}")
    return condition


def main():
    print("\n" + "=" * 60)
    print("  SESSION 18 VALIDATION: Screener Universe + Freshness")
    print("=" * 60 + "\n")

    conn = get_conn()
    cur = conn.cursor()
    passed = 0
    failed = 0

    # 1. screener_run_health table exists
    cur.execute("SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='screener_run_health')")
    exists = cur.fetchone()[0]
    if check("screener_run_health table exists", exists):
        passed += 1
    else:
        failed += 1

    # 2. Current-day scan count
    cur.execute("SELECT COUNT(DISTINCT symbol) FROM trade_ai_scans WHERE (scanned_at AT TIME ZONE 'America/New_York')::date = (NOW() AT TIME ZONE 'America/New_York')::date")
    today_symbols = cur.fetchone()[0]
    if check("Current-day scan count", today_symbols > 0, f"{today_symbols} symbols"):
        passed += 1
    else:
        failed += 1

    # 3. Latest run health
    cur.execute("SELECT run_label, status, symbols_scanned FROM screener_run_health WHERE run_date=CURRENT_DATE ORDER BY finished_at DESC NULLS LAST LIMIT 1")
    rh = cur.fetchone()
    if rh:
        if check("Run health status present", True, f"run={rh[0]} status={rh[1]} symbols={rh[2]}"):
            passed += 1
        else:
            failed += 1
    else:
        if check("Run health status present", False, "No run health records for today"):
            passed += 1
        else:
            failed += 1

    # 4. Prospects API freshness
    try:
        import urllib.request
        resp = urllib.request.urlopen("http://localhost:7777/api/v2/prospects", timeout=10)
        data = json.loads(resp.read())
        has_stale = "is_stale" in data
        has_health = "run_health_status" in data
        if check("Prospects API has freshness fields", has_stale and has_health,
                  f"is_stale={data.get('is_stale')} health={data.get('run_health_status')} symbols={data.get('symbols_scanned')}"):
            passed += 1
        else:
            failed += 1
    except Exception as e:
        if check("Prospects API responds", False, str(e)):
            passed += 1
        else:
            failed += 1

    # 5. Trade AI API run health
    try:
        resp = urllib.request.urlopen("http://localhost:7777/api/v2/trade-ai", timeout=10)
        raw = json.loads(resp.read())
        data = raw.get("data", raw)
        has_health = "run_health_status" in data
        if check("Trade AI API has run health", has_health,
                  f"health={data.get('run_health_status')} signals={data.get('today_strategy_signal_count')}"):
            passed += 1
        else:
            failed += 1
    except Exception as e:
        if check("Trade AI API responds", False, str(e)):
            passed += 1
        else:
            failed += 1

    # 6. Pipeline run health endpoint
    try:
        resp = urllib.request.urlopen("http://localhost:7777/api/v2/pipeline-run-health", timeout=10)
        raw = json.loads(resp.read())
        data = raw.get("data", raw)
        if check("Pipeline run health endpoint", data.get("ok"),
                  f"run={data.get('latest_run',{}).get('run_label')} plans={data.get('trade_plans',{}).get('planned')}/{data.get('trade_plans',{}).get('proposal_worthy')}"):
            passed += 1
        else:
            failed += 1
    except Exception as e:
        if check("Pipeline run health endpoint", False, str(e)):
            passed += 1
        else:
            failed += 1

    # 7. Strategy signals today
    cur.execute("SELECT COUNT(*) FROM strategy_signals WHERE fired_at::date = CURRENT_DATE")
    sig_count = cur.fetchone()[0]
    if check("Strategy signals today", sig_count > 0, f"{sig_count} signals"):
        passed += 1
    else:
        failed += 1

    # 8. Trade plan coverage
    cur.execute("""
        SELECT COUNT(*) AS pw,
               COUNT(CASE WHEN entry_high IS NOT NULL AND stop_loss IS NOT NULL
                          AND target_1 IS NOT NULL AND shares IS NOT NULL THEN 1 END) AS planned
        FROM strategy_signals
        WHERE fired_at::date = CURRENT_DATE
        AND (signal_grade IN ('A','A+') OR signal_score >= 40)
    """)
    pw_row = cur.fetchone()
    pw, planned = pw_row[0], pw_row[1]
    coverage = round(planned / pw * 100, 1) if pw > 0 else 0
    if check("Trade plan coverage", coverage >= 50 or pw == 0,
             f"{planned}/{pw} planned ({coverage}%)"):
        passed += 1
    else:
        failed += 1

    # 9. No hardcoded secrets in session 18 files
    import subprocess
    session18_files = [
        "scripts/screener_run_health.py",
        "scripts/backfill_trade_plans_for_signals.py",
    ]
    existing = [f for f in session18_files if Path(PROJECT_ROOT / f).exists()]
    result = subprocess.run(
        ["grep", "-l", "1AHC_w9F"] + existing,
        capture_output=True, text=True, cwd=str(PROJECT_ROOT)
    )
    no_secrets = result.returncode != 0
    if check("No hardcoded DB in session 18 files", no_secrets):
        passed += 1
    else:
        failed += 1

    # 10. Holdings unchanged
    try:
        h = json.load(open(PROJECT_ROOT / "data/portfolios/state/holdings.json"))
        val = h["portfolio_totals"]["total_value"]
        if check("Holdings intact", val > 1000000, f"${val:,.0f}"):
            passed += 1
        else:
            failed += 1
    except Exception as e:
        if check("Holdings file readable", False, str(e)):
            passed += 1
        else:
            failed += 1

    # 11. Syntax checks
    for f in ["api_v2.py", "trade_ai_orchestrator.py", "finviz_screener_runner.py",
              "strategy_signal_sync.py", "screener_run_health.py", "backfill_trade_plans_for_signals.py"]:
        path = PROJECT_ROOT / "scripts" / f
        if path.exists():
            try:
                import ast
                ast.parse(path.read_text())
                if check(f"Syntax: {f}", True):
                    passed += 1
                else:
                    failed += 1
            except SyntaxError as e:
                if check(f"Syntax: {f}", False, str(e)):
                    passed += 1
                else:
                    failed += 1

    conn.close()

    print(f"\n{'=' * 60}")
    total = passed + failed
    if failed == 0:
        print(f"  SESSION 18 VALIDATION: PASSED ({passed}/{total})")
    else:
        print(f"  SESSION 18 VALIDATION: {failed} FAILURES ({passed}/{total} passed)")
    print(f"{'=' * 60}\n")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
