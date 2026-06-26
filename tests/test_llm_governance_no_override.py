#!/usr/bin/env python3
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


def test_llm_approve_with_hard_block():
    from brokers.execution_readiness import evaluate_execution_readiness
    import options_desk_enterprise as ent
    proposal = {
        "intent_id": "x", "id": "p1", "strategy": "covered_call", "symbol": "TST",
        "data_source": "bs_estimate",
        "model_snapshot": {"verdict": "approve", "unlock_live": False},
    }
    blocks = ent.evaluate_hard_risk_blocks(proposal, mode="live")
    r = evaluate_execution_readiness(proposal, asset_class="option", mode="live")
    check("hard block exists", any(b["code"] == "bs_estimate_only" for b in blocks))
    check("readiness not ok with bs_estimate", not r["ok"] or r["mode"] == "blocked")


def test_llm_unlock_attempt_blocked():
    from brokers.execution_readiness import _llm_cannot_unlock
    g = _llm_cannot_unlock({"llm": {"unlock_live": True}})
    check("unlock attempt blocked", not g["ok"])


def test_missing_llm_does_not_enable_live():
    from brokers.execution_readiness import evaluate_execution_readiness
    r = evaluate_execution_readiness({"intent_id": "y"}, asset_class="equity", mode="live")
    check("missing llm does not grant live", r.get("autonomous_live_submit_allowed") is False)


if __name__ == "__main__":
    print("\n— llm governance —")
    test_llm_approve_with_hard_block()
    test_llm_unlock_attempt_blocked()
    test_missing_llm_does_not_enable_live()
    print(f"\n{PASS} passed, {FAIL} failed")
    raise SystemExit(1 if FAIL else 0)