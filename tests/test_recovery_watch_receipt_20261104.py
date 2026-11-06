"""FQ-117: the recovery lane must leave proof of useful work, not an exit code.

AGENTS rule 8 — exit 0 is not evidence of work. The runner writes one durable receipt per invocation carrying
a UTC clock, an invocation id, the concrete source it ran from, every step's outcome and the exit. These tests
run the real `main()` with every side-effecting step stubbed, so no DB, network, Telegram or file outside
tmp_path is touched.

ANCHOR: RECOVERY_WATCH_RUN_RECEIPT_20261104
"""
from __future__ import annotations

import hashlib
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


# ── FQ-117 (codex P0 recovery measurement, 2026-11-05): "log Complete ≠ useful-work receipt" and the
#    "historical executed release UNKNOWN" gap. These read the durable record, never the log's mtime. ──


def _write(stubbed, doc) -> None:
    import json as _json
    stubbed.mkdir(parents=True, exist_ok=True)
    (stubbed / "r.json").write_text(_json.dumps(doc))


def _receipt(stubbed, **over) -> dict:
    doc = {"schema": "RecoveryWatchRunReceipt@v1", "invocation_id": "abc123", "started_at": "2026-11-05T06:00:00+00:00",
           "finished_at": "2026-11-05T06:01:00+00:00", "outcome": "ok", "error": None,
           "steps": [{"name": "detect_new_stopouts", "ok": True}, {"name": "create_watch_records", "ok": True}],
           "summary": {"new_stopouts": 2}, "source": {"script": str(R.__file__),
                                                     "script_sha256": hashlib.sha256(Path(R.__file__).read_bytes()).hexdigest()},
           "logs": {}}
    doc.update(over)
    return doc


def test_status_is_useful_only_when_the_last_run_finished_and_every_step_ok(stubbed):
    import json as _json
    _write(stubbed, _receipt(stubbed))
    status = R.receipt_status(stubbed)
    assert status["ran"] is True and status["useful_work_verified"] is True
    assert status["steps_failed"] == [] and status["summary"] == {"new_stopouts": 2}
    assert status["source_binding"]["state"] in ("bound", "changed")


def test_status_refuses_to_call_a_failed_step_useful(stubbed):
    import json as _json
    doc = _receipt(stubbed, steps=[{"name": "detect_new_stopouts", "ok": True},
                                   {"name": "check_and_escalate", "ok": False, "failed": 1}])
    _write(stubbed, doc)
    status = R.receipt_status(stubbed)
    assert status["useful_work_verified"] is False
    assert status["steps_failed"] == ["check_and_escalate"]


def test_status_on_an_incomplete_run_is_not_useful_and_says_so(stubbed):
    import json as _json
    _write(stubbed, _receipt(stubbed, outcome="incomplete", summary=None))
    status = R.receipt_status(stubbed)
    assert status["useful_work_verified"] is False and status["outcome"] == "incomplete"


def test_no_receipt_is_reported_rather_than_invented(stubbed):
    status = R.receipt_status(stubbed)
    assert status["ran"] is False and status["useful_work_verified"] is False
    assert "no run receipt" in status["detail"]


def test_source_binding_marks_a_pre_receipt_run_unknown_never_guessed():
    assert R.source_binding({"source": {}})["state"] == "unknown"
    assert R.source_binding(None)["state"] == "unknown"


def test_source_binding_separates_bound_changed_and_absent(tmp_path):
    script = tmp_path / "run.py"
    script.write_text("print('one')\n")
    digest = __import__("hashlib").sha256(script.read_bytes()).hexdigest()
    assert R.source_binding({"source": {"script": str(script), "script_sha256": digest}})["state"] == "bound"
    script.write_text("print('a later release')\n")
    changed = R.source_binding({"source": {"script": str(script), "script_sha256": digest}})
    assert changed["state"] == "changed" and changed["script_sha256"] == digest
    assert changed["observed_sha256"] != digest
    assert R.source_binding({"source": {"script": str(tmp_path / "gone.py"), "script_sha256": digest}})["state"] == "absent"


# ── Review F1/F2/F3 on #2674: the report must say what actually happened ──────────────────

def _reminder():
    return {"symbol": "SPCX", "account": "acct-1", "market_value": 100.0, "pct": 1.0, "reminder_num": 1}


def test_a_failed_stop_reminder_page_is_not_certified_as_sent(monkeypatch):
    """F1: the transport raises while the audit row succeeds — the report must still say failed."""
    import types

    def _down(*_a, **_k):
        raise RuntimeError("telegram down")

    rows = []
    monkeypatch.setitem(sys.modules, "telegram_alert", types.SimpleNamespace(send_telegram=_down))
    monkeypatch.setitem(sys.modules, "db_adapter",
                        types.SimpleNamespace(save_notification_log_entry=rows.append))

    report = R.send_stop_reminders([_reminder()])

    assert report["ok"] is False
    assert report["sent"] == 0
    assert report["failed"] == 1
    assert "telegram down" in report["error"]
    # The step machinery agrees, so the run receipt cannot call this step ok.
    assert R._step_failure(report)
    # And the audit row does not claim the page was sent.
    assert rows and rows[0]["status"] == "failed" and "telegram down" in (rows[0]["error"] or "")


def test_a_delivered_stop_reminder_page_reports_sent(monkeypatch):
    import types

    calls = []
    monkeypatch.setitem(sys.modules, "telegram_alert",
                        types.SimpleNamespace(send_telegram=lambda *a, **k: calls.append((a, k))))
    monkeypatch.setitem(sys.modules, "db_adapter",
                        types.SimpleNamespace(save_notification_log_entry=lambda row: None))

    report = R.send_stop_reminders([_reminder()])

    assert report == {"sent": 1, "failed": 0, "ok": True, "error": None}
    assert calls and calls[0][1].get("priority") == "P1"


def test_an_optional_reply_step_that_ran_and_failed_is_recorded_once(stubbed, monkeypatch):
    """F2: one step, one row — `failed`, never also `skipped`."""
    import types

    def _boom():
        raise RuntimeError("reply store down")

    monkeypatch.setitem(sys.modules, "telegram_reply_processor",
                        types.SimpleNamespace(process_replies=_boom))
    R.main()
    receipt = _only_receipt(stubbed)

    rows = [s for s in receipt["steps"] if s["name"] == "process_telegram_replies"]
    assert len(rows) == 1, rows
    assert rows[0]["outcome"] == "failed"
    assert "reply store down" in rows[0]["error"]
    # Optional: the run itself still finishes, but it is not certified as all-steps-ok.
    assert receipt["outcome"] == "ok"
    assert R.receipt_status(stubbed)["useful_work_verified"] is False


def test_a_failed_directory_fsync_is_reported_not_swallowed(tmp_path, monkeypatch, capsys):
    """F3: the durability the receipt claims is the durability it got — or it says otherwise."""
    real_fsync = R.os.fsync
    calls = {"n": 0}

    def flaky(fd):
        calls["n"] += 1
        if calls["n"] >= 2:  # first call fsyncs the file, second the directory
            raise OSError("fsync refused (probe)")
        return real_fsync(fd)

    monkeypatch.setattr(R.os, "fsync", flaky)
    path = R.write_run_receipt(
        {"started_at": "2026-11-05T00:00:00Z", "invocation_id": "probe", "outcome": "ok"}, tmp_path)

    assert path.exists()
    assert "directory fsync failed" in capsys.readouterr().err
