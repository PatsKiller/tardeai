#!/usr/bin/env python3
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


def test_transitions():
    from brokers.order_lifecycle import can_transition, transition, OrderState
    check("PROPOSED->PREFLIGHTED", can_transition("PROPOSED", "PREFLIGHTED"))
    check("illegal FILLED from PROPOSED", not can_transition("PROPOSED", "FILLED"))
    ev = transition("OPERATOR_APPROVED", "SUBMIT_REQUESTED", reason="test")
    check("submit requested ok", ev.get("ok"))


def test_broker_ack_required():
    from brokers.order_lifecycle import transition
    ev = transition("PREFLIGHTED", "FILLED")
    check("no fill without ack", not ev.get("ok"))


def test_idempotency_key_stable():
    from brokers.order_lifecycle import idempotency_key
    k1 = idempotency_key("i1", "schwab_taxable", "V")
    k2 = idempotency_key("i1", "schwab_taxable", "V")
    check("idempotency stable", k1 == k2 and len(k1) == 32)


def test_partial_fill_path():
    from brokers.order_lifecycle import can_transition
    check("WORKING->PARTIAL", can_transition("WORKING", "PARTIALLY_FILLED"))
    check("PARTIAL->FILLED", can_transition("PARTIALLY_FILLED", "FILLED"))


if __name__ == "__main__":
    print("\n— order lifecycle —")
    test_transitions()
    test_broker_ack_required()
    test_idempotency_key_stable()
    test_partial_fill_path()
    print(f"\n{PASS} passed, {FAIL} failed")
    raise SystemExit(1 if FAIL else 0)