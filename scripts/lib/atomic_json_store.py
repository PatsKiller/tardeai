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


def append_jsonl(path: Path | str, rec: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(rec, sort_keys=True, default=str) + "\n"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line)
        fh.flush()
        os.fsync(fh.fileno())
