"""The reconciler as a scheduled lane (2026-10-07).

Measured on served c5de69ee9: the reminder sent via telegram_alert and recorded no transport row,
and the reconciler had no entry point and no schedule, so DELIVERY_OBSERVED could never occur. Now
the reminder appends an ApprovalReminderTransport@v1 row (ids only) per provider message id it
gets back from the transport, and the reconciler runs at minute 12 and turns matched rows into
DELIVERY_OBSERVED. Adapter success without an id stays DELIVERY_UNMEASURED."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from scripts import approval_package_reminder as apr  # noqa: E402
from scripts import approval_reminder_reconcile as arr  # noqa: E402
from datetime import datetime, timezone  # noqa: E402

from test_approval_reminder_receipt_20261007 import _due_ledger  # noqa: E402


def _run_reminder(tmp_path, *, ids):
    ledger = tmp_path / "approval_packages.jsonl"
    _due_ledger(ledger, datetime.now(timezone.utc))
    receipt = tmp_path / "last.json"
    transport = tmp_path / "transport.jsonl"
    code = apr.main(["--ledger", str(ledger), "--receipt", str(receipt), "--transport", str(transport), "--send", "--record"],
                    sender=lambda text: None, provider_ids=lambda: list(ids))
    assert code == 0
    return receipt, transport


def test_reminder_writes_one_transport_row_per_provider_id(tmp_path):
    receipt, transport = _run_reminder(tmp_path, ids=["tg-100"])
    rec = json.loads(receipt.read_text())
    rows = [json.loads(l) for l in transport.read_text().splitlines()]
    assert rec["delivery_status"] == "DELIVERY_UNMEASURED" and rec["transport_rows_written"] == len(rows) >= 1
    assert all(r["run_id"] == rec["run_id"] and r["provider_message_id"] == "tg-100" for r in rows)
    assert all(set(r) <= {"schema", "run_id", "provider_message_id", "channel", "at"} for r in rows)   # ids only


def test_reconcile_lane_observes_delivery_only_from_matching_ids(tmp_path):
    receipt, transport = _run_reminder(tmp_path, ids=["tg-100"])
    out = tmp_path / "reconcile_last.json"
    assert arr.main(["--receipt", str(receipt), "--transport", str(transport), "--out", str(out)]) == 0   # dry run
    assert json.loads(receipt.read_text())["delivery_status"] == "DELIVERY_UNMEASURED" and not out.exists()
    assert arr.main(["--receipt", str(receipt), "--transport", str(transport), "--out", str(out), "--write"]) == 0
    rec = json.loads(receipt.read_text())
    run = json.loads(out.read_text())
    assert rec["delivery_status"] == "DELIVERY_OBSERVED" and rec["delivery_receipt_count"] >= 1 and rec["reconciled_at"]
    assert run["schema"] == "ApprovalReminderReconcileRun@v1" and run["status"] == "RECONCILED" and run["written"] is True


def test_no_id_from_the_transport_stays_unmeasured(tmp_path):
    receipt, transport = _run_reminder(tmp_path, ids=[])
    assert not transport.exists()
    out = tmp_path / "r.json"
    assert arr.main(["--receipt", str(receipt), "--transport", str(transport), "--out", str(out), "--write"]) == 0
    assert json.loads(receipt.read_text())["delivery_status"] == "DELIVERY_UNMEASURED"


def test_empty_hour_reconciles_to_no_action_and_missing_receipt_is_quiet(tmp_path):
    rpath = tmp_path / "last.json"
    rpath.write_text(json.dumps({"schema": "ApprovalReminderReceipt@v1", "run_id": "r0", "outcome": "NO_ACTION",
                                 "action_count": 0, "delivery_status": "NO_ACTION", "delivery_receipt_count": 0}))
    assert arr.main(["--receipt", str(rpath), "--transport", str(tmp_path / "none.jsonl"), "--out", str(tmp_path / "o.json"), "--write"]) == 0
    assert json.loads(rpath.read_text())["delivery_status"] == "NO_ACTION"
    assert arr.main(["--receipt", str(tmp_path / "absent.json"), "--transport", str(tmp_path / "none.jsonl")]) == 0


def test_lane_row_declares_the_reconciler():
    lanes = {l["lane_id"]: l for l in json.loads((ROOT / "config" / "lane_registry.json").read_text(encoding="utf-8"))["lanes"]}
    lane = lanes["approval-reminder-reconcile"]
    assert lane["state"] == "ACTIVE" and "approval_reminder_reconcile.py" in lane["scheduler"]["match"]
    assert lane["output_signal"]["path"] == "data/runtime/approval_reminder_reconcile_last.json"
