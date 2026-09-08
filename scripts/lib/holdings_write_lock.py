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

AUTHORITY
---------
Read-only advisory with respect to financial data. This module only serializes
writers; it performs no calculation and changes no values.
"""
from __future__ import annotations

import fcntl
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

LOCK_PATH = Path("/tmp/holdings_write.lock")


@contextmanager
def holdings_write_lock() -> Iterator[None]:
    """Blocking exclusive lock on the shared holdings.json write lock.

    Blocks until acquired (there is no timeout in POSIX flock). Holding the lock
    across a whole read-modify-write cycle is what prevents the lost-update race;
    the ~60s the repricer holds it is a deliberate serialization cost on a 15-min
    cadence, not a bug.
    """
    fd = os.open(str(LOCK_PATH), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)  # blocks until the lock is free
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
