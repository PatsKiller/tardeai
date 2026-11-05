"""Return freed heap to the OS when the portfolio-server goes idle (portfolio-server memory, 2026-10-25).

The server's requests allocate large transient buffers (multi-MB file reads, json.dumps + gzip of MB-scale
payloads, DB result sets). glibc keeps freed chunks inside the heap/arenas, so RSS ratchets to the
high-water mark of the busiest concurrent burst and stays there. In the 2026-10-25 diagnosis the live
process held 477 MB in glibc heap+arenas against 52 MB on an otherwise identical sequential replay, and
``malloc_trim(0)`` released 78-106 MB on the replay instance after a burst.

``note_request_start()`` / ``note_request_end()`` bracket every request. When the in-flight count returns
to zero and at least ``PORTFOLIO_SERVER_MALLOC_TRIM_MIN_INTERVAL_SEC`` (default 15 s) has passed since the
last trim, the finishing thread calls ``malloc_trim(0)``. Disabled with ``PORTFOLIO_SERVER_MALLOC_TRIM=0``
or on a libc without ``malloc_trim``. Never raises.
"""

from __future__ import annotations

import ctypes
import os
import threading
import time

_LOCK = threading.Lock()
_STATE = {"inflight": 0, "last_trim": 0.0, "trims": 0, "fn": None, "resolved": False}


def _enabled() -> bool:
    return str(os.environ.get("PORTFOLIO_SERVER_MALLOC_TRIM", "1")).strip().lower() not in ("0", "false", "no", "off")


def _min_interval() -> float:
    try:
        return max(0.0, float(os.environ.get("PORTFOLIO_SERVER_MALLOC_TRIM_MIN_INTERVAL_SEC", "15")))
    except ValueError:
        return 15.0


def _trim_fn():
    if not _STATE["resolved"]:
        _STATE["resolved"] = True
        try:
            # "libc.so.6" first: ctypes.util.find_library spawns ldconfig/gcc, never do that per server.
            libc = ctypes.CDLL("libc.so.6")
            fn = libc.malloc_trim
            fn.argtypes = [ctypes.c_size_t]
            fn.restype = ctypes.c_int
            _STATE["fn"] = fn
        except (OSError, AttributeError):
            _STATE["fn"] = None
    return _STATE["fn"]


def trim_now() -> bool:
    """Call malloc_trim(0) unconditionally (when available). True when it ran."""
    fn = _trim_fn()
    if fn is None:
        return False
    try:
        fn(0)
    except Exception:
        return False
    _STATE["trims"] += 1
    return True


def note_request_start() -> None:
    with _LOCK:
        _STATE["inflight"] += 1


def note_request_end(now: float | None = None) -> bool:
    """Decrement the in-flight count; trim when the server just went idle. True when a trim ran."""
    now = time.monotonic() if now is None else now
    with _LOCK:
        _STATE["inflight"] = max(0, _STATE["inflight"] - 1)
        due = (
            _STATE["inflight"] == 0
            and _enabled()
            and (now - _STATE["last_trim"]) >= _min_interval()
        )
        if due:
            _STATE["last_trim"] = now
    if not due:
        return False
    return trim_now()


def stats() -> dict:
    with _LOCK:
        return {"inflight": _STATE["inflight"], "trims": _STATE["trims"], "last_trim": _STATE["last_trim"],
                "available": _trim_fn() is not None, "enabled": _enabled()}
