"""Serve-last-good-with-age, single background build per key (LQ-20261107-2572).

Why: /api/v2/cio/pages builds in 20-30 s, longer than its 60 s TTL and the 30 s request watchdog. With
the plain single-flight lock every poll parked behind the one build (27 threads, 49 reaped polls, zero
completed builds, 2.6 GB, SIGKILL 2026-11-12 17:12 ET). Here a caller NEVER waits on a build:

* fresh entry (< ttl_s)            -> returned as is, stale False
* stored entry older than ttl_s    -> returned at once with as_of / age_s / stale True; one background
                                      build is started if none is in flight
* nothing stored yet               -> UNKNOWN "building" (also starts the one build); never a guess
* the build runs on its own daemon thread, so a watchdog reaping the request does not stop it and its
  result is still stored; a failed build is recorded (last_error) and the last-good stays served
* at most one build thread per key, hence the thread count is bounded by the number of keys

REVIEW-2580 (LQ-2584):
* R1 a failing build is reported, not hidden: with no last-good the body is UNKNOWN reason "build_failed"
  with last_build_error / last_build_error_at; with a last-good it carries last_build_error. After a failure
  no new build starts for max(ttl_s, MIN_BACKOFF_S) so a persistent failure is not a back-to-back burn.
* R2 a running build is visible (build_running_s). Past STUCK_FACTOR x ttl_s it is "build_stuck" (cold:
  reason build_stuck; stale: build_stuck true) and ONE replacement build may start; a replaced build that
  returns later is discarded if it started before the stored result.
* N1 a build that RETURNS an HTTP-error tuple (status >= 400) is a failure, never stored as last-good.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone

MIN_BACKOFF_S = 5.0
STUCK_FACTOR = 5.0

_LOCK = threading.Lock()
_ENTRIES: dict = {}  # key -> {"mono", "wall", "payload", "started"}
_INFLIGHT: dict = {}  # key -> {"thread", "started": mono}
_ERRORS: dict = {}  # key -> {"mono", "wall", "error"}


def _iso(wall: float) -> str:
    return datetime.fromtimestamp(wall, tz=timezone.utc).isoformat(timespec="seconds")


def _default_annotate(payload, meta: dict):
    if isinstance(payload, dict):
        out = dict(payload)
        out.update(meta)
        return out
    return payload


def _unknown_default(key: str, meta: dict) -> dict:
    out = {"status": "UNKNOWN", "reason": meta.get("reason", "building"), "stale": True, "as_of": None, "age_s": None,
           "detail": f"{key}: no last-good payload yet"}
    out.update({k: v for k, v in meta.items() if k != "reason"})
    return out


def _run(key: str, build, started: float) -> None:
    try:
        payload = build()
        if isinstance(payload, tuple) and payload and isinstance(payload[0], int) and payload[0] >= 400:
            raise RuntimeError(f"build returned HTTP {payload[0]}")
        with _LOCK:
            cur = _ENTRIES.get(key)
            if cur is None or cur["started"] <= started:  # a replaced (stuck) build must not overwrite a newer one
                _ENTRIES[key] = {"mono": time.monotonic(), "wall": time.time(), "payload": payload, "started": started}
            _ERRORS.pop(key, None)
    except BaseException as e:  # noqa: BLE001 - recorded, last-good stays served
        with _LOCK:
            _ERRORS[key] = {"mono": time.monotonic(), "wall": time.time(), "error": f"{type(e).__name__}: {e}"[:300]}
    finally:
        with _LOCK:
            cur = _INFLIGHT.get(key)
            if cur is not None and cur["started"] == started:
                _INFLIGHT.pop(key, None)


def _start(key: str, build, ttl_s: float) -> bool:
    """Start the build for key unless one is in flight (and not stuck) or the last one failed < backoff ago.
    Caller holds _LOCK."""
    now = time.monotonic()
    cur = _INFLIGHT.get(key)
    if cur is not None and now - cur["started"] < STUCK_FACTOR * max(ttl_s, 1.0):
        return False
    err = _ERRORS.get(key)
    if err is not None and now - err["mono"] < max(ttl_s, MIN_BACKOFF_S):
        return False
    t = threading.Thread(target=_run, args=(key, build, now), daemon=True, name=f"swr-build-{key}"[:60])
    _INFLIGHT[key] = {"thread": t, "started": now}
    t.start()
    return True


def _state_meta(key: str, ttl_s: float, now: float) -> dict:
    """Build-state fields shared by the stale and the cold responses. Caller holds _LOCK."""
    meta: dict = {}
    cur = _INFLIGHT.get(key)
    if cur is not None:
        running = now - cur["started"]
        meta["build_running_s"] = round(running, 1)
        if running >= STUCK_FACTOR * max(ttl_s, 1.0):
            meta["build_stuck"] = True
    err = _ERRORS.get(key)
    if err is not None:
        meta["last_build_error"] = err["error"]
        meta["last_build_error_at"] = _iso(err["wall"])
    return meta


def get(key: str, ttl_s: float, build, *, annotate=None, unknown=None):
    """Never blocks on a build. See the module docstring."""
    annotate = annotate or _default_annotate
    unknown = unknown or _unknown_default
    with _LOCK:
        now = time.monotonic()
        ent = _ENTRIES.get(key)
        age = None if ent is None else now - ent["mono"]
        stale = ent is None or age >= ttl_s
        state = _state_meta(key, ttl_s, now)  # BEFORE _start: the poll that replaces a stuck build still reports it
        if stale:
            _start(key, build, ttl_s)
    if ent is None:
        if "last_build_error" in state and "build_running_s" not in state:
            state["reason"] = "build_failed"
        elif state.get("build_stuck"):
            state["reason"] = "build_stuck"
        else:
            state["reason"] = "building"
        return unknown(key, state)
    meta = {"as_of": _iso(ent["wall"]), "age_s": round(age, 1), "stale": bool(stale)}
    if stale:
        meta.update(state)
    return annotate(ent["payload"], meta)


def warm(key: str, ttl_s: float, build) -> bool:
    """Start the background build for key now (boot warm). True when a build was started."""
    with _LOCK:
        ent = _ENTRIES.get(key)
        if ent is not None and time.monotonic() - ent["mono"] < ttl_s:
            return False
        return _start(key, build, ttl_s)


def clear() -> None:  # tests
    with _LOCK:
        _ENTRIES.clear()
        _ERRORS.clear()
        _INFLIGHT.clear()


def inflight() -> list:
    with _LOCK:
        return sorted(_INFLIGHT)
