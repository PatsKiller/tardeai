"""Admission precedes telemetry; runner signals only mocked owned processes.

No real pipeline, provider, DB, credential, process or signal is used. Kernel
flock checks operate only on temporary fixture files.
"""

from __future__ import annotations

import ast
from contextlib import ExitStack
import errno
import os
from pathlib import Path
import signal
import subprocess
import sys
import types

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.lib import orchestrator_admission as admission  # noqa: E402

# Functional lifecycle coverage only: alarm send sites are mocked, not fired.
FUNCTIONAL_TARGETS = ["scripts/lib/orchestrator_admission.py", "scripts/trade_ai_orchestrator.py", "scripts/continuous_runner.py"]


def test_one_writer_and_next_owner_use_the_same_inode(tmp_path):
    lock = tmp_path / "admission.lock"
    with admission.orchestrator_admission(lock) as first:
        assert first is True
        inode = lock.stat().st_ino
        with admission.orchestrator_admission(lock) as contender:
            assert contender is False
    with admission.orchestrator_admission(lock) as next_owner:
        assert next_owner is True
        assert lock.stat().st_ino == inode


def test_outer_screener_lock_does_not_deadlock_internal_admission(tmp_path):
    assert admission.ADMISSION_LOCK.name != "screener_pm.lock"
    with admission.orchestrator_admission(tmp_path / "screener_pm.lock") as outer:
        assert outer is True
        with admission.orchestrator_admission(tmp_path / admission.ADMISSION_LOCK.name) as inner:
            assert inner is True


def test_lock_errors_fail_closed_and_symlinks_are_not_followed(tmp_path):
    target = tmp_path / "unchanged"
    target.write_text("fixture")
    link = tmp_path / "admission.lock"
    link.symlink_to(target)
    with pytest.raises(OSError) as exc:
        with admission.orchestrator_admission(link):
            pytest.fail("unsafe lock admitted a writer")
    assert exc.value.errno == errno.ELOOP
    assert target.read_text() == "fixture"


def test_lock_fd_cannot_be_inherited_by_pipeline_children(tmp_path, monkeypatch):
    original_open = os.open
    opened = []

    def capture_open(*args, **kwargs):
        fd = original_open(*args, **kwargs)
        opened.append(fd)
        return fd

    monkeypatch.setattr(admission.os, "open", capture_open)
    with admission.orchestrator_admission(tmp_path / "admission.lock") as admitted:
        assert admitted is True
        assert os.get_inheritable(opened[-1]) is False


def _entrypoint(tmp_path, main):
    events = []
    exit_callbacks = []

    class Run:
        def __init__(self, key):
            events.append(("registered", key))

        def __enter__(self):
            return self

        def __exit__(self, *args):
            events.append(("closed",))

    tree = ast.parse((ROOT / "scripts/trade_ai_orchestrator.py").read_text())
    block = next(
        n
        for n in tree.body
        if isinstance(n, ast.If) and isinstance(n.test, ast.Compare) and getattr(n.test.left, "id", "") == "__name__"
    )
    namespace = {
        "orchestrator_admission": lambda: admission.orchestrator_admission(tmp_path / "admission.lock"),
        "CONTENTION_EXIT": admission.CONTENTION_EXIT,
        "ExitStack": ExitStack,
        "atexit": types.SimpleNamespace(register=exit_callbacks.append),
        "PipelineRun": Run,
        "Path": Path,
        "sys": sys,
        "main": lambda: main(events),
        "report_rows_produced": lambda run: events.append(("rows",)),
        "_enrich_opaque_exit": lambda code, root: code,
    }
    with pytest.raises(SystemExit) as exc:
        exec(compile(ast.Module(body=block.body, type_ignores=[]), "orchestrator.entrypoint", "exec"), namespace)
    assert len(exit_callbacks) == 1
    # PipelineRun has unwound, but process-lifetime admission stays held until
    # the interpreter invokes its registered cleanup callback.
    with admission.orchestrator_admission(tmp_path / "admission.lock") as contender:
        assert contender is False
    for cleanup in reversed(exit_callbacks):
        cleanup()
    return exc.value.code, events


def test_contention_skips_before_registering_or_running_pipeline(tmp_path, capsys):
    with admission.orchestrator_admission(tmp_path / "admission.lock"):
        rc, events = _entrypoint(tmp_path, lambda events: pytest.fail("contender ran pipeline"))
    assert rc == 75 and events == []
    assert "already running" in capsys.readouterr().err


@pytest.mark.parametrize("result", [0, 2])
def test_admitted_entrypoint_preserves_result_and_releases_on_exit(tmp_path, result):
    def main(events):
        events.append(("pipeline",))
        return result

    rc, events = _entrypoint(tmp_path, main)
    assert rc == result
    assert events[0] == ("registered", "trade_ai_orchestrator")
    assert events[1] == ("pipeline",)
    assert (("rows",) in events) is (result == 0)
    assert events[-1] == ("closed",)
    with admission.orchestrator_admission(tmp_path / "admission.lock") as admitted:
        assert admitted is True


class Child:
    pid = 424242

    def __init__(self, results):
        self.results = list(results)
        self.waits = []

    def wait(self, timeout):
        self.waits.append(timeout)
        result = self.results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


