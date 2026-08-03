"""Atomic JSON publish for Data Broker snapshot files.

Uses a unique temp name (pid + random) so concurrent desk refreshes never race on
the same ``*.json.tmp`` path — that race produced ENOENT on Path.replace and
blanked Re-Entry / Watch desks with a hard error.
"""
from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from typing import Any


def atomic_write_json(path: Path, payload: Any, *, indent: int = 2) -> None:
    """Write payload to path via tmp + os.replace. Creates parent dirs. Raises on I/O error."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    try:
        tmp.write_text(json.dumps(payload, indent=indent, default=str), encoding="utf-8")
        os.replace(tmp, path)
    finally:
        try:
            if tmp.exists():
                tmp.unlink(missing_ok=True)  # type: ignore[call-arg]
        except TypeError:
            # py<3.8 style
            try:
                if tmp.exists():
                    tmp.unlink()
            except Exception:
                pass
        except Exception:
            pass


def atomic_write_json_soft(path: Path, payload: Any, *, indent: int = 2) -> bool:
    """Same as atomic_write_json but never raises — returns False on failure."""
    try:
        atomic_write_json(path, payload, indent=indent)
        return True
    except Exception:
        return False
