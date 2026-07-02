#!/usr/bin/env python3
"""Tests for broker_proposal_queue_ops + proposalBlockers parity."""
import sys
from pathlib import Path

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


def test_blocker_category():
    import broker_proposal_queue_ops as bqo
    check("strategy cat", bqo._blocker_category("Strategy still a watchlist sleeve") == "strategy")
    check("trade plan cat", bqo._blocker_category("No authoritative trade plan") == "trade_plan")


def test_reconcile_dry_run():
    import broker_proposal_queue_ops as bqo
    r = bqo.reconcile_sleeve_strategies(dry_run=True)
    check("reconcile ok", r.get("ok") is True)


def test_queue_summary():
    import broker_proposal_queue_ops as bqo
    r = bqo.compute_queue_summary()
    check("summary ok", r.get("ok") is True)
    check("has total", "total" in r)


ALL = [test_blocker_category, test_reconcile_dry_run, test_queue_summary]

if __name__ == "__main__":
    print("\n— broker proposal queue ops —")
    for t in ALL:
        try:
            t()
        except Exception as ex:
            FAIL += 1
            print(f"  [FAIL] {t.__name__} {ex}")
    print(f"\n{PASS} passed, {FAIL} failed")
    raise SystemExit(1 if FAIL else 0)