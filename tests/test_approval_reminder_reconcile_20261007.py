"""Reconciling a past transport row does not send."""
from __future__ import annotations

from scripts.approval_reminder_reconcile import reconcile


def _receipt(**extra):
    body = {
        "schema": "ApprovalReminderReceipt@v1",
        "run_id": "run-1",
        "outcome": "PACKAGE_WRITTEN",
        "planner_status": "ACTIONS_PLANNED",
        "action_count": 1,
        "send_attempt_count": 1,
        "delivery_receipt_count": 0,
        "delivery_status": "DELIVERY_UNMEASURED",
    }
    body.update(extra)
    return body


def test_no_provider_id_stays_unmeasured():
    out = reconcile(_receipt(), [{"run_id": "run-1", "provider_message_id": ""}])
    assert out["delivery_status"] == "DELIVERY_UNMEASURED"
    assert out["delivery_observed"] is False


def test_one_provider_id_is_observed_and_a_duplicate_is_not_counted_twice():
    rows = [
        {"run_id": "run-1", "provider_message_id": "tg-1"},
        {"run_id": "run-1", "provider_message_id": "tg-1"},
        {"run_id": "other", "provider_message_id": "tg-2"},
    ]
    out = reconcile(_receipt(), rows)
    assert out["delivery_receipt_count"] == 1
    assert out["delivery_status"] == "DELIVERY_OBSERVED"
    assert out["delivery_observed"] is True


def test_empty_plan_is_not_rewritten_into_delivery():
    out = reconcile(_receipt(outcome="NO_ACTION", action_count=0, send_attempt_count=0), [{"run_id": "run-1", "provider_message_id": "tg-1"}])
    assert out["delivery_status"] == "NO_ACTION"
    assert out["delivery_receipt_count"] == 0