def _runner(child=None, *, spawn_error=None, kill_error=None, handlers=None):
    spawned, killed = [], []
    handlers = {signal.SIGTERM: signal.SIG_DFL, signal.SIGHUP: signal.SIG_DFL} if handlers is None else handlers

    def set_handler(signum, handler):
        previous = handlers[signum]
        handlers[signum] = handler
        return previous

    def popen(cmd, **kwargs):
        spawned.append((cmd, kwargs))
        if spawn_error:
            raise spawn_error
        return child

    def killpg(pid, sig):
        killed.append((pid, sig))
        if kill_error:
            raise kill_error

    tree = ast.parse((ROOT / "scripts/continuous_runner.py").read_text())
    functions = [
        n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in ("_stop_full_pipeline", "run_full_cycle")
    ]
    namespace = {
        "Path": Path,
        "sys": types.SimpleNamespace(executable="/fixture/python"),
        "os": types.SimpleNamespace(environ={"FIXTURE": "yes"}, killpg=killpg),
        "subprocess": types.SimpleNamespace(Popen=popen, TimeoutExpired=subprocess.TimeoutExpired),
        "signal": types.SimpleNamespace(
            SIGTERM=signal.SIGTERM,
            SIGHUP=signal.SIGHUP,
            SIGKILL=signal.SIGKILL,
            getsignal=lambda signum: handlers[signum],
            signal=set_handler,
        ),
    }
    exec(compile(ast.Module(body=functions, type_ignores=[]), "runner.full_cycle", "exec"), namespace)
    return namespace["run_full_cycle"], spawned, killed


@pytest.mark.parametrize("rc,phrase", [(0, "completed"), (75, "admission skipped"), (2, "failed"), (-15, "failed")])
def test_runner_distinguishes_skip_success_and_failure(rc, phrase, capsys):
    child = Child([rc])
    run, spawned, killed = _runner(child)
    assert run(Path("/fixture"), "0900", "2026-10-29") == rc
    assert phrase in capsys.readouterr().out
    assert child.waits == [2700]
    assert spawned[0][1] == {"env": {"FIXTURE": "yes"}, "start_new_session": True}
    assert killed == []


@pytest.mark.parametrize("leader_exits_on_term", [True, False])
def test_runner_timeout_reaps_owned_group_even_when_leader_exits_first(leader_exits_on_term, capsys):
    expired = subprocess.TimeoutExpired("fixture", 2700)
    grace_result = -15 if leader_exits_on_term else subprocess.TimeoutExpired("fixture", 5)
    child = Child([expired, grace_result, -9])
    run, _, killed = _runner(child)
    assert run(Path("/fixture"), "0900", "2026-10-29") == 124
    assert child.waits == [2700, 5, 5]
    assert killed == [(child.pid, signal.SIGTERM), (child.pid, signal.SIGKILL)]
    assert "timed out" in capsys.readouterr().out


def test_runner_spawn_failure_is_failure_not_success(capsys):
    run, _, killed = _runner(spawn_error=OSError("synthetic spawn failure"))
    assert run(Path("/fixture"), "0900", "2026-10-29") == 1
    assert "synthetic spawn failure" in capsys.readouterr().out
    assert killed == []


def test_failed_timeout_cleanup_does_not_claim_group_stopped(capsys):
    child = Child([subprocess.TimeoutExpired("fixture", 2700)])
    run, _, _ = _runner(child, kill_error=PermissionError("synthetic signal refusal"))
    assert run(Path("/fixture"), "0900", "2026-10-29") == 124
    output = capsys.readouterr().out
    assert "cleanup failed" in output and "process group stopped" not in output


@pytest.mark.parametrize("signum", [signal.SIGTERM, signal.SIGHUP])
def test_parent_termination_cleans_owned_children_and_restores_handlers(signum):
    handlers = {signal.SIGTERM: signal.SIG_DFL, signal.SIGHUP: signal.SIG_DFL}
    originals = dict(handlers)

    class SignalledChild(Child):
        def wait(self, timeout):
            if timeout == 2700:
                handlers[signum](signum, None)
            return super().wait(timeout)

    child = SignalledChild([-15, -9])
    run, _, killed = _runner(child, handlers=handlers)
    with pytest.raises(SystemExit) as exc:
        run(Path("/fixture"), "0900", "2026-10-29")
    assert exc.value.code == 128 + signum
    assert killed == [(child.pid, signal.SIGTERM), (child.pid, signal.SIGKILL)]
    assert handlers == originals


def test_existing_pipeline_signal_handler_keeps_its_exception():
    class PipelineSignal(SystemExit):
        pass

    def prior(signum, frame):
        raise PipelineSignal(128 + signum)

    handlers = {signal.SIGTERM: prior, signal.SIGHUP: signal.SIG_DFL}

    class SignalledChild(Child):
        def wait(self, timeout):
            if timeout == 2700:
                handlers[signal.SIGTERM](signal.SIGTERM, None)
            return super().wait(timeout)

    child = SignalledChild([-15, -9])
    run, _, killed = _runner(child, handlers=handlers)
    with pytest.raises(PipelineSignal):
        run(Path("/fixture"), "0900", "2026-10-29")
    assert len(killed) == 2 and handlers[signal.SIGTERM] is prior


@pytest.mark.parametrize("rc,message", [(0, "[STARTUP] Complete"), (75, "[STARTUP] Skipped"), (2, "[STARTUP] Failed")])
def test_startup_completion_message_matches_actual_result(rc, message, capsys):
    tree = ast.parse((ROOT / "scripts/continuous_runner.py").read_text())
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
    block = next(
        n
        for n in ast.walk(main)
        if isinstance(n, ast.Try)
        and any(isinstance(x, ast.Call) and getattr(x.func, "id", "") == "run_full_cycle" for x in ast.walk(n))
    )
    namespace = {
        "root": Path("/fixture"),
        "_startup_label": "0900",
        "_startup_date": "2026-10-29",
        "run_full_cycle": lambda *args: rc,
    }
    exec(compile(ast.Module(body=[block], type_ignores=[]), "runner.startup", "exec"), namespace)
    output = capsys.readouterr().out
    assert message in output
    assert ("[STARTUP] Complete" in output) is (rc == 0)
