"""Run one heavy read-only API computation in a child process with a hard deadline.

Why this exists (n8nmat reliability, 2026-10-09)
-------------------------------------------------
:7777 is a threaded ``http.server``. A Python thread cannot be cancelled, so a slow
read handler holds its thread, its memory and (for C-level work) the GIL until it
finishes. ``/api/v2/system/control-plane-surface-authority`` parsed a 150 MB JSONL
twice per call (~800 MB peak) inside the API process; on a server already near its
``MemoryHigh`` that froze every thread, ``/api/health`` stopped answering, and the
cron watchdog SIGKILLed the service (7 kills 10-05 → 10-09).

A child process fixes the three things a thread cannot:

* a deadline that is actually enforced (the child is killed, the caller gets an
  honest ``TIMEOUT`` body instead of a hung socket);
* memory that is returned to the OS when the child exits instead of fragmenting
  the long-lived API heap;
* process-global side effects (``os.environ`` pinning in whole_site_truth) that
  no longer race other request threads.

Results are cached for a short TTL and computed single-flight per key, so a
dashboard polling the endpoint does not fork one child per poll.

Read-only contract: the child imports the named module and calls one function
with JSON kwargs. It never receives credentials beyond the parent environment and
writes nothing but its JSON result to stdout.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]

# Env-driven (no hard-coded operating values). The default deadline sits well under
# the watchdog's ~46 s unresponsive window, so a timed-out child is reported long
# before the server could look wedged.
TIMEOUT_ENV = "TRADEAI_API_ISOLATED_TIMEOUT_SEC"
TTL_ENV = "TRADEAI_API_ISOLATED_CACHE_TTL_SEC"
DEFAULT_TIMEOUT_SEC = 25.0
DEFAULT_TTL_SEC = 60.0

_CHILD = r"""
import importlib, json, sys
sys.path[:0] = [sys.argv[1], sys.argv[2]]
mod = importlib.import_module(sys.argv[3])
out = getattr(mod, sys.argv[4])(**json.loads(sys.argv[5]))
sys.stdout.write("\n" + json.dumps(out, default=str))
"""

_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _env_float(name: str, default: float) -> float:
    try:
        value = float(os.environ.get(name, ""))
    except ValueError:
        return default
    return value if value > 0 else default


def timeout_sec() -> float:
    return _env_float(TIMEOUT_ENV, DEFAULT_TIMEOUT_SEC)


def cache_ttl_sec() -> float:
    return _env_float(TTL_ENV, DEFAULT_TTL_SEC)


def _lock_for(key: str) -> threading.Lock:
    with _locks_guard:
        lock = _locks.get(key)
        if lock is None:
            lock = _locks[key] = threading.Lock()
        return lock


def _failure(module: str, fn: str, status: str, reason: str, elapsed: float) -> dict[str, Any]:
    return {
        "contract": fn,
        "module": module,
        "status": status,
        "reason": reason,
        "elapsed_sec": round(elapsed, 2),
        "authority": "READ_ONLY_ADVISORY",
        "isolation": "subprocess",
        "isolation_failure": True,
    }


def _run_child(module: str, fn: str, kwargs: dict[str, Any], deadline: float) -> dict[str, Any]:
    started = time.monotonic()
    argv = [
        sys.executable,
        "-c",
        _CHILD,
        str(ROOT / "scripts"),
        str(ROOT),
        module,
        fn,
        json.dumps(kwargs, default=str),
    ]
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=deadline,
            cwd=str(ROOT),
            env=dict(os.environ),
        )
    except subprocess.TimeoutExpired:
        return _failure(
            module,
            fn,
            "TIMEOUT",
            f"computation exceeded {deadline:g}s and was killed; the API stayed up",
            time.monotonic() - started,
        )
    except OSError as exc:
        return _failure(module, fn, "UNAVAILABLE", f"{type(exc).__name__}: {exc}", time.monotonic() - started)
    elapsed = time.monotonic() - started
    if proc.returncode != 0:
        tail = (proc.stderr or "").strip().splitlines()[-1:] or [f"exit {proc.returncode}"]
        return _failure(module, fn, "UNAVAILABLE", tail[0][:300], elapsed)
    lines = (proc.stdout or "").strip().splitlines()
    try:
        body = json.loads(lines[-1]) if lines else None
    except ValueError:
        body = None
    if not isinstance(body, dict):
        return _failure(module, fn, "UNAVAILABLE", "child returned no JSON object", elapsed)
    body.setdefault("isolation", "subprocess")
    return body


def run_isolated(
    module: str,
    fn: str,
    kwargs: dict[str, Any] | None = None,
    *,
    timeout: float | None = None,
    ttl: float | None = None,
) -> dict[str, Any]:
    """Return ``module.fn(**kwargs)`` computed in a child process under a deadline.

    Never raises for a slow, failing or crashing computation: those come back as a
    dict with ``status`` ``TIMEOUT`` or ``UNAVAILABLE`` and the reason. Successful
    results are cached for ``ttl`` seconds; concurrent callers for the same key
    wait for the one in-flight child (bounded by the same deadline) instead of
    starting their own.
    """
    kwargs = dict(kwargs or {})
    deadline = timeout_sec() if timeout is None else timeout
    keep_for = cache_ttl_sec() if ttl is None else ttl
    key = f"{module}:{fn}:{json.dumps(kwargs, sort_keys=True, default=str)}"

    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < keep_for:
        return hit[1]

    lock = _lock_for(key)
    if not lock.acquire(timeout=deadline):
        return _failure(module, fn, "BUSY", "an identical computation is still running", deadline)
    try:
        hit = _cache.get(key)
        if hit and time.monotonic() - hit[0] < keep_for:
            return hit[1]
        body = _run_child(module, fn, kwargs, deadline)
        # Isolation failures (timeout, crash) are retried on the next call; a
        # verdict the contract itself returned (even UNAVAILABLE) is a result.
        if not body.get("isolation_failure"):
            _cache[key] = (time.monotonic(), body)
        return body
    finally:
        lock.release()


def clear_cache() -> None:
    """Test hook."""
    _cache.clear()
