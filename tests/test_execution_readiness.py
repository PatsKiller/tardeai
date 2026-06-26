#!/usr/bin/env python3
import os
import sys
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} {detail}")


def test_live_locked_without_standing_unlock():
    from brokers.execution_readiness import evaluate_execution_readiness
    with mock.patch("brokers.execution_guard._live_future_unlocked", return_value=False):
        r = evaluate_execution_readiness(
            {"intent_id": "t1", "id": "p1", "strategy": "covered_call", "symbol": "V"},
            asset_class="option", account_key="schwab_taxable", mode="live",
        )
    gate = r.get("gate_results", {}).get("global_live_allowed", {})
    check("global gate fails when locked", gate.get("ok") is False)
    check("autonomous false", r.get("autonomous_live_submit_allowed") is False)
    check("evidence_hash present", bool(r.get("evidence_hash")))


def test_live_allowed_with_standing_unlock_still_needs_2fa():
    from brokers.execution_readiness import evaluate_execution_readiness
    with mock.patch("brokers.execution_guard._live_future_unlocked", return_value=True):
        with mock.patch("brokers.kill_switches.is_blocked", return_value=(False, [])):
            r = evaluate_execution_readiness(
                {"intent_id": "t1a", "id": "p1", "strategy": "covered_call", "symbol": "V"},
                asset_class="option", account_key="schwab_taxable", mode="live",
            )
    check("global gate passes when standing unlock", r.get("gate_results", {}).get("global_live_allowed", {}).get("ok"))
    check("still needs operator path or blocks", r.get("mode") in ("operator_required", "blocked", "dry_run"))


def test_llm_cannot_unlock():
    from brokers.execution_readiness import evaluate_execution_readiness
    r = evaluate_execution_readiness(
        {"intent_id": "t2", "model_snapshot": {"unlock_live": True, "override_risk": True}},
        asset_class="equity", mode="live",
    )
    blocks = [b["code"] for b in r.get("hard_blocks", [])]
    check("llm unlock blocked", "llm_advisory_only" in str(r.get("gate_results", {})) or not r["ok"])


def test_unknown_quote_fail_closed():
    from brokers.execution_readiness import evaluate_execution_readiness
    with mock.patch("brokers.execution_readiness._global_live_allowed",
                    return_value={"ok": True, "code": "global_live_allowed", "reason": "ok", "severity": "hard"}):
        with mock.patch("brokers.kill_switches.is_blocked", return_value=(False, [])):
            r = evaluate_execution_readiness(
                {"intent_id": "t3", "id": "p3", "strategy": "covered_call", "symbol": "RTX"},
                asset_class="option", account_key="schwab_taxable", mode="live",
            )
    gate = r.get("gate_results", {}).get("fresh_market_data", {})
    check("unknown quote fails closed", gate.get("ok") is False or r["mode"] == "blocked")


if __name__ == "__main__":
    print("\n— execution_readiness tests —")
    test_live_locked_without_standing_unlock()
    test_live_allowed_with_standing_unlock_still_needs_2fa()
    test_llm_cannot_unlock()
    test_unknown_quote_fail_closed()
    print(f"\n{PASS} passed, {FAIL} failed")
    raise SystemExit(1 if FAIL else 0)