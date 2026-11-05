"""FQ-117: the recovery lane must leave proof of useful work, not an exit code.

AGENTS rule 8 — exit 0 is not evidence of work. The runner writes one durable receipt per invocation carrying
a UTC clock, an invocation id, the concrete source it ran from, every step's outcome and the exit. These tests
run the real `main()` with every side-effecting step stubbed, so no DB, network, Telegram or file outside
tmp_path is touched.

ANCHOR: RECOVERY_WATCH_RUN_RECEIPT_20261104
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import recovery_watch_daily as R  # noqa: E402

#: Captured before any fixture stubs it, so a test can drive the REAL record builder against a failing writer.
REAL_CREATE_WATCH_RECORDS = R.create_watch_records


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


# ── FQ-117 R1/R2 (cx-openai-2 BLOCK at b80f0af9b) ───────────────────────────────────────────────────────────
# A receipt must distinguish "successful zero work" from "failed persistence", and the invocation must be durable
# BEFORE any mutable work — a crash has to leave evidence that a run began.

def test_failed_persistence_is_not_certified_as_success(stubbed, monkeypatch):
    """R1: `create_watch_records` swallows a failed insert and returns a count. A normal return was called ok."""
    calls = {"work": 0}
    monkeypatch.setattr(R, "detect_new_stopouts", lambda: [{"symbol": "SPCX", "account": "a", "exit_price": 1.0,
                                                            "stop_price": 2.0, "explicit_stop_out": True}])
    def boom(*a, **k):
        calls["work"] += 1
        raise RuntimeError("synthetic insert failure")
    monkeypatch.setattr(R, "_db_write", boom)
    monkeypatch.setattr(R, "create_watch_records", REAL_CREATE_WATCH_RECORDS)   # the real builder, not the stub

    with pytest.raises(R.StepFailed):
        R.main()

    receipt = _only_receipt(stubbed)
    assert calls["work"] == 1, "the insert was never attempted"
    assert receipt["outcome"] == "failed" and receipt["exit_code"] == 1
    step = [s for s in receipt["steps"] if s["name"] == "create_watch_records"][0]
    assert step["outcome"] == "failed"
    assert "synthetic insert failure" in (step["error"] or ""), step["error"]
    assert step["output"].get("failed") == 1 and step["output"].get("ok") is False


def test_the_invocation_is_durable_before_any_work_runs(stubbed, monkeypatch):
    """R2: the started record exists before the first step touches anything."""
    seen = {}
    def first_step():
        receipts = sorted(stubbed.glob("*.json"))
        seen["receipts_at_start"] = [p.name for p in receipts]
        seen["outcome_at_start"] = json.loads(receipts[0].read_text())["outcome"] if receipts else None
        return []
    monkeypatch.setattr(R, "detect_new_stopouts", first_step)
    R.main()
    assert len(seen["receipts_at_start"]) == 1, "no durable record existed when the first step ran"
    assert seen["outcome_at_start"] == "incomplete", "the started record must not claim a finished outcome"


def test_a_hard_death_leaves_the_started_record_behind(stubbed, monkeypatch):
    """R2: a process that dies mid-run leaves evidence that it began. os._exit in a child, as the reviewer did."""
    import subprocess
    script = (
        "import os, sys; sys.path.insert(0, %r);"
        "import recovery_watch_daily as R;"
        "R.detect_new_stopouts = lambda: os._exit(23);"
        "R.main()" % str(ROOT / "scripts")
    )
    env = {**os.environ, "RECOVERY_WATCH_RECEIPT_DIR": str(stubbed)}
    proc = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, env=env, timeout=60)
    assert proc.returncode == 23, proc.stderr[-500:]
    receipt = _only_receipt(stubbed)
    assert receipt["outcome"] == "incomplete"
    assert receipt["finished_at"] is None and receipt["exit_code"] is None


def test_an_unwritable_receipt_directory_means_the_lane_does_not_run(stubbed, monkeypatch, tmp_path):
    """R2: if the invocation cannot be recorded, no mutable work happens."""
    blocker = tmp_path / "blocked"
    blocker.write_text("not a directory")
    monkeypatch.setenv("RECOVERY_WATCH_RECEIPT_DIR", str(blocker))
    ran = {"step": False}
    def any_step():
        ran["step"] = True
        return []
    for name in ("detect_new_stopouts", "detect_relist_events", "review_active_items",
                 "scan_unconfirmed_stops", "compute_temp_allocations"):
        monkeypatch.setattr(R, name, any_step)
    with pytest.raises(RuntimeError):
        R.main()
    assert ran["step"] is False, "the workload ran even though the invocation could not be recorded"


def test_the_directory_is_fsynced_after_the_rename(stubbed, monkeypatch, tmp_path):
    """R2: fsyncing the file proves the bytes, not that the name was published."""
    fsynced = []
    real = os.fsync
    monkeypatch.setattr(os, "fsync", lambda fd: (fsynced.append(fd), real(fd))[1])
    target = tmp_path / "receipts"
    target.mkdir()
    R.write_run_receipt({"schema": "x", "invocation_id": "abc", "started_at": "2026-11-04T00:00:00+00:00"}, target)
    assert len(fsynced) >= 2, "only the file was fsynced; the directory entry was never published durably"
