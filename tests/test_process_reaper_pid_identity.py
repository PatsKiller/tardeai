import importlib.util
import subprocess
import signal
import sys
import threading
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("process_reaper_under_test", ROOT / "scripts" / "process_reaper.py")
reaper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(reaper)


PID = 81234
IDENTITY = (123456, b"python\0scripts/trade_ai_orchestrator.py\0")
TARGET = {"pid": PID, "identity": IDENTITY}


def _without_pidfd(monkeypatch):
    monkeypatch.setattr(reaper.os, "pidfd_open", None, raising=False)
    monkeypatch.setattr(reaper.signal, "pidfd_send_signal", None, raising=False)


def test_identity_change_before_term_never_signals(monkeypatch):
    _without_pidfd(monkeypatch)
    calls = []
    monkeypatch.setattr(reaper, "_proc_identity", lambda _pid: (123457, b"python\0other.py\0"))
    monkeypatch.setattr(reaper.os, "kill", lambda *args: calls.append(args))

    assert reaper._kill(TARGET, True) == "identity_changed"
    assert calls == []


def test_identity_change_during_grace_never_escalates(monkeypatch):
    _without_pidfd(monkeypatch)
    observations = iter([IDENTITY, IDENTITY, (123457, b"python\0other.py\0")])
    monkeypatch.setattr(reaper, "_proc_identity", lambda _pid: next(observations))
    calls = []
    monkeypatch.setattr(reaper.os, "kill", lambda _pid, sig: calls.append(sig))
    monkeypatch.setattr(reaper.time, "sleep", lambda _seconds: None)

    assert reaper._kill(TARGET, True) == "identity_changed_after_sigterm"
    assert calls == [signal.SIGTERM]


def test_same_target_is_escalated_after_graceful_timeout(monkeypatch):
    _without_pidfd(monkeypatch)
    monkeypatch.setattr(reaper, "_proc_identity", lambda _pid: IDENTITY)
    calls = []
    monkeypatch.setattr(reaper.os, "kill", lambda _pid, sig: calls.append(sig))
    monkeypatch.setattr(reaper.time, "sleep", lambda seconds: calls.append(("sleep", seconds)))

    assert reaper._kill(TARGET, True) == "killed_sigkill"
    assert calls == [signal.SIGTERM, ("sleep", 3), signal.SIGKILL]


def test_target_gone_during_grace_is_not_escalated(monkeypatch):
    _without_pidfd(monkeypatch)
    observations = iter([IDENTITY, IDENTITY])

    def current(_pid):
        try:
            return next(observations)
        except StopIteration:
            raise ProcessLookupError

    monkeypatch.setattr(reaper, "_proc_identity", current)
    calls = []
    monkeypatch.setattr(reaper.os, "kill", lambda _pid, sig: calls.append(sig))
    monkeypatch.setattr(reaper.time, "sleep", lambda _seconds: None)

    assert reaper._kill(TARGET, True) == "terminated"
    assert calls == [signal.SIGTERM]


def test_pidfd_is_used_and_always_closed(monkeypatch):
    sent, closed = [], []
    monkeypatch.setattr(reaper.os, "pidfd_open", lambda _pid, _flags: 99, raising=False)
    monkeypatch.setattr(
        reaper.signal, "pidfd_send_signal", lambda fd, sig, _info, _flags: sent.append((fd, sig)), raising=False
    )
    monkeypatch.setattr(reaper, "_proc_identity", lambda _pid: IDENTITY)
    monkeypatch.setattr(reaper.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(reaper.os, "close", lambda fd: closed.append(fd))

    assert reaper._kill(TARGET, True) == "killed_sigkill"
    assert sent == [(99, signal.SIGTERM), (99, signal.SIGKILL)]
    assert closed == [99]


def test_pidfd_is_closed_when_identity_changed_before_term(monkeypatch):
    closed = []
    monkeypatch.setattr(reaper.os, "pidfd_open", lambda _pid, _flags: 98, raising=False)
    monkeypatch.setattr(
        reaper.signal, "pidfd_send_signal", lambda *_args: pytest.fail("must not signal"), raising=False
    )
    monkeypatch.setattr(reaper, "_proc_identity", lambda _pid: (999, b"other"))
    monkeypatch.setattr(reaper.os, "close", lambda fd: closed.append(fd))

    assert reaper._kill(TARGET, True) == "identity_changed"
    assert closed == [98]


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="requires Linux /proc process identity")
def test_live_owned_child_uses_identity_checked_fallback(monkeypatch):
    """Exercise real /proc identity and numeric-PID TERM/KILL on a test-owned child."""
    _without_pidfd(monkeypatch)
    child = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); print('ready', flush=True); time.sleep(60)",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    waiter = None
    try:
        assert child.stdout is not None
        assert child.stdout.readline().strip() == "ready"
        target = {"pid": child.pid, "identity": reaper._proc_identity(child.pid)}
        waiter = threading.Thread(target=child.wait, daemon=True)
        waiter.start()

        assert reaper._kill(target, True) == "killed_sigkill"
        waiter.join(timeout=5)
        assert not waiter.is_alive()
        assert child.poll() is not None
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)
        if child.stdout is not None:
            child.stdout.close()
        if waiter is not None:
            waiter.join(timeout=5)
