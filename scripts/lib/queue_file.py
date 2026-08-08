#!/usr/bin/env python3
"""queue_file.py — flock-guarded atomic read/write for shared JSON queue files.

Four scripts read-modify-write ``logs/claude_escalation_queue.json`` concurrently
(health_agent, system_health_agent, claude_escalation_handler, coder_dispatch,
agent_watchdog).  Without locking, concurrent writers can lose updates — the classic
read-modify-write race.

This module provides two functions:

    items = read_items(path)        # flock SHARED, returns list (or [] if missing)
    write_items(path, items)        # flock EXCLUSIVE, atomic write (temp + os.replace)

A ``<path>.lock`` sidecar file is used for locking; only the data file's directory is
touched.  Callers that hold the read result and later write must re-read under the
exclusive lock to merge changes they didn't see — see ``atomic_update()``.
"""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from pathlib import Path


def _lock_fd(fd, exclusive: bool = False) -> None:
    """Acquire an advisory flock on *fd* (blocking)."""
    op = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
    fcntl.flock(fd, op)


def _unlock_fd(fd) -> None:
    """Release the advisory flock on *fd*."""
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    except Exception:
        pass


def read_items(path: Path | str) -> list:
    """Return the JSON array stored at *path*, or [] if the file is missing/invalid.

    Acquires a SHARED flock — multiple readers can proceed concurrently.
    """
    path = Path(path)
    if not path.exists():
        return []
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    # Create lock file if it doesn't exist (flock needs an open fd)
    if not lock_path.exists():
        lock_path.touch()
    with open(lock_path, "r+") as lf:
        _lock_fd(lf, exclusive=False)
        try:
            with open(path, "r") as df:
                data = json.load(df)
        except (FileNotFoundError, json.JSONDecodeError):
            return []
        finally:
            _unlock_fd(lf)
    if isinstance(data, list):
        return data
    return []


def write_items(path: Path | str, items: list) -> None:
    """Atomically write *items* as a JSON array to *path*.

    Acquires an EXCLUSIVE flock — no other reader or writer can proceed while the
    write is in flight.  The data is first written to a temp file in the same
    directory, then ``os.replace`` makes the write atomic (observers see either the
    complete old file or the complete new file).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    if not lock_path.exists():
        lock_path.touch()
    payload = json.dumps(items, indent=2, ensure_ascii=False)
    with open(lock_path, "r+") as lf:
        _lock_fd(lf, exclusive=True)
        try:
            # Write to temp file in the same directory so os.replace is atomic
            fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp_" + path.name)
            try:
                os.write(fd, payload.encode("utf-8"))
                os.fsync(fd)
            finally:
                os.close(fd)
            os.chmod(tmp, 0o600)
            os.replace(tmp, str(path))  # atomic on same filesystem
        finally:
            _unlock_fd(lf)


def atomic_update(path: Path | str, update_fn) -> list:
    """Read *path*, call ``update_fn(items)`` → new_items, write atomically.

    The *update_fn* is called UNDER THE EXCLUSIVE LOCK, so it sees the freshest
    state.  This is the safe one-shot pattern for read-modify-write cycles.

    Returns the list written.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    if not lock_path.exists():
        lock_path.touch()
    with open(lock_path, "r+") as lf:
        _lock_fd(lf, exclusive=True)
        try:
            if path.exists():
                with open(path, "r") as df:
                    try:
                        items = json.load(df)
                    except json.JSONDecodeError:
                        items = []
                if not isinstance(items, list):
                    items = []
            else:
                items = []
            new_items = update_fn(items)
            payload = json.dumps(new_items, indent=2, ensure_ascii=False)
            fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp_" + path.name)
            try:
                os.write(fd, payload.encode("utf-8"))
                os.fsync(fd)
            finally:
                os.close(fd)
            os.chmod(tmp, 0o600)
            os.replace(tmp, str(path))
            return new_items
        finally:
            _unlock_fd(lf)
