"""One orchestrator writer across cron, recovery and continuous-runner callers.

This lock is deliberately separate from the outer screener_pm.lock used by
some launchers. Contention is a skip before pipeline telemetry is opened.
"""

from __future__ import annotations

from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
from typing import Iterator

ADMISSION_LOCK = Path("/tmp/tradeai_orchestrator_admission.lock")
CONTENTION_EXIT = 75


@contextmanager
def orchestrator_admission(lock_path: Path = ADMISSION_LOCK) -> Iterator[bool]:
    """Yield admission immediately; closing the non-inherited fd releases it.

    Lock-file errors fail closed rather than starting an unprotected writer.
    The file is never truncated or unlinked, so contenders keep one inode.
    """
    fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        yield True
    finally:
        os.close(fd)
