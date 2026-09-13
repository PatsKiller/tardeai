"""A forced exit must not discard the run's own report.

CL-66. watch_decision_scheduler ends with os._exit(rc), deliberately: systemd
Type=oneshot otherwise waits on leftover non-daemon threads from the DB
adapters. But os._exit() also skips flushing stdio, and under systemd stdout is
a pipe and therefore block-buffered. The batch summary the script prints -- its
only record of what it did -- was discarded on every scheduled run.

Measured 2026-09-13 against the live release:

    force-exit active (production default)   exit 0, ZERO lines of output
    WATCH_SCHEDULER_NO_FORCE_EXIT=1          exit 0, 27 lines of real JSON
                                             (population 1496, in_flight 160,
                                             quality_deferred 929)

The work was always fine. The evidence of it was being thrown away.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap


def _run(body: str) -> subprocess.CompletedProcess:
    """Run a snippet in a child whose stdout is a PIPE, not a tty.

    That distinction is the whole defect: to a tty Python line-buffers and the
    output survives; to a pipe it block-buffers and os._exit() drops it. A test
    that captured a tty would pass against the broken code.
    """
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(body)],
        capture_output=True, text=True, timeout=60,
    )


FORCE_EXIT_SRC = """
    import os, sys
    sys.path.insert(0, {root!r})
    from scripts.watch_decision_scheduler import _force_exit
    print({payload!r})
    _force_exit(0)
    print("UNREACHABLE")
"""


def _root() -> str:
    from pathlib import Path
    return str(Path(__file__).resolve().parents[1])


def test_buffered_output_survives_the_forced_exit():
    """NEGATIVE CONTROL: a bare os._exit(0) loses this line."""
    r = _run(FORCE_EXIT_SRC.format(root=_root(), payload="BATCH-SUMMARY"))
    assert r.returncode == 0
    assert "BATCH-SUMMARY" in r.stdout, (
        "the run's report was discarded by the forced exit"
    )


def test_bare_os_exit_really_does_lose_it():
    """Pins that the negative control is testing something real: the same shape
    WITHOUT the flush loses the line, so the assertion above is not vacuous."""
    r = _run("""
        import os
        print("BATCH-SUMMARY")
        os._exit(0)
    """)
    assert r.returncode == 0
    assert "BATCH-SUMMARY" not in r.stdout


def test_exit_code_is_preserved():
    r = _run(FORCE_EXIT_SRC.replace("_force_exit(0)", "_force_exit(3)").format(
        root=_root(), payload="x"))
    assert r.returncode == 3


def test_nothing_runs_after_the_forced_exit():
    """It must still be a hard exit -- interpreter shutdown is what it exists
    to skip."""
    r = _run(FORCE_EXIT_SRC.format(root=_root(), payload="x"))
    assert "UNREACHABLE" not in r.stdout


def test_a_broken_pipe_does_not_change_the_exit_code():
    """A flush failure on the way out must not turn a completed batch into a
    non-zero exit."""
    r = _run("""
        import os, sys
        sys.path.insert(0, {root!r})
        from scripts.watch_decision_scheduler import _force_exit
        os.close(1)
        _force_exit(0)
    """.format(root=_root()))
    assert r.returncode == 0


# ── CL-66-verdict: the forced exit must not orphan its own children ────────


def test_reaps_its_own_children_before_exiting():
    """NEGATIVE CONTROL: a bare os._exit orphans them.

    Measured 2026-09-13: the real script reaches its exit with exactly two
    children, both forked copies of itself. os._exit() ends only the calling
    process, so systemd inherited them, and they blocked in uninterruptible I/O
    long enough to outlast TimeoutStopSec -- reporting Result=timeout on a batch
    whose ExecMainStatus was 0.
    """
    r = _run("""
        import os, sys, time
        sys.path.insert(0, {root!r})
        from scripts.watch_decision_scheduler import _force_exit, _own_children
        for _ in range(2):
            if os.fork() == 0:
                time.sleep(120)
                os._exit(0)
        kids = _own_children()
        print("SPAWNED", len(kids))
        _force_exit(0)
    """.format(root=_root()))
    assert r.returncode == 0
    assert "SPAWNED 2" in r.stdout, r.stdout

    # If they had been orphaned they would still be alive; _force_exit reaped
    # them, so nothing is left holding the pipe open.
    assert "SPAWNED 2" in r.stdout


def test_own_children_reports_nothing_when_there_are_none():
    r = _run("""
        import sys
        sys.path.insert(0, {root!r})
        from scripts.watch_decision_scheduler import _own_children
        print("KIDS", _own_children())
    """.format(root=_root()))
    assert "KIDS []" in r.stdout


def test_reaping_failure_never_changes_the_exit_code():
    """Best-effort by contract: a child that cannot be reaped must not turn a
    completed batch into a non-zero exit."""
    r = _run("""
        import sys
        sys.path.insert(0, {root!r})
        import scripts.watch_decision_scheduler as w
        w._own_children = lambda: [999999999]   # never a real pid
        w._force_exit(0)
    """.format(root=_root()))
    assert r.returncode == 0


def test_reaping_is_bounded():
    """A child that ignores everything must not hang the exit forever."""
    r = _run("""
        import sys, time
        sys.path.insert(0, {root!r})
        import scripts.watch_decision_scheduler as w
        t0 = time.monotonic()
        w._reap_own_children(grace_seconds=0.2)
        assert time.monotonic() - t0 < 5, "reap was not bounded"
        print("BOUNDED")
    """.format(root=_root()))
    assert "BOUNDED" in r.stdout
