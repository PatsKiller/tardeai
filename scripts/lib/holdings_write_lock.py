"""Shared lock for holdings.json read-modify-write serialization.

WHY THIS EXISTS
---------------
Several cron jobs each read-modify-write ``holdings.json`` on overlapping 15-min
schedules, each guarded by a DIFFERENT per-script lock (``portfolio_repricer.lock``,
``alpaca_live_read_sync.lock``, ``schwab_pos_sync.lock``). A slow reader — the
repricer, which spends ~60s fetching quotes between its read and its write — could
therefore read a stale cash row, then write that stale copy back AFTER the Alpaca
sync had already written a fresh one. The Alpaca cash-row ``broker_position_as_of``
kept flipping back to a stale date and drove the whole portfolio block STALE via
``compute_data_as_of`` (oldest contributor).

This is the ONE lock every holdings writer must hold across its full
read -> modify -> write cycle so they serialize instead of racing.

RE-ENTRANCY (2026-11-03, board row 32a)
---------------------------------------
``flock`` is per open file description: a SECOND fd in the same process blocks
against a lock the process already holds. So a writer that holds this lock cannot
call another lock-taking helper — the process deadlocks against itself. Callers
that need to compose (a writer that calls the guarded write path, or a guard that
takes the lock around its own read-modify-write) get a thread-local depth counter:
the outermost ``with`` opens the fd and takes the kernel lock once, and nested
``with`` blocks on the SAME THREAD re-enter without a second fd. The kernel lock is
released only when the outermost block exits.

Documented limit: the counter is per THREAD. The kernel lock is process-wide, so a
different thread of the same process still blocks against it (as it always has) —
this change makes same-thread composition safe; it does not make the lock
multi-tenant within a process.

AUTHORITY
---------
Read-only advisory with respect to financial data. This module only serializes
writers; it performs no calculation and changes no values.
"""

from __future__ import annotations

import fcntl
import os
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

LOCK_PATH = Path("/tmp/holdings_write.lock")

#: Per-thread nesting depth. 0/absent means this thread does not hold the lock.
_STATE = threading.local()


def _depth() -> int:
    return int(getattr(_STATE, "depth", 0) or 0)


@contextmanager
def holdings_write_lock() -> Iterator[None]:
    """Blocking exclusive lock on the shared holdings.json write lock.

    Blocks until acquired (there is no timeout in POSIX flock). Holding the lock
    across a whole read-modify-write cycle is what prevents the lost-update race;
    the ~60s the repricer holds it is a deliberate serialization cost on a 15-min
    cadence, not a bug.

    Re-entrant on the calling thread: the outermost ``with`` takes the kernel lock
    on one fd, nested ``with`` blocks reuse it, and the lock is released when the
    outermost block exits. A different thread still waits, as before.
    """
    if _depth():
        _STATE.depth = _depth() + 1
        try:
            yield
        finally:
            _STATE.depth = _depth() - 1
        return
    fd = os.open(str(LOCK_PATH), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)  # blocks until the lock is free
        _STATE.depth = 1
        try:
            yield
        finally:
            _STATE.depth = 0
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
