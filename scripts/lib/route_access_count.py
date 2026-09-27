"""Fail-soft counts of HTTP paths. No query string, no body, no deletion.

WS-8 starts here: a route is not removed until this file has shown it unused.
The counter never raises into the request.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

_LOCK = threading.Lock()
_COUNTS: dict[str, int] = {}
_SINCE_FLUSH = 0
_FLUSH_EVERY = 50
_MAX_KEYS = 2000

def _default_path() -> Path:
    env = (os.environ.get("TRADEAI_ROUTE_COUNT_PATH") or "").strip()
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2] / "data" / "runtime" / "route_access_counts.json"


def note(method: str, raw_path: str, *, store: dict[str, int] | None = None, flush_path: Path | None = None) -> None:
    path = (raw_path or "").split("?", 1)[0].split("#", 1)[0][:180] or "/"
    key = f"{(method or 'GET').upper()} {path}"
    target = _COUNTS if store is None else store
    should = False
    snapshot: dict[str, int] = {}
    with _LOCK:
        if key not in target and len(target) >= _MAX_KEYS:
            return
        target[key] = int(target.get(key) or 0) + 1
        global _SINCE_FLUSH
        _SINCE_FLUSH += 1
        if store is None and _SINCE_FLUSH >= _FLUSH_EVERY:
            _SINCE_FLUSH = 0
            snapshot = dict(target)
            should = True
    if should:
        _write(snapshot, flush_path or _default_path())


def flush(store: dict[str, int] | None = None, flush_path: Path | None = None) -> None:
    with _LOCK:
        snapshot = dict(_COUNTS if store is None else store)
    _write(snapshot, flush_path or _default_path())


def _write(snapshot: dict[str, int], path: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps({"schema": "RouteAccessCounts@v1", "counts": snapshot}, sort_keys=True), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        return
