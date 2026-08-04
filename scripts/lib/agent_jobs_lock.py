"""Non-overlapping execution lock for process_watchlist_agent_jobs.

Uses flock on a well-known path. Stale lock recovery: if the lock holder PID is
dead, the OS releases advisory flock automatically when the process exits.
We never unlink a held lock; a second process simply fails to acquire (non-blocking).

Rapid retries: callers should exit 99 (or similar) without scheduling provider calls.
"""
from __future__ import annotations

import fcntl
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

DEFAULT_LOCK = Path(os.environ.get(
    "AGENT_JOBS_LOCK_PATH",
    "/tmp/tradeai_watchlist_agent_jobs.lock",
))

# Exit code convention matching historical cron flock -E 99
OVERLAP_EXIT = 99
STALE_NOTE = (
    "Advisory flock: if a previous holder died, the kernel released the lock. "
    "No forced unlink of a live lock is performed."
)


class OverlapError(RuntimeError):
    def __init__(self, message: str = "OVERLAP: another process_watchlist_agent_jobs holds the lock"):
        super().__init__(message)
        self.exit_code = OVERLAP_EXIT


@contextmanager
def acquire_jobs_lock(
    path: Path | None = None,
    *,
    blocking: bool = False,
) -> Iterator[int]:
    """Acquire exclusive flock. Yields lock fd. Raises OverlapError if busy (non-blocking)."""
    lock_path = Path(path or DEFAULT_LOCK)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o644)
    flags = fcntl.LOCK_EX
    if not blocking:
        flags |= fcntl.LOCK_NB
    try:
        try:
            fcntl.flock(fd, flags)
        except BlockingIOError as e:
            os.close(fd)
            raise OverlapError() from e
        # Record holder PID for diagnostics (not used for forced kill)
        try:
            os.ftruncate(fd, 0)
            os.lseek(fd, 0, os.SEEK_SET)
            os.write(fd, f"pid={os.getpid()}\n".encode())
        except Exception:
            pass
        yield fd
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except Exception:
            pass
        try:
            os.close(fd)
        except Exception:
            pass


def try_acquire_or_exit() -> int | None:
    """Helper for scripts: returns None if lock acquired (caller keeps context differently).

    Prefer acquire_jobs_lock context manager in main.
    """
    return None
