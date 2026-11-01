"""Atomic current-document writer: unique temp + fsync + os.replace.

Never leave a partial JSON current file. History appends are a separate path.
"""
from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from typing import Any


def atomic_write_json(path: Path | str, payload: Any, *, indent: int = 2) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    text = json.dumps(payload, indent=indent, default=str) + "\n"
    try:
        with tmp.open("w", encoding="utf-8") as fh:
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
    try:
        with tmp.open("wb") as fh:
            fh.write(data)
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


def append_jsonl(path: Path | str, rec: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(rec, sort_keys=True, default=str) + "\n"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line)
        fh.flush()
        os.fsync(fh.fileno())
