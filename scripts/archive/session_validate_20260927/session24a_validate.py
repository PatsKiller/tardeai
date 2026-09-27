#!/usr/bin/env python3
"""session24a_validate.py — Validation for Session 24A lifecycle + governance."""
import json, os, sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from session13_db import get_conn

passed = failed = warnings = 0

def check(label, condition, warn_only=False):
    global passed, failed, warnings
    if condition:
        print(f"  [PASS] {label}"); passed += 1
    elif warn_only:
        print(f"  [WARN] {label}"); warnings += 1
    else:
        print(f"  [FAIL] {label}"); failed += 1

def main():
    global passed, failed, warnings
    conn = get_conn()
    cur = conn.cursor()

    print("\n=== SESSION 24A VALIDATION ===\n")

    # 1. proposal_lifecycle imports
    print("1. Lifecycle module")
    try:
        from proposal_lifecycle import (get_expiry_hours, is_overnight, is_intraday,
                                        get_timeframe_class, evaluate_lifecycle_status)
        check("proposal_lifecycle imports", True)
    except Exception as e:
        check(f"proposal_lifecycle import ({e})", False)

    # 2. All 20 strategies have expiry values
    print("\n2. Strategy expiry values")
    from proposal_lifecycle import STRATEGY_EXPIRY_HOURS
    check(f"Strategy count >= 20 ({len(STRATEGY_EXPIRY_HOURS)})", len(STRATEGY_EXPIRY_HOURS) >= 20)

    # 3. Intraday strategies are not overnight
    print("\n3. Intraday classification")
    check("momentum_scalp is intraday", is_intraday("momentum_scalp"))
    check("gap_and_go is intraday", is_intraday("gap_and_go"))
    check("momentum_scalp NOT overnight", not is_overnight("momentum_scalp"))

    # 4. Swing/position are overnight
    print("\n4. Overnight classification")
    check("swing_breakout is overnight", is_overnight("swing_breakout"))
    check("income_add is overnight", is_overnight("income_add"))
    check("defense_thesis is overnight", is_overnight("defense_thesis"))

    # 5. Proposal creation uses lifecycle
    print("\n5. Proposal creation")
    apg = (PROJECT_ROOT / "scripts/auto_proposal_generator.py").read_text()
    check("auto_proposal_generator uses get_expiry_datetime", "get_expiry_datetime" in apg)
    ptl = (PROJECT_ROOT / "scripts/paper_trade_logger.py").read_text()
    check("paper_trade_logger uses get_expiry_datetime", "get_expiry_datetime" in ptl)

    # 6. Expiry cleanup is strategy-aware
    print("\n6. Expiry cleanup")
    check("expire_old_proposals is strategy-aware", "EXPIRED_INTRADAY" in ptl and "EXPIRED_MAX_WINDOW" in ptl)

    # 7. Proposal monitor
    print("\n7. Proposal monitor")
    try:
        from proposal_monitor import monitor_proposal, get_pending_proposals
        check("proposal_monitor imports", True)
    except Exception as e:
        check(f"proposal_monitor ({e})", False)

    # 8. Live price API
    print("\n8. Live price API")
    api_src = (PROJECT_ROOT / "scripts/api_v2.py").read_text()
    check("live-price endpoint exists", "live-price/" in api_src)
    check("lifecycle-events endpoint exists", "lifecycle-events" in api_src)
    check("proposal-monitor endpoint exists", "/api/v2/paper-proposals/monitor" in api_src)

    # 9. UI builds
    print("\n9. Frontend")
    build = PROJECT_ROOT / "apps/command-center-v2/dist/index.html"
    check("Frontend dist/index.html exists", build.exists())

    # 10. Lifecycle schema
    print("\n10. Lifecycle schema")
    for col in ["lifecycle_status", "entry_zone_status", "base_expires_at",
                "max_expires_at", "expiry_extended_count", "proposal_timeframe_class"]:
        cur.execute("SELECT EXISTS (SELECT FROM information_schema.columns WHERE table_name='paper_trade_proposals' AND column_name=%s)", [col])
        check(f"Column {col} exists", cur.fetchone()[0])

    # 11. TCA table
    print("\n11. TCA table")
    cur.execute("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name='paper_execution_quality')")
    check("paper_execution_quality exists", cur.fetchone()[0])

    # 12. Broker reconciliation tables
    print("\n12. Broker reconciliation")
    for t in ["broker_reconciliation_runs", "broker_reconciliation_items"]:
        cur.execute("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name=%s)", [t])
        check(f"{t} exists", cur.fetchone()[0])

    # 13. Governance table
    print("\n13. Governance")
    cur.execute("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name='paper_performance_governance')")
    check("paper_performance_governance exists", cur.fetchone()[0])
    cur.execute("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name='trade_thesis_outcomes')")
    check("trade_thesis_outcomes exists", cur.fetchone()[0])

    # 14. LLM model
    print("\n14. LLM model")
    try:
        from local_llm_config import get_local_llm_model
        check(f"LLM = {get_local_llm_model()}", get_local_llm_model() == "qwen3:14b")
    except Exception as e:
        check(f"LLM ({e})", False)

    # 15. Real journal
    print("\n15. Real journal")
    try:
        import requests
        d = requests.get("http://localhost:7777/api/v2/journal", timeout=10).json()
        trades = d.get("data", {}).get("trades", [])
        paper = [t for t in trades if "PAPER" in str(t.get("account", "")).upper()]
        check(f"Journal clean ({len(trades)} real, {len(paper)} paper)", len(paper) == 0)
    except Exception as e:
        check(f"Journal ({e})", False)

    # 16. Holdings
    print("\n16. Holdings")
    d = json.loads((PROJECT_ROOT / "data/portfolios/state/holdings.json").read_text())
    v = d["portfolio_totals"]["total_value"]
    check(f"Holdings ${v:,.0f} > $1M", v > 1000000)

    # 17. No hardcoded DB password
    print("\n17. No hardcoded secrets")
    for f in ["scripts/proposal_lifecycle.py", "scripts/proposal_monitor.py"]:
        content = (PROJECT_ROOT / f).read_text()
        check(f"No DB password in {f}", "DB_PASSWORD" not in content or "os.getenv" in content)

    # 18. Live trading disabled
    print("\n18. Live trading")
    check("LIVE_TRADING_ENABLED=false", os.getenv("LIVE_TRADING_ENABLED", "false").lower() == "false")
    check("ALPACA_MODE=paper", os.getenv("ALPACA_MODE", "paper").lower() == "paper")

    total = passed + failed
    print(f"\n{'='*50}")
    if failed == 0:
        print(f"SESSION 24A VALIDATION: PASSED ({passed}/{total} checks passed, {warnings} warnings)")
    else:
        print(f"SESSION 24A VALIDATION: FAILED ({failed} failures, {passed}/{total} passed, {warnings} warnings)")
    print(f"{'='*50}\n")
    conn.close()
    return 0 if failed == 0 else 1

if __name__ == "__main__":
    sys.exit(main())
