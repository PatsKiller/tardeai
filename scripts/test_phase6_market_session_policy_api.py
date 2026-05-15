#!/usr/bin/env python3
"""Phase 6B API-level session policy validation — mock scenarios.

No live orders, no paper trades, no Alpaca submission.

Usage:
    .venv/bin/python scripts/test_phase6_market_session_policy_api.py
"""
import json, sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
except ImportError:
    ET = None

from phase6_market_session_policy import classify_market_session

RESULTS = []


def _et(y, m, d, h, mi):
    if ET:
        return datetime(y, m, d, h, mi, tzinfo=ET)
    return datetime(y, m, d, h, mi)


def run(name, now_et, expected_allowed, expected_session):
    r = classify_market_session(now_et)
    passed = r["allowed"] == expected_allowed and r["session"] == expected_session
    RESULTS.append({"scenario": name, "expected_allowed": expected_allowed,
                    "actual_allowed": r["allowed"], "expected_session": expected_session,
                    "actual_session": r["session"], "passed": passed, "reason": r["reason"]})


def main():
    print("Phase 6B — Session Policy API Mock Validation")
    print("=" * 60)

    run("regular_session_wed", _et(2026, 5, 13, 10, 30), True, "regular")
    run("premarket_wed", _et(2026, 5, 13, 7, 0), False, "premarket")
    run("afterhours_wed", _et(2026, 5, 13, 17, 0), False, "afterhours")
    run("weekend_sat", _et(2026, 5, 16, 10, 0), False, "weekend")
    run("weekend_sun", _et(2026, 5, 17, 10, 0), False, "weekend")
    run("holiday_newyear", _et(2026, 1, 1, 10, 0), False, "holiday")
    run("closed_night", _et(2026, 5, 13, 22, 0), False, "closed")
    run("open_boundary_930", _et(2026, 5, 13, 9, 30), True, "regular")
    run("close_boundary_1600", _et(2026, 5, 13, 16, 0), False, "afterhours")

    p = sum(1 for r in RESULTS if r["passed"])
    t = len(RESULTS)
    print(f"\n{'SCENARIO':<30} {'SESSION':>12} {'ALLOWED':>8} {'RESULT':>8}")
    print("-" * 60)
    for r in RESULTS:
        s = "PASS" if r["passed"] else "FAIL"
        print(f"{r['scenario']:<30} {r['actual_session']:>12} {str(r['actual_allowed']):>8} {s:>8}")
    print(f"\n{p}/{t} passed")

    out = PROJECT_ROOT / "docs/execution_safety/phase6_market_revalidation/v4_1_phase6b_session_policy_api_results.json"
    out.write_text(json.dumps({"date": datetime.now().isoformat(), "total": t,
                               "passed": p, "scenarios": RESULTS}, indent=2, default=str))
    print(f"\nResults: {out}")
    return 0 if p == t else 1


if __name__ == "__main__":
    sys.exit(main())
