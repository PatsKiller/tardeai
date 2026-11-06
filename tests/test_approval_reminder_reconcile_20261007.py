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


def test_a_written_reconcile_run_carries_an_explicit_ok(tmp_path):
    """The lane's receipt is measured by ok+as_of; a missing or unreadable receipt never writes one."""
    import json
    from scripts.approval_reminder_reconcile import main

    rp = tmp_path / "reminder.json"
    rp.write_text(json.dumps(_receipt(as_of="2026-10-07T00:00:00Z", ended_at="2026-10-07T00:00:00Z")))
    tp = tmp_path / "transport.jsonl"
    tp.write_text("")
    op = tmp_path / "out.json"
    assert main(["--receipt", str(rp), "--transport", str(tp), "--out", str(op), "--write"]) == 0
    doc = json.loads(op.read_text())
    assert doc["ok"] is True and doc["status"] == "RECONCILED"
