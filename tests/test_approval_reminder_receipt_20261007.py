"""An empty approval plan writes a run receipt and does not touch a send path."""
from __future__ import annotations

import json

from scripts.approval_package_reminder import main


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
