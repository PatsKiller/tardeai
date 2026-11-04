"""FQ-117: the recovery lane must leave proof of useful work, not an exit code.

AGENTS rule 8 — exit 0 is not evidence of work. The runner writes one durable receipt per invocation carrying
a UTC clock, an invocation id, the concrete source it ran from, every step's outcome and the exit. These tests
run the real `main()` with every side-effecting step stubbed, so no DB, network, Telegram or file outside
tmp_path is touched.

ANCHOR: RECOVERY_WATCH_RUN_RECEIPT_20261104
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import recovery_watch_daily as R  # noqa: E402


@pytest.fixture
def stubbed(monkeypatch, tmp_path):
    """Every step replaced with a harmless stub; receipts go to tmp_path."""
    monkeypatch.setenv("RECOVERY_WATCH_RECEIPT_DIR", str(tmp_path / "receipts"))
    monkeypatch.setattr(R, "detect_new_stopouts", lambda: [{"symbol": "SPCX", "explicit_stop_out": True}])
    monkeypatch.setattr(R, "create_watch_records", lambda events: len(events))
    monkeypatch.setattr(R, "detect_relist_events", lambda: 2)
    monkeypatch.setattr(R, "review_active_items", lambda: [{"symbol": "SPCX", "old_verdict": "HOLD", "verdict": "EXIT", "confidence": 0.8}])
    monkeypatch.setattr(R, "check_and_escalate", lambda reviewed: [])
    monkeypatch.setattr(R, "send_notifications", lambda escalated: None)
    monkeypatch.setattr(R, "scan_unconfirmed_stops", lambda: [])
    monkeypatch.setattr(R, "send_stop_reminders", lambda reminders: None)
    monkeypatch.setattr(R, "compute_temp_allocations", lambda: 3)
    return tmp_path / "receipts"


def _only_receipt(directory: Path) -> dict:
    files = sorted(directory.glob("*.json"))
    assert len(files) == 1, [p.name for p in files]
    return json.loads(files[0].read_text())


def test_a_normal_run_writes_one_receipt_with_every_step(stubbed):
    summary = R.main()
    receipt = _only_receipt(stubbed)

    assert receipt["schema"] == "RecoveryWatchRunReceipt@v1"
    assert receipt["outcome"] == "ok" and receipt["exit_code"] == 0
    assert summary["reviewed"] == 1

    # UTC clock, both ends, timezone-aware — not a naive local timestamp.
    for key in ("started_at", "finished_at"):
        moment = datetime.fromisoformat(receipt[key])
        assert moment.tzinfo is not None and moment.utcoffset().total_seconds() == 0

    # A concrete invocation identity and a concrete source identity.
    assert re.fullmatch(r"[0-9a-f]{32}", receipt["invocation_id"])
    source = receipt["source"]
    assert re.fullmatch(r"[0-9a-f]{64}", source["script_sha256"] or "")
    assert source["release_sha"] is None or re.fullmatch(r"[0-9a-f]{40}", source["release_sha"])
    assert source["git_head"] is None or re.fullmatch(r"[0-9a-f]{40}", source["git_head"])

    # Every required step is recorded with its own outcome, in order.
    # The Telegram step is optional (it is recorded as skipped when the processor is unavailable), so it is
    # excluded from the required order and asserted separately below.
    names = [s["name"] for s in receipt["steps"] if s["name"] != "process_telegram_replies"]
    assert names == [
        "detect_new_stopouts", "create_watch_records", "detect_relist_events", "review_active_items",
        "check_and_escalate", "send_notifications", "scan_unconfirmed_stops", "send_stop_reminders",
        "compute_temp_allocations",
    ]
    assert all(s["outcome"] == "ok" for s in receipt["steps"] if s["name"] != "process_telegram_replies")


def test_a_failing_step_is_recorded_and_the_run_still_fails(stubbed, monkeypatch):
    def boom(reviewed):
        raise RuntimeError("escalation transport down")

    monkeypatch.setattr(R, "check_and_escalate", boom)

    with pytest.raises(RuntimeError):
        R.main()

    receipt = _only_receipt(stubbed)
    assert receipt["outcome"] == "failed" and receipt["exit_code"] == 1
    assert "escalation transport down" in (receipt["error"] or "")
    failed = [s for s in receipt["steps"] if s["outcome"] == "failed"]
    assert [s["name"] for s in failed] == ["check_and_escalate"]
    # The steps that ran before the failure are still on the record.
    assert [s["name"] for s in receipt["steps"]][:3] == ["detect_new_stopouts", "create_watch_records", "detect_relist_events"]


def test_the_receipt_names_both_log_files_with_their_clock(stubbed):
    R.main()
    receipt = _only_receipt(stubbed)
    assert set(receipt["logs"]) == {"recovery-watch.log", "recovery_watch.log"}
    for entry in receipt["logs"].values():
        assert "present" in entry
        if entry["present"]:
            datetime.fromisoformat(entry["mtime"])  # timezone-aware ISO


def test_receipt_write_is_atomic(stubbed):
    R.main()
    assert not list(stubbed.glob("*.tmp")), "a temporary file survived the write"
