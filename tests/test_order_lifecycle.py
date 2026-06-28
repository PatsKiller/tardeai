#!/usr/bin/env python3
"""Order lifecycle + broker-truth status taxonomy + idempotency (P0-5).

Runs under pytest and standalone.
"""
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
    assert cond, f"{name} {detail}"


def test_transitions():
    from brokers.order_lifecycle import can_transition, transition
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


# ── Broker status normalization (recorded fixtures) ──

def test_normalize_filled():
    from brokers.order_lifecycle import normalize_broker_status
    n = normalize_broker_status("FILLED", filled_qty=10, total_qty=10)
    check("filled -> FILLED", n["lifecycle_state"] == "FILLED" and n["normalized"] == "filled")


def test_normalize_partial_fill_preserved():
    from brokers.order_lifecycle import normalize_broker_status
    n = normalize_broker_status("WORKING", filled_qty=3, total_qty=10)
    check("partial preserved", n["normalized"] == "partially_filled"
          and n["lifecycle_state"] == "PARTIALLY_FILLED")


def test_normalize_cancel_reject_expire():
    from brokers.order_lifecycle import normalize_broker_status
    check("canceled", normalize_broker_status("CANCELED")["lifecycle_state"] == "CANCELLED")
    check("cancelled alt spelling", normalize_broker_status("CANCELLED")["lifecycle_state"] == "CANCELLED")
    check("rejected", normalize_broker_status("REJECTED")["lifecycle_state"] == "REJECTED")
    check("expired", normalize_broker_status("EXPIRED")["lifecycle_state"] == "EXPIRED")


def test_normalize_unknown_fails_to_reconcile():
    from brokers.order_lifecycle import normalize_broker_status
    n = normalize_broker_status("SOME_NEW_SCHWAB_STATUS")
    check("unknown -> ERROR_RECONCILE_REQUIRED",
          n["normalized"] == "unknown" and n["lifecycle_state"] == "ERROR_RECONCILE_REQUIRED")


def test_normalize_pending_activation_is_acked_not_live():
    from brokers.order_lifecycle import normalize_broker_status
    n = normalize_broker_status("PENDING_ACTIVATION")
    check("pending_activation acked not live", n["lifecycle_state"] == "BROKER_ACKED" and not n["is_live"])


def test_apply_status_requires_broker_order_id_for_live():
    from brokers.order_lifecycle import apply_broker_status
    r = apply_broker_status("SUBMIT_REQUESTED", "WORKING", broker_order_id=None)
    check("working without boid -> reconcile", not r["ok"] and r["to"] == "ERROR_RECONCILE_REQUIRED")
    r2 = apply_broker_status("BROKER_ACKED", "WORKING", broker_order_id="BRK123")
    check("working with boid + acked ok", r2["ok"] and r2["to"] == "WORKING")


def test_apply_status_no_fill_without_broker_truth():
    from brokers.order_lifecycle import apply_broker_status
    r = apply_broker_status("BROKER_ACKED", "FILLED", broker_order_id=None)
    check("no fill without boid", not r["ok"] and r["to"] == "ERROR_RECONCILE_REQUIRED")


def test_duplicate_active_submit_blocked():
    from brokers.order_lifecycle import idempotency_key, is_duplicate_active_submit
    k = idempotency_key("i1", "schwab_taxable", "V")
    existing = [{"idempotency_key": k, "status": "submitting"}]
    check("duplicate active submit detected", is_duplicate_active_submit(k, existing) is True)
    existing2 = [{"idempotency_key": k, "status": "filled"}]
    check("terminal prior allows resubmit", is_duplicate_active_submit(k, existing2) is False)
    k2 = idempotency_key("i2", "schwab_taxable", "V")
    check("different key not duplicate", is_duplicate_active_submit(k2, existing) is False)


def test_stale_submit_requires_reconcile():
    from brokers.order_lifecycle import submit_requires_reconcile
    check("old orphan submit needs reconcile",
          submit_requires_reconcile("submitting", broker_order_id=None, age_minutes=45) is True)
    check("acked submit does not", submit_requires_reconcile("submitting", broker_order_id="B1", age_minutes=45) is False)
    check("fresh submit does not", submit_requires_reconcile("submitting", broker_order_id=None, age_minutes=2) is False)


ALL = [
    test_transitions, test_broker_ack_required, test_idempotency_key_stable, test_partial_fill_path,
    test_normalize_filled, test_normalize_partial_fill_preserved, test_normalize_cancel_reject_expire,
    test_normalize_unknown_fails_to_reconcile, test_normalize_pending_activation_is_acked_not_live,
    test_apply_status_requires_broker_order_id_for_live, test_apply_status_no_fill_without_broker_truth,
    test_duplicate_active_submit_blocked, test_stale_submit_requires_reconcile,
]


if __name__ == "__main__":
    print("\n— order lifecycle + broker taxonomy —")
    for t in ALL:
        try:
            t()
        except AssertionError:
            pass
    print(f"\n{PASS} passed, {FAIL} failed")
    raise SystemExit(1 if FAIL else 0)
