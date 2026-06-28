#!/usr/bin/env python3
"""Broker order reconciliation taxonomy (P0-5) — pure, repeatable, no broker calls.

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


def _build(**kw):
    from brokers.reconcile_orders import build_reconcile_report
    return build_reconcile_report(kw.get("local", []), kw.get("pilots", []), kw.get("broker", []))


def test_clean_when_empty():
    r = _build()
    check("empty is clean", r["clean"] is True and r["total_findings"] == 0)


def test_filled_order_is_not_a_finding():
    # A matched, filled broker order produces no taxonomy findings.
    local = [{"intent_id": "i1", "correlation_id": "c1", "broker_order_id": "B1", "state": "WORKING"}]
    broker = [{"broker_order_id": "B1", "correlation_id": "c1", "status": "FILLED",
               "filled_qty": 10, "total_qty": 10}]
    r = _build(local=local, broker=broker)
    check("filled clean", r["counts"]["partial_fills"] == 0 and r["counts"]["rejected_orders"] == 0
          and r["counts"]["broker_missing_local"] == 0)


def test_partial_fill_detected():
    local = [{"intent_id": "i2", "correlation_id": "c2", "broker_order_id": "B2", "state": "WORKING"}]
    broker = [{"broker_order_id": "B2", "correlation_id": "c2", "status": "WORKING",
               "filled_qty": 4, "total_qty": 10}]
    r = _build(local=local, broker=broker)
    check("partial fill in taxonomy", r["counts"]["partial_fills"] == 1)
    check("partial fill preserved state",
          r["taxonomy"]["partial_fills"][0]["lifecycle_state"] == "PARTIALLY_FILLED")


def test_rejected_order_detected():
    local = [{"intent_id": "i3", "correlation_id": "c3", "broker_order_id": "B3", "state": "SUBMIT_REQUESTED"}]
    broker = [{"broker_order_id": "B3", "correlation_id": "c3", "status": "REJECTED"}]
    r = _build(local=local, broker=broker)
    check("rejected detected", r["counts"]["rejected_orders"] == 1)
    check("rejected has action", "action" in str(r["taxonomy"]["rejected_orders"][0]).lower())


def test_canceled_order_not_flagged_as_problem():
    local = [{"intent_id": "i4", "correlation_id": "c4", "broker_order_id": "B4", "state": "CANCEL_REQUESTED"}]
    broker = [{"broker_order_id": "B4", "correlation_id": "c4", "status": "CANCELED"}]
    r = _build(local=local, broker=broker)
    check("cancel not partial/reject/unknown",
          r["counts"]["partial_fills"] == 0 and r["counts"]["rejected_orders"] == 0
          and r["counts"]["unknown_statuses"] == 0)


def test_lost_response_orphan_submit_flagged():
    # Local submit, old, no broker order id, and broker returned nothing → stale + local-missing.
    local = [{"intent_id": "i5", "correlation_id": "c5", "broker_order_id": None,
              "state": "SUBMIT_REQUESTED", "age_minutes": 60}]
    r = _build(local=local, broker=[])
    check("orphan submit is stale", r["counts"]["stale_internal_orders"] == 1)


def test_duplicate_submit_both_visible():
    # Two pilot rows for the same intent — both active, no broker order. Both flagged.
    pilots = [
        {"intent_id": "i6", "correlation_id": "c6a", "broker_order_id": None,
         "status": "submitting", "age_minutes": 1, "symbol": "V"},
        {"intent_id": "i6", "correlation_id": "c6b", "broker_order_id": None,
         "status": "submitting", "age_minutes": 1, "symbol": "V"},
    ]
    r = _build(pilots=pilots, broker=[])
    check("both duplicate submits visible (local_missing_broker)",
          r["counts"]["local_missing_broker"] == 2)


def test_broker_order_missing_local_intent():
    broker = [{"broker_order_id": "ZZZ", "correlation_id": "unknown", "status": "WORKING"}]
    r = _build(local=[], broker=broker)
    check("broker order without local intent flagged", r["counts"]["broker_missing_local"] == 1)


def test_unknown_status_flagged():
    local = [{"intent_id": "i7", "correlation_id": "c7", "broker_order_id": "B7", "state": "WORKING"}]
    broker = [{"broker_order_id": "B7", "correlation_id": "c7", "status": "WEIRD_NEW_STATUS"}]
    r = _build(local=local, broker=broker)
    check("unknown status flagged", r["counts"]["unknown_statuses"] == 1)


def test_repeatable_same_inputs_same_output():
    local = [{"intent_id": "i8", "correlation_id": "c8", "broker_order_id": "B8", "state": "WORKING"}]
    broker = [{"broker_order_id": "B8", "correlation_id": "c8", "status": "WORKING",
               "filled_qty": 5, "total_qty": 10}]
    r1 = _build(local=local, broker=broker)
    r2 = _build(local=local, broker=broker)
    check("repeatable counts", r1["counts"] == r2["counts"])


ALL = [
    test_clean_when_empty, test_filled_order_is_not_a_finding, test_partial_fill_detected,
    test_rejected_order_detected, test_canceled_order_not_flagged_as_problem,
    test_lost_response_orphan_submit_flagged, test_duplicate_submit_both_visible,
    test_broker_order_missing_local_intent, test_unknown_status_flagged,
    test_repeatable_same_inputs_same_output,
]


if __name__ == "__main__":
    print("\n— reconcile orders taxonomy —")
    for t in ALL:
        try:
            t()
        except AssertionError:
            pass
    print(f"\n{PASS} passed, {FAIL} failed")
    raise SystemExit(1 if FAIL else 0)
