#!/usr/bin/env python3
"""Phase 6A API-level mock validation — exercises approval revalidation logic.

Uses the pure validate_paper_proposal_live_market() function with mock quotes.
No live orders, no DB writes, no Alpaca submission.

Usage:
    .venv/bin/python scripts/test_phase6_market_revalidation_api.py
"""
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from paper_trade_logger import validate_paper_proposal_live_market

RESULTS = []


def run_scenario(name, symbol, entry, stop, target, shares, quote_dict,
                 expected_ok, expected_reason_contains=None, **kwargs):
    """Run one scenario and record result."""
    try:
        r = validate_paper_proposal_live_market(
            symbol, entry, stop, target, shares, quote_dict, **kwargs)
        passed = r["ok"] == expected_ok
        if expected_reason_contains and expected_reason_contains not in r.get("reason", ""):
            passed = False
        RESULTS.append({
            "scenario": name,
            "expected_ok": expected_ok,
            "actual_ok": r["ok"],
            "passed": passed,
            "reason": r.get("reason", "")[:200],
            "checks": r.get("checks"),
            "warnings": r.get("warnings", []),
            "adjusted_entry": r.get("adjusted_entry"),
            "live_price": r.get("live_price"),
        })
    except Exception as e:
        RESULTS.append({
            "scenario": name,
            "expected_ok": expected_ok,
            "actual_ok": None,
            "passed": False,
            "reason": f"EXCEPTION: {e}",
            "checks": None,
        })


def make_quote(price, bid=None, ask=None, spread_pct=0.05, age_sec=3):
    bid = bid or round(price - 0.05, 2)
    ask = ask or round(price + 0.05, 2)
    return {
        "last_price": price,
        "bid": bid,
        "ask": ask,
        "spread_pct": spread_pct,
        "quote_timestamp": datetime.now(timezone.utc) - timedelta(seconds=age_sec),
        "provider": "mock",
    }


def main():
    print("Phase 6A — API Mock Validation")
    print("=" * 60)

    # Scenario 1: Valid approval — all checks pass
    run_scenario(
        "valid_approval",
        "AAPL", 150.0, 145.0, 165.0, 40,
        make_quote(150.5),
        expected_ok=True)

    # Scenario 2: Stale quote block
    run_scenario(
        "stale_quote_block",
        "AAPL", 150.0, 145.0, 165.0, 40,
        make_quote(150.0, age_sec=1200),
        expected_ok=False,
        expected_reason_contains="min old")

    # Scenario 3: High spread block
    run_scenario(
        "high_spread_block",
        "MSFT", 350.0, 340.0, 370.0, 20,
        make_quote(350.0, spread_pct=3.2),
        expected_ok=False,
        expected_reason_contains="spread")

    # Scenario 4: Stop breached block
    run_scenario(
        "stop_breached_block",
        "TSLA", 200.0, 190.0, 220.0, 30,
        make_quote(185.0),
        expected_ok=False,
        expected_reason_contains="stop")

    # Scenario 5: R:R degraded block
    run_scenario(
        "rr_degraded_block",
        "NVDA", 100.0, 95.0, 104.0, 50,
        make_quote(101.0, spread_pct=0.1),
        expected_ok=False,
        expected_reason_contains="R:R")

    # Scenario 6: Drift warning — adjusted entry
    run_scenario(
        "drift_warning_adjusted_entry",
        "AMD", 100.0, 85.0, 130.0, 40,
        make_quote(102.0, spread_pct=0.1),
        expected_ok=True,
        expected_reason_contains="adjustment")

    # Scenario 7: No quote block
    run_scenario(
        "no_quote_block",
        "UNKNOWN", 50.0, 45.0, 60.0, 100,
        {"last_price": None},
        expected_ok=False,
        expected_reason_contains="no live price")

    # Summary
    passed = sum(1 for r in RESULTS if r["passed"])
    total = len(RESULTS)
    print(f"\n{'SCENARIO':<40} {'EXPECTED':>10} {'ACTUAL':>10} {'RESULT':>10}")
    print("-" * 72)
    for r in RESULTS:
        status = "PASS" if r["passed"] else "FAIL"
        print(f"{r['scenario']:<40} {'ok' if r['expected_ok'] else 'block':>10} "
              f"{'ok' if r['actual_ok'] else 'block':>10} {status:>10}")

    print(f"\n{passed}/{total} scenarios passed")

    # Write JSON results
    out_json = PROJECT_ROOT / "docs/execution_safety/phase6_market_revalidation/v4_1_phase6a_api_validation_results.json"
    out_json.write_text(json.dumps({
        "date": datetime.now().isoformat(),
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "scenarios": RESULTS,
    }, indent=2, default=str))
    print(f"\nResults written to: {out_json}")

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
