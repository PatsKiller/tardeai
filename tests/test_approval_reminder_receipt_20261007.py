"""An empty approval plan writes a run receipt and does not touch a send path."""
from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.approval_package_reminder import (
    UncertainSend,
    build_run_receipt,
    liveness,
    main,
    same_runtime_target,
    write_run_receipt,
)


def _boom(exc: BaseException):
    raise exc


def test_empty_plan_writes_a_receipt_without_sending(tmp_path, capsys):
    ledger = tmp_path / "approval_packages.jsonl"
    ledger.write_text("", encoding="utf-8")
    receipt_path = tmp_path / "approval_package_reminder_last.json"
    code = main(["--ledger", str(ledger), "--receipt", str(receipt_path)])
    assert code == 0
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["schema"] == "ApprovalReminderReceipt@v1"
    assert receipt["actions"] == 0
    assert receipt["sent"] is False
    assert receipt["send_requested"] is False
    assert receipt["recorded"] is False
    assert receipt["consumer_receipt"] is None
    assert receipt["package_ledger_is_run_receipt"] is False
    assert "text" not in receipt
    assert ledger.read_text(encoding="utf-8") == ""
    captured = capsys.readouterr()
    assert "nothing due" in captured.out
    assert "send_telegram" not in captured.out
    assert receipt["planner_status"] == "NO_ACTION"
    assert receipt["outcome"] == "NO_ACTION"
    assert receipt["delivery_status"] == "NO_ACTION"
    assert receipt["delivery_receipt_count"] == 0
    assert receipt["run_observed"] is True
    assert receipt["adapter_return_is_delivery"] is False
    assert "SUCCESS" not in receipt.values()
    assert "sk-" not in json.dumps(receipt)
    assert "postgres://" not in json.dumps(receipt)


def _due_ledger(path: Path, now: datetime) -> None:
    from scripts.lib.approval_package import Ledger

    led = Ledger(path)
    led.append(
        {
            "event": "PACKAGE_CREATED",
            "package_id": "pkg-test",
            "package": {
                "state": "DRAFT",
                "items": [{"item_no": 1, "state": "PENDING"}],
                "notes": [],
                "expires_at": (now + timedelta(hours=20)).isoformat(),
            },
        }
    )
    led.append(
        {
            "event": "SUBMITTED",
            "package_id": "pkg-test",
            "ts": (now - timedelta(hours=5)).isoformat(),
        }
    )


def test_actionable_plan_records_without_calling_delivery(tmp_path):
    ledger = tmp_path / "approval_packages.jsonl"
    _due_ledger(ledger, datetime.now(timezone.utc))
    receipt_path = tmp_path / "receipt.json"
    calls: list[str] = []
    code = main(
        ["--ledger", str(ledger), "--receipt", str(receipt_path), "--record", "--send"],
        sender=lambda text: calls.append(text),
    )
    assert code == 0
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["outcome"] == "PACKAGE_WRITTEN"
    assert receipt["delivery_status"] == "DELIVERY_UNMEASURED"
    assert receipt["delivery_receipt_count"] == 0
    assert receipt["sent"] is True
    assert calls
    assert "APPROVE" not in json.dumps(receipt)
    assert "pkg-test" not in json.dumps(receipt)


def test_sender_refusal_and_timeout_do_not_claim_delivery(tmp_path):
    now = datetime.now(timezone.utc)
    ledger = tmp_path / "ledger.jsonl"
    _due_ledger(ledger, now)
    refused = tmp_path / "refused.json"
    code = main(
        ["--ledger", str(ledger), "--receipt", str(refused), "--send", "--record"],
        sender=lambda _text: _boom(RuntimeError("adapter down")),
    )
    assert code == 0
    body = json.loads(refused.read_text(encoding="utf-8"))
    assert body["error_class"] == "sender_refusal"
    assert body["delivery_status"] == "DELIVERY_UNMEASURED"
    assert body["sent"] is False

    ledger2 = tmp_path / "ledger2.jsonl"
    _due_ledger(ledger2, now)
    uncertain = tmp_path / "uncertain.json"
    code = main(
        ["--ledger", str(ledger2), "--receipt", str(uncertain), "--send", "--record"],
        sender=lambda _text: _boom(UncertainSend("maybe")),
    )
    assert code == 0
    body = json.loads(uncertain.read_text(encoding="utf-8"))
    assert body["error_class"] == "sender_timeout"
    assert body["delivery_status"] == "UNCERTAIN"
    assert body["delivery_receipt_count"] == 0


def test_crash_before_replace_keeps_the_previous_file(tmp_path):
    path = tmp_path / "receipt.json"
    path.write_text('{"schema":"keep"}\n', encoding="utf-8")
    receipt = build_run_receipt([], now=datetime.now(timezone.utc), send_requested=False, recorded=False, sent=False)
    with pytest.raises(RuntimeError, match="crash"):
        write_run_receipt(path, receipt, before_replace=lambda: _boom(RuntimeError("crash")))
    assert json.loads(path.read_text(encoding="utf-8"))["schema"] == "keep"


def test_success_is_refused(tmp_path):
    receipt = build_run_receipt([], now=datetime.now(timezone.utc), send_requested=False, recorded=False, sent=False)
    receipt["outcome"] = "SUCCESS"
    with pytest.raises(ValueError):
        write_run_receipt(tmp_path / "no.json", receipt)


def test_an_empty_plan_cannot_be_relabelled_as_delivery(tmp_path):
    now = datetime.now(timezone.utc)
    with pytest.raises(ValueError, match="empty plan"):
        build_run_receipt(
            [],
            now=now,
            send_requested=False,
            recorded=False,
            sent=False,
            delivery_status="DELIVERED",
        )
    quiet = build_run_receipt(
        [],
        now=now,
        send_requested=False,
        recorded=False,
        sent=False,
        error_class="sender_refusal",
    )
    assert quiet["delivery_status"] == "NO_ACTION"
    assert quiet["error_class"] is None
    quiet["delivery_status"] = "DELIVERED"
    with pytest.raises(ValueError, match="delivery"):
        write_run_receipt(tmp_path / "no.json", quiet)


def test_two_invocations_leave_one_complete_receipt(tmp_path):
    ledger = tmp_path / "empty.jsonl"
    ledger.write_text("", encoding="utf-8")
    path = tmp_path / "receipt.json"
    errors: list[BaseException] = []

    def run() -> None:
        try:
            main(["--ledger", str(ledger), "--receipt", str(path)])
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    body = json.loads(path.read_text(encoding="utf-8"))
    assert body["schema"] == "ApprovalReminderReceipt@v1"
    assert body["outcome"] == "NO_ACTION"


def test_symlink_identity_and_stale_receipt(tmp_path):
    real = tmp_path / "persistent"
    real.mkdir()
    link = tmp_path / "runtime"
    link.symlink_to(real, target_is_directory=True)
    other = tmp_path / "split"
    other.mkdir()
    assert same_runtime_target(link, real) is True
    assert same_runtime_target(link, other) is False
    old = datetime.now(timezone.utc) - timedelta(hours=5)
    receipt = build_run_receipt([], now=old, send_requested=False, recorded=False, sent=False)
    assert liveness(receipt, now=datetime.now(timezone.utc), max_age_s=3600) == "STALE"
    fresh = build_run_receipt([], now=datetime.now(timezone.utc), send_requested=False, recorded=False, sent=False)
    assert liveness(fresh, now=datetime.now(timezone.utc), max_age_s=3600) == "FRESH"
