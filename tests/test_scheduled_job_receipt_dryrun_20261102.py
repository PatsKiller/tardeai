"""Synthetic generic wrapper actions only; no registered job or live transport.

ANCHOR: SCHEDULED_JOB_RECEIPT_DRYRUN_20261102
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import socket
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
OLD = "2030-01-02T03:04:05Z"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def modules(monkeypatch, tmp_path):
    def forbidden(*args, **kwargs):
        raise AssertionError("No network, subprocess, registered job or receipt callback in dry-run")
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "synthetic-state"))
    wrapper = load("scripts.lib.scheduled_receipt_dryrun_test", "scripts/lib/scheduled_job_receipt.py")
    watchdog = load("scheduled_receipt_watchdog_test", "scripts/cron_outage_watchdog.py")
    return wrapper, watchdog, forbidden


def prior(path):
    path.write_bytes((json.dumps({"schema": "ScheduledJobReceipt@v1", "exit": 0,
                               "as_of": OLD, "ok_at": OLD, "summary": {"state": "completed"}}) + "\n").encode())
    return path.read_bytes(), path.stat().st_mtime_ns


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("flag", ["--dry-run", "--help", "-h"])
def test_inspection_preserves_canonical_and_watchdog_success(modules, monkeypatch, tmp_path, existing, flag):
    wrapper, watchdog, _ = modules
    receipt = tmp_path / "canonical.json"
    before = prior(receipt) if existing else None
    previous_success = watchdog.receipt_success(json.loads(before[0]), "ok_at") if before else None
    argv = ["synthetic_job.py", "--receipt", str(receipt), flag, "--synthetic", "unchanged"]
    monkeypatch.setattr(sys, "argv", argv[:])
    seen = []
    def action():
        seen.append(sys.argv[:])
        print("DRY-RUN: would evaluate synthetic input; no job execution")
        return 0
    assert wrapper.run_with_receipt(action, script="synthetic", root=tmp_path) == 0
    assert seen == [[argv[0], flag, "--synthetic", "unchanged"]]
    assert sys.argv == argv
    if existing:
        assert (receipt.read_bytes(), receipt.stat().st_mtime_ns) == before
        assert watchdog.receipt_success(json.loads(receipt.read_bytes()), "ok_at") == previous_success
    else:
        assert not receipt.exists()
        assert watchdog.receipt_success({}, "ok_at") is None
    assert sorted(p.name for p in tmp_path.iterdir()) == ([receipt.name] if existing else [])


@pytest.mark.parametrize("flag", ["--dry-run", "--help", "-h"])
def test_inspection_cannot_reach_receipt_or_summary_callbacks(modules, monkeypatch, tmp_path, flag):
    wrapper, _, forbidden = modules
    monkeypatch.setattr(wrapper, "atomic_write_json", forbidden)
    monkeypatch.setattr(wrapper, "_previous_ok_at", forbidden)
    monkeypatch.setattr(sys, "argv", ["synthetic.py", "--receipt", str(tmp_path / "absent" / "receipt.json"), flag])
    assert wrapper.run_with_receipt(lambda: 0, script="synthetic", root=tmp_path, summary_from=forbidden) == 0
    assert not (tmp_path / "absent").exists()


@pytest.mark.parametrize("result", [0, 7, {"pending": 3, "ignored": "synthetic"}])
def test_dryrun_preserves_nonexception_action_result(modules, monkeypatch, tmp_path, result):
    wrapper, _, forbidden = modules
    monkeypatch.setattr(wrapper, "atomic_write_json", forbidden)
    original = ["synthetic.py", "--dry-run"]
    monkeypatch.setattr(sys, "argv", original[:])
    assert wrapper.run_with_receipt(lambda: result, script="synthetic", root=tmp_path) == result
    assert sys.argv == original and not list(tmp_path.iterdir())


@pytest.mark.parametrize("exception", [SystemExit(0), SystemExit(4), RuntimeError("synthetic failure"), KeyboardInterrupt()])
def test_dryrun_preserves_exception_and_argv(modules, monkeypatch, tmp_path, exception):
    wrapper, _, forbidden = modules
    monkeypatch.setattr(wrapper, "atomic_write_json", forbidden)
    original = ["synthetic.py", "--dry-run"]
    monkeypatch.setattr(sys, "argv", original[:])
    def action():
        raise exception
    with pytest.raises(type(exception)) as got:
        wrapper.run_with_receipt(action, script="synthetic", root=tmp_path, summary_from=forbidden)
    assert got.value is exception and sys.argv == original and not list(tmp_path.iterdir())


@pytest.mark.parametrize("arguments", [[], ["--", "--dry-run"], ["--dry-run=false"], ["--plan"], ["--synthetic-value=--dry-run"]])
def test_only_explicit_control_dryrun_suppresses_existing_live_contract(modules, monkeypatch, tmp_path, arguments):
    wrapper, watchdog, _ = modules
    receipt = tmp_path / "live.json"
    original = ["synthetic.py", "--receipt", str(receipt), *arguments]
    monkeypatch.setattr(sys, "argv", original[:])
    def action():
        assert sys.argv == [original[0], *arguments]
        return 0
    assert wrapper.run_with_receipt(action, script="synthetic", root=tmp_path) == 0
    doc = json.loads(receipt.read_bytes())
    assert doc["schema"] == "ScheduledJobReceipt@v1" and doc["exit"] == 0
    assert doc["ok_at"] == doc["as_of"] and watchdog.receipt_success(doc, "ok_at") is not None
    assert "mode" not in doc and sys.argv == original


def test_live_failure_keeps_previous_success_and_diagnostics(modules, monkeypatch, tmp_path):
    wrapper, watchdog, _ = modules
    receipt = tmp_path / "live.json"
    old, _ = prior(receipt)
    before = watchdog.receipt_success(json.loads(old), "ok_at")
    monkeypatch.setattr(sys, "argv", ["synthetic.py", "--receipt", str(receipt)])
    def action():
        raise ValueError("synthetic detail must not be persisted")
    with pytest.raises(ValueError):
        wrapper.run_with_receipt(action, script="synthetic", root=tmp_path)
    doc = json.loads(receipt.read_bytes())
    assert doc["exit"] == 1 and doc["ok_at"] == OLD
    assert doc["summary"] == {"state": "failed", "exception_type": "ValueError"}
    assert "synthetic detail" not in receipt.read_text()
    assert watchdog.receipt_success(doc, "ok_at") == before
