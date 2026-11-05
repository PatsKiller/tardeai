"""HOLDINGS_LOCK_REENTRANT_20261103 — the shared write lock composes on one thread.

flock is per open file description, so a second fd in the same process blocks against a lock the
process already holds. Before this change, a writer holding `holdings_write_lock()` that called
another lock-taking helper deadlocked the process against itself. Row 32a makes the lock re-entrant
per thread; the kernel lock is still taken exactly once, at the outermost block.

What must NOT change: writers in other processes are still excluded for the whole read-modify-write
window. That is the property the lock exists for, and it is tested against a real child process.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "scripts", ROOT / "scripts" / "lib"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import lib.holdings_write_lock as hwl  # noqa: E402


@pytest.fixture
def lock_path(tmp_path, monkeypatch):
    p = tmp_path / "holdings_write.lock"
    monkeypatch.setattr(hwl, "LOCK_PATH", p)
    return p


def test_nested_acquisition_on_one_thread_does_not_deadlock(lock_path):
    """The row-32a case: a guard taking the lock a writer already holds must re-enter, not hang."""
    with hwl.holdings_write_lock():
        with hwl.holdings_write_lock():  # would block forever on a second fd
            with hwl.holdings_write_lock():
                assert hwl._depth() == 3
            assert hwl._depth() == 2
        assert hwl._depth() == 1
    assert hwl._depth() == 0


def test_the_outermost_block_still_releases_the_kernel_lock(lock_path):
    with hwl.holdings_write_lock():
        with hwl.holdings_write_lock():
            pass
    # A real child process can take it immediately after the outer block exits.
    assert _child_can_lock(lock_path) is True


def test_another_process_is_excluded_while_the_outermost_block_holds(lock_path):
    with hwl.holdings_write_lock():
        with hwl.holdings_write_lock():
            assert _child_can_lock(lock_path) is False, "a child must not acquire the held lock"
    assert _child_can_lock(lock_path) is True


def test_an_exception_in_a_nested_block_still_unwinds(lock_path):
    with pytest.raises(RuntimeError):
        with hwl.holdings_write_lock():
            with hwl.holdings_write_lock():
                raise RuntimeError("inner")
    assert hwl._depth() == 0
    assert _child_can_lock(lock_path) is True


def test_an_exception_in_the_outermost_block_still_releases(lock_path):
    with pytest.raises(RuntimeError):
        with hwl.holdings_write_lock():
            raise RuntimeError("outer")
    assert hwl._depth() == 0
    assert _child_can_lock(lock_path) is True


def test_another_thread_still_waits_documented_limit(lock_path):
    """The counter is per THREAD: the kernel lock stays process-wide, exactly as before."""
    acquired = threading.Event()

    def other():
        with hwl.holdings_write_lock():
            acquired.set()

    with hwl.holdings_write_lock():
        t = threading.Thread(target=other, daemon=True)
        t.start()
        assert not acquired.wait(0.3), "another thread must wait while this thread holds the lock"
    assert acquired.wait(5), "the waiting thread must proceed once the lock is released"
    t.join(5)


def _child_can_lock(path: Path) -> bool:
    """True when a SEPARATE process can take the kernel lock non-blockingly right now."""
    code = textwrap.dedent(
        """
        import fcntl, os, sys
        fd = os.open(sys.argv[1], os.O_CREAT | os.O_RDWR, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise SystemExit(1)
        finally:
            os.close(fd)
        raise SystemExit(0)
        """
    )
    r = subprocess.run([sys.executable, "-c", code, str(path)], capture_output=True, timeout=30)
    return r.returncode == 0
