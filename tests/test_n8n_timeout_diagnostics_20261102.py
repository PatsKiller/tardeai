"""Synthetic child-timeout capture: no scheduled workload, live store or network."""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("timeout_executor_under_test", ROOT / "scripts/n8n_run_executor.py")
X = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = X
SPEC.loader.exec_module(X)


class FakeChild:
    pid = 42
    returncode = -9

    def __init__(self, final=("final progress", "RuntimeError: fixture deadline"), partial=(b"early", b"early error")):
        self.final = final
        self.partial = partial
        self.calls = []

    def communicate(self, timeout=None):
        self.calls.append(("communicate", timeout))
        if timeout is not None:
            raise subprocess.TimeoutExpired(["fixture"], timeout, output=self.partial[0], stderr=self.partial[1])
        return self.final

    def kill(self):
        self.calls.append(("kill", None))


def spawn(monkeypatch, tmp_path, runner):
    monkeypatch.setattr(X.time, "time", lambda: 10.0)
    rec = {"schema": "RunReceipt@v1", "run_id": "fixture-timeout-run", "lane_id": "fixture-lane",
           "state": "RUNNING", "exit_code": None, "started_at": "1970-01-01T00:00:05Z"}
    return X._spawn(rec, {"lock_kind": "safe_flock"}, ["fixture"], runner, 60, {}, tmp_path, None, False, 5.0)


@pytest.mark.parametrize(("out", "err"), [
    ("progress", "RuntimeError: fixture"),
    (b"progress\xff", b"RuntimeError: fixture\xff"),
    (None, None),
])
def test_spawn_keeps_bytes_strings_or_absence_without_inventing_a_child_exit(monkeypatch, tmp_path, out, err):
    def runner(*args, **kwargs):
        assert kwargs["timeout"] == 60 + X.KILL_AFTER_S + 30
        raise subprocess.TimeoutExpired(["fixture"], kwargs["timeout"], output=out, stderr=err)

    rec = spawn(monkeypatch, tmp_path, runner)
    assert rec["state"] == "RUN_TIMEOUT" and rec["reason"] == "executor_deadline"
    assert rec["timed_out"] is True and rec["exit_code"] is None and rec["duration_s"] == 5.0
    expected_out = out.decode("utf-8", errors="replace") if isinstance(out, bytes) else out
    expected_err = err.decode("utf-8", errors="replace") if isinstance(err, bytes) else err
    assert rec["stdout_tail"] == expected_out
    assert rec["stderr_tail"] == expected_err


def test_subprocess_runner_keeps_final_capture_and_existing_kill_order(monkeypatch, tmp_path):
    child, fences = FakeChild(), []
    monkeypatch.setattr(X.subprocess, "Popen", lambda *args, **kwargs: child)
    monkeypatch.setattr(X, "_release_spawn_fence", lambda: fences.append("released"))
    with pytest.raises(subprocess.TimeoutExpired) as got:
        X._subprocess_runner(["fixture"], timeout=2, env={}, cwd=tmp_path)
    assert got.value.output == "final progress" and got.value.stderr == "RuntimeError: fixture deadline"
    assert child.calls == [("communicate", 2), ("kill", None), ("communicate", None)]
    assert fences == ["released"]


def test_subprocess_runner_retains_partial_exception_evidence_when_final_capture_is_absent(monkeypatch, tmp_path):
    child = FakeChild(final=(None, None))
    monkeypatch.setattr(X.subprocess, "Popen", lambda *args, **kwargs: child)
    with pytest.raises(subprocess.TimeoutExpired) as got:
        X._subprocess_runner(["fixture"], timeout=2, env={}, cwd=tmp_path)
    assert got.value.output == b"early" and got.value.stderr == b"early error"


def test_heartbeat_deadline_keeps_partial_output_and_existing_beat_kill_order(monkeypatch, tmp_path):
    child, spawned, beats = FakeChild(), [], []
    clock = iter([0.0, 0.0, 2.0])
    monkeypatch.setattr(X.subprocess, "Popen", lambda *args, **kwargs: child)
    monkeypatch.setattr(X.time, "monotonic", lambda: next(clock))
    runner = X.heartbeat_runner(spawned.append, beats.append, heartbeat_s=0.1)
    with pytest.raises(subprocess.TimeoutExpired) as got:
        runner(["fixture"], timeout=1.0, env={}, cwd=tmp_path)
    assert got.value.output == "final progress" and got.value.stderr == "RuntimeError: fixture deadline"
    assert spawned == [42] and beats == [42]
    assert child.calls == [("communicate", 0.1), ("kill", None), ("communicate", None)]


def test_timeout_tail_redacts_before_truncation_and_flows_through_safe_jobs_diagnostics(monkeypatch, tmp_path):
    # A long secret crosses the eventual tail boundary. Redacting after truncation could leak its suffix.
    secret = "fixture" * 250
    err = "Traceback (most recent call last):\nValueError: password=" + secret
    out = "p" * 2000 + " retained progress"

    def runner(*args, **kwargs):
        raise subprocess.TimeoutExpired(["fixture"], 1, output=out, stderr=err)

    rec = spawn(monkeypatch, tmp_path, runner)
    assert rec["stdout_tail"] == out[-X.TAIL_CHARS:] and len(rec["stdout_tail"]) == X.TAIL_CHARS
    assert secret not in rec["stderr_tail"] and "fixturefixture" not in rec["stderr_tail"]
    assert "[REDACTED]" in rec["stderr_tail"] and len(rec["stderr_tail"]) <= X.TAIL_CHARS
    spec = importlib.util.spec_from_file_location("timeout_diagnostic_projection", ROOT / "scripts/lib/job_failure_diagnostics.py")
    helper = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = helper
    spec.loader.exec_module(helper)
    detail = helper.diagnostics_for_run(rec, host_role="n8n_executor")
    assert detail["failure_kind"] == "timeout" and detail["execution"]["exit_code"] is None
    assert detail["traceback"]["available"] is True and detail["exception_type"] == "ValueError"
    assert "fixturefixture" not in str(detail)


def test_missing_timeout_output_stays_explicit_in_jobs_diagnostics(monkeypatch, tmp_path):
    def runner(*args, **kwargs):
        raise subprocess.TimeoutExpired(["fixture"], 1)

    rec = spawn(monkeypatch, tmp_path, runner)
    spec = importlib.util.spec_from_file_location("timeout_missing_projection", ROOT / "scripts/lib/job_failure_diagnostics.py")
    helper = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = helper
    spec.loader.exec_module(helper)
    detail = helper.diagnostics_for_run(rec, host_role="n8n_executor")
    assert rec["stdout_tail"] is None and rec["stderr_tail"] is None
    assert "stderr_not_retained" in detail["gaps"] and "traceback_not_retained" in detail["gaps"]
