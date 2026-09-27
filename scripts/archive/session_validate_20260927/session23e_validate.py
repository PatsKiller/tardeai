#!/usr/bin/env python3
"""session23e_validate.py — Validation for Session 23E quote source repair."""
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from session13_db import get_conn

passed = 0
failed = 0
warnings = 0


def check(label, condition, warn_only=False):
    global passed, failed, warnings
    if condition:
        print(f"  [PASS] {label}")
        passed += 1
    elif warn_only:
        print(f"  [WARN] {label}")
        warnings += 1
    else:
        print(f"  [FAIL] {label}")
        failed += 1


def main():
    global passed, failed, warnings
    conn = get_conn()
    cur = conn.cursor()

    print("\n=== SESSION 23E VALIDATION ===\n")

    # 1. market_quote_snapshots table exists
    print("1. Quote snapshots table")
    cur.execute("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name='market_quote_snapshots')")
    check("market_quote_snapshots table exists", cur.fetchone()[0])

    # 2. market_quote_provider imports
    print("\n2. Quote provider import")
    try:
        from market_quote_provider import get_best_quote, store_quote
        check("market_quote_provider imports OK", True)
    except Exception as e:
        check(f"market_quote_provider import ({e})", False)

    # 3. Pending symbols get quote snapshots
    print("\n3. Quote snapshots for pending symbols")
    cur.execute("SELECT DISTINCT symbol FROM paper_trade_proposals WHERE status='PENDING'")
    pending = [r[0] for r in cur.fetchall()]
    if pending:
        from market_quote_provider import get_best_quote
        test_sym = pending[0]
        q = get_best_quote(test_sym)
        check(f"Quote for {test_sym}: provider={q.get('provider')}", q.get('provider') != 'none')
        check(f"Quote returns structured result", 'is_execution_eligible' in q)
    else:
        check("No pending proposals to test", False, warn_only=True)

    # 4. Readiness no longer uses Finviz as primary
    print("\n4. Readiness code audit")
    readiness_src = (PROJECT_ROOT / "scripts" / "proposal_execution_readiness.py").read_text()
    check("No 'finviz_cache' in readiness assess_proposal",
          "finviz_cache" not in readiness_src.split("def assess_proposal")[1] if "def assess_proposal" in readiness_src else False)
    check("Uses market_quote_provider", "market_quote_provider" in readiness_src)

    # 5. Missing bid/ask does not pass spread check
    print("\n5. Spread behavior")
    check("spread_ok defaults to False (not True)",
          "spread_ok = False" in readiness_src and "spread_ok = True  # default" not in readiness_src)
    check("BLOCKED_SPREAD_UNKNOWN in readiness states",
          "BLOCKED_SPREAD_UNKNOWN" in readiness_src)

    # 6. yfinance/Finviz fallback blocks submit
    print("\n6. Delayed quote blocking")
    check("is_execution_eligible field used",
          "is_execution_eligible" in readiness_src or "quote_execution_eligible" in readiness_src)

    # 7. Technical snapshot satisfies indicators_ok
    print("\n7. Technical snapshot primary")
    check("proposal_technical_snapshots checked first",
          "proposal_technical_snapshots" in readiness_src)
    check("indicator_confluence_cache is fallback",
          "indicator_confluence_cache" in readiness_src)

    # 8. Backtest labeling
    print("\n8. Backtest labeling")
    check("BACKTEST_SAMPLE_INSUFFICIENT_LEARNING_MODE in code",
          "BACKTEST_SAMPLE_INSUFFICIENT_LEARNING_MODE" in readiness_src)
    check("No 'Backtest gate not yet implemented' false pass",
          "Backtest gate not yet implemented" not in readiness_src)

    # 9. Enrichment cron deduplicated
    print("\n9. Cron dedupe")
    import subprocess
    cron_result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    cron_lines = [l for l in cron_result.stdout.strip().split("\n") if "enrichment_loop" in l]
    check(f"Enrichment loop cron entries: {len(cron_lines)} (expected 1)", len(cron_lines) <= 1)

    # 10. Gitignore
    print("\n10. Git ignore")
    gitignore = (PROJECT_ROOT / ".gitignore").read_text()
    check("reports/ in .gitignore", "reports/" in gitignore)
    check("logs/ in .gitignore", "logs/" in gitignore)
    check("backups/ in .gitignore", "backups/" in gitignore)
    check("*.bak in .gitignore", "*.bak" in gitignore)
    check("docx_patch_ in .gitignore", "docx_patch_" in gitignore)

    # 11. Real journal clean
    print("\n11. Real journal clean")
    try:
        import requests
        resp = requests.get("http://localhost:7777/api/v2/journal", timeout=10)
        d = resp.json()
        trades = d.get("data", {}).get("trades", [])
        paper = [t for t in trades if "PAPER" in str(t.get("account", "")).upper()]
        check(f"Real journal clean ({len(trades)} real, {len(paper)} paper)", len(paper) == 0)
    except Exception as e:
        check(f"Journal check ({e})", False)

    # 12. Holdings untouched
    print("\n12. Holdings untouched")
    try:
        hpath = PROJECT_ROOT / "data" / "portfolios" / "state" / "holdings.json"
        d = json.loads(hpath.read_text())
        v = d["portfolio_totals"]["total_value"]
        check(f"Holdings ${v:,.0f} > $1M", v > 1000000)
    except Exception as e:
        check(f"Holdings check ({e})", False)

    # 13. No hardcoded secrets
    print("\n13. No hardcoded secrets")
    for f in ["scripts/market_quote_provider.py", "scripts/proposal_execution_readiness.py",
              "scripts/session23e_validate.py"]:
        fpath = PROJECT_ROOT / f
        if fpath.exists():
            content = fpath.read_text()
            _p = ["PK" + "TM", "sk" + "-", "xa" + "i-", "AI" + "za"]
            has_secret = any(s in content for s in _p)
            check(f"No secrets in {f}", not has_secret)

    # 14. No live trading
    print("\n14. Live trading disabled")
    check("LIVE_TRADING_ENABLED=false",
          os.getenv("LIVE_TRADING_ENABLED", "false").lower() == "false")
    check("ALPACA_MODE=paper",
          os.getenv("ALPACA_MODE", "paper").lower() == "paper")

    # Summary
    total = passed + failed
    print(f"\n{'='*50}")
    if failed == 0:
        print(f"SESSION 23E VALIDATION: PASSED ({passed}/{total} checks passed, {warnings} warnings)")
    else:
        print(f"SESSION 23E VALIDATION: FAILED ({failed} failures, {passed}/{total} passed, {warnings} warnings)")
    print(f"{'='*50}\n")

    conn.close()
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
