"""Atomic current-document writer: unique temp + fsync + os.replace.

Never leave a partial JSON current file. History appends are a separate path.
"""
from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from typing import Any


#: Permissions a NEW document gets. A store file must not become readable by every user on the host just because
#: the writing process ran with the cron/systemd default umask (022 leaves a fresh file 0644).
NEW_FILE_MODE = 0o600


def _target_mode(path: Path) -> int:
    """The mode the written file must keep: the existing target's own, or 0600 for a new document.

    cc-deepseek-8's BLOCK on #2299 (F1): the temp file was created with the caller's umask, and ``os.replace`` gives
    the temp's mode to the target — so a correctly 0600 holdings file came back 0644 after one write from a 022
    process (cron, systemd), while the same code looked safe from a developer's 077 shell. Reading the target's mode
    first keeps whatever the caller chose; a document that does not exist yet is private by default.
    """
    try:
        return path.stat().st_mode & 0o777
    except FileNotFoundError:
        return NEW_FILE_MODE


def atomic_write_json(path: Path | str, payload: Any, *, indent: int = 2) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    text = json.dumps(payload, indent=indent, default=str) + "\n"
    mode = _target_mode(path)
    try:
        with tmp.open("w", encoding="utf-8") as fh:
            os.fchmod(fh.fileno(), mode)
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
    return path


def atomic_write_bytes(path: Path | str, data: bytes) -> Path:
    """Atomically write exact raw bytes: unique temp + fsync + os.replace.

    The target is never truncated in place — the bytes are written to a temp
    file in the same directory, fsynced, then atomically renamed over the
    target. A failure (e.g. ENOSPC) leaves the prior target byte-for-byte
    intact. Contrast with ``Path.write_bytes``, which opens the target in
    "wb" (truncate) mode first and can leave a 0-byte file on failure.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    mode = _target_mode(path)
    try:
        with tmp.open("wb") as fh:
            os.fchmod(fh.fileno(), mode)
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        try:  # nosemgrep: tq-py-except-pass -- best-effort temp cleanup in finally; the write error (if any) still propagates
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
    return path


def append_jsonl(path: Path | str, rec: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(rec, sort_keys=True, default=str) + "\n"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line)
        fh.flush()
        os.fsync(fh.fileno())
