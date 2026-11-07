"""ANCHOR: PROPOSAL_ALERT_RUN_EVIDENCE_20261107 — a quiet run still has to prove it ran.

WORK-QUEUE 2026-11-07, item 14. `send-telegram-proposal-alert` polls `*/2 9-16 * * 1-5` and was graded
`late — No run or output recorded since the latest scheduled time`. The cron was firing (journal shows
16:52, 16:54, 16:56, 16:58 ET on 2026-11-06); the lane simply prints nothing when no proposal needs an
alert, so `logs/proposal_alerts.log` — its only output signal — stopped advancing at 16:32 and the row
stayed late until Monday. The run now writes a LaneRunReceipt on every real run, and the registry's
output signal names that receipt.

Hermetic: a temporary state root, no database (the query is stubbed), no Telegram, no network.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from scripts.lib import jobs_history as J

ROOT = Path(__file__).resolve().parents[1]
ET = ZoneInfo("America/New_York")
LANE_ID = "send-telegram-proposal-alert"
RECEIPT_REL = f"data/runtime/{LANE_ID}_last.json"

sys.path.insert(0, str(ROOT / "scripts"))


def registry_row() -> dict:
    lanes = json.loads((ROOT / "config" / "lane_registry.json").read_text())["lanes"]
    return next(lane for lane in lanes if lane["lane_id"] == LANE_ID)


@pytest.fixture
def alert_module(monkeypatch, tmp_path):
    """The lane's script, with its only database call stubbed out and a private state root."""
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    import send_telegram_proposal_alert as module
    monkeypatch.setattr(module, "_db_query", lambda *a, **k: [])
    return module


def run_main(module, monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["send_telegram_proposal_alert.py", *argv])
    module.main()


def test_a_quiet_real_run_writes_a_receipt(alert_module, monkeypatch, tmp_path):
    run_main(alert_module, monkeypatch, "--mode", "pending", "--send")
    receipt = json.loads((tmp_path / RECEIPT_REL).read_text())
    assert receipt["lane_id"] == LANE_ID
    assert receipt["exit"] == 0
    assert receipt["produced_count"] == 0
    assert receipt["empty_reason"] == "no pending proposal needed an alert this run"
    assert receipt["started_at"]


def test_a_dry_run_writes_no_receipt(alert_module, monkeypatch, tmp_path):
    run_main(alert_module, monkeypatch, "--mode", "pending")  # default is dry-run
    assert not (tmp_path / RECEIPT_REL).exists()


def test_the_registry_output_signal_is_the_receipt_the_lane_writes():
    signal = registry_row()["output_signal"]
    assert signal["path"] == RECEIPT_REL
    assert signal["kind"] == "file_mtime"
    assert signal["evidence"] == "SCRIPT_RECEIPT"


FRIDAY = datetime(2026, 11, 6, tzinfo=ET)
LAST_SLOT = datetime(2026, 11, 6, 16, 58, tzinfo=ET)
FRIDAY_NIGHT = datetime(2026, 11, 6, 23, 15, tzinfo=ET)


def build(*, output_times=None, receipts=None, now_et=FRIDAY_NIGHT):
    now_utc = now_et.astimezone(ZoneInfo("UTC"))
    inputs = {"ledger_since": now_utc - timedelta(days=10), "journal_since": now_utc - timedelta(days=10),
              "output_times": output_times or {}, "receipts": receipts or {}}
    result = J.build({"lanes": [registry_row()]}, inputs, now=now_utc, trading_day=lambda day: day.isoweekday() <= 5)
    return next(row for row in result["rows"] if row["lane_id"] == LANE_ID)


def test_a_receipt_from_the_last_slot_clears_the_lateness(monkeypatch, tmp_path):
    """After the fix: the last run of the day is recorded, so Friday night is not late."""
    receipt = J.receipt_run({"started_at": LAST_SLOT.isoformat(),
                             "finished_at": (LAST_SLOT + timedelta(seconds=4)).isoformat(),
                             "ok": True, "exit": 0, "status": "ok"}, None)
    row = build(output_times={LANE_ID: LAST_SLOT}, receipts={LANE_ID: receipt})
    assert row["status"] != "late", row["status_reason"]
    assert row["last_run"]["result"] == "succeeded"


def test_a_log_that_stopped_early_is_still_late_before_the_fix():
    """The old evidence shape: only an activity log, frozen 26 minutes before the last slot."""
    row = build(output_times={LANE_ID: datetime(2026, 11, 6, 16, 32, tzinfo=ET)})
    assert row["status"] == "late"
    assert row["status_reason"] == "No run or output recorded since the latest scheduled time"
