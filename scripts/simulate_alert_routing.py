#!/usr/bin/env python3
"""Simulate alert routing for ALERT-FATIGUE-1 verification."""
import argparse, json, os, sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

JUN25_CASES = [
    ("⚡ Trade AI LIVE [09:50]\n🎯 NEW GO — EHGO score=41 RVOL 19.7x", "suppressed"),
    ("❓ Paper Proposal: GDHG\nStrategy: Sector Rotation\n/ptreject 606", "primary"),
    ("🚨 STOP_TRIGGERED — CACI\nTrigger: stop_price 475.38", "primary"),
    ("🔭 Hermes watchlist alerts:\n⤴ AMD jumped to Hermes rank #1471", "suppressed"),
    ("⚠️ Health Agent: DEGRADED — 84/100\ndata:100", "suppressed"),
    ("🔍 Investigating 5 escalation(s) via local LLM:", "suppressed"),
    ("☀️ MORNING COMMAND — Jun 25, 2026\n--- Portfolio ---", "primary"),
]

CASES = [
    ("ATP REVIEW ALERT -- STOP CROSSED PENDING\nSymbol: ASPN\nApproval: BLOCKED\nPaper mode. No order submitted.", "suppressed"),
    ("ATP REVIEW ALERT -- LARGE MOVE BEFORE REVIEW\nSymbol: NWG\nStatus: PENDING", "suppressed"),
    ("PROPOSAL REJECTED: BCS dividend_growth_compounder — classifier_health", "suppressed"),
    ("PROPOSAL DEFERRED: MUD recovery_watch — B-1 bucket2", "suppressed"),
    ("PROPOSAL DENIED: ARM — quote stale", "suppressed"),
    ("dry_run_approved: CMCSA dividend_growth_compounder", "suppressed"),
    ("TRADE OPENED: CMCSA 120 shares @ $24.97 — dividend_growth_compounder", "primary"),
    ("TRADE CLOSED: INFU earnings_catalyst — target hit @ $9.34 P&L +$261", "primary"),
    ("STOP HIT: GCTS momentum_scalp — stopped @ $1.37 P&L -$225", "primary"),
    ("TRAILING STOP TRIGGERED: FLYW swing_trade — trailed to $16.50", "primary"),
    ("CRITICAL NEWS AUTO-CLOSE: XYZ — trading halt detected", "primary"),
    ("Approval: BLOCKED\nNo order submitted\nPaper mode.", "suppressed"),
    ("ENTRY_FILLED: NWG 189 shares @ $15.84", "primary"),
    ("EXIT_FILLED: ASPN 553 shares @ $5.96", "primary"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output-md", type=str)
    ap.add_argument("--output-json", type=str)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    from telegram_alert_router import should_send_telegram, classify_alert

    results = []
    passed = 0
    failed = 0

    all_cases = CASES + JUN25_CASES
    for msg, expected in all_cases:
        would_send = should_send_telegram(msg)
        level = classify_alert(msg)
        actual = "primary" if would_send else "suppressed"
        ok = actual == expected
        if ok:
            passed += 1
        else:
            failed += 1
        results.append({
            "message": msg[:60],
            "expected": expected,
            "actual": actual,
            "level": level,
            "pass": ok,
        })
        if args.verbose:
            status = "PASS" if ok else "FAIL"
            print(f"  {status} [{level}] {msg[:50]}... → {actual} (expected {expected})")

    report = {"passed": passed, "failed": failed, "total": len(all_cases), "results": results}

    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        with open(args.output_json, "w") as f:
            json.dump(report, f, indent=2)

    if args.output_md:
        Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
        with open(args.output_md, "w") as f:
            f.write(f"# Alert Routing Simulation\n\n")
            f.write(f"Passed: {passed}/{len(all_cases)}\n\n")
            f.write("| Message | Expected | Actual | Level | Pass |\n|---|---|---|---|---|\n")
            for r in results:
                f.write(f"| {r['message']} | {r['expected']} | {r['actual']} | {r['level']} | {'Y' if r['pass'] else 'N'} |\n")

    print(f"\nSimulation: {passed}/{len(all_cases)} passed, {failed} failed")


if __name__ == "__main__":
    os.chdir(str(PROJECT_ROOT))
    main()
