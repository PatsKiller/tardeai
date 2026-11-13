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

MEM-CONTAIN 2026-11-13 (watchdog SIGKILL 14:30:57 ET, cgroup 2,861,133,824 B > memory.high, after four
parallel reports/analyst/links + cio-card + market-risk/latest builds):
* GLOBAL cap: at most SWR_MAX_CONCURRENT_BUILDS (default 2) builds run across ALL keys, counting stuck
  (replaced) builds that still run. Over the cap nothing is queued: the caller gets last-good / UNKNOWN
  with build_refused "REFUSED_CAP".
* MEMORY guard: a build is not STARTED while this process's cgroup memory.current >= SWR_MEMORY_GUARD_PCT
  (default 85) % of memory.high (cgroup found via /proc/self/cgroup -> /sys/fs/cgroup/<path>). Unreadable
  files or memory.high "max" -> fail open (build allowed). The refusal is recorded (build_refused
  "REFUSED_MEMORY", counters, one log line per key per SWR_REFUSE_LOG_INTERVAL_S).
* A failed build keeps last-good; an older build never overwrites (nor errors over) a newer stored result.
* One structured log line per build outcome on stdout: ``[swr-build] {json}`` with key, route, start/end,
  build_ms, rss_kb before/after (/proc/self/status VmRSS), outcome BUILT|FAILED|REFUSED_CAP|REFUSED_MEMORY,
  running builds and the route's hit/stale/unknown counters. ``[swr-stats] {json}`` every
  SWR_STATS_LOG_INTERVAL_S (default 60) with every route's counters.
* HOST-WIDE (operator correction 2026-11-13 15:07 ET): the cap is also enforced across processes by an fcntl
  flock slot pool in SWR_SLOT_DIR (default ~/trade-ai-releases/persistent-state/data/ops/swr_build_slots when
  data/ops exists): N = SWR_MAX_CONCURRENT_BUILDS files slot-<i>.lock, acquired NON-BLOCKING by the build thread
  and held until it ends (the kernel drops the lock if the process dies). A per-key lock file (key-<sha1>.lock)
  dedupes across processes: the same key is never built twice at once anywhere on the host (REFUSED_DUPLICATE).
  Nothing waits: no free slot -> REFUSED_CAP, the caller is served last-good / UNKNOWN (queue length 0).
  An unusable slot dir fails open to the per-process cap and is logged once. SWR_SLOT_DIR=off disables it.
  Under pytest the pool is off unless SWR_SLOT_DIR is set (tests never touch the live slots).
* TEMPORARY CONTAINMENT. A Python thread cannot be cancelled: a build that has started runs to completion even
  when every client has gone. What bounds it is the cap (at most N such builds host-wide) and the per-key dedupe.
  The completed fix moves these builds out of portfolio-server.
* Entries are bounded (SWR_MAX_ENTRIES, default 256; least recently stored evicted) so per-query keys
  cannot grow the cache without limit.
"""
from __future__ import annotations

import errno
import fcntl
import hashlib
import json
import os
import sys
import threading
import time
from datetime import datetime, timezone

MIN_BACKOFF_S = 5.0
STUCK_FACTOR = 5.0
DEFAULT_MAX_CONCURRENT_BUILDS = 2
DEFAULT_MEMORY_GUARD_PCT = 85.0
DEFAULT_MAX_ENTRIES = 256
DEFAULT_REFUSE_LOG_INTERVAL_S = 30.0
DEFAULT_STATS_LOG_INTERVAL_S = 60.0

_LOCK = threading.Lock()
_ENTRIES: dict = {}  # key -> {"mono", "wall", "payload", "started"}
_INFLIGHT: dict = {}  # key -> {"thread", "started": mono}
_ERRORS: dict = {}  # key -> {"mono", "wall", "error"}
_RUNNING: dict = {}  # token -> key: every build thread still running (incl. replaced stuck builds)
_REFUSED: dict = {}  # key -> {"mono", "wall", "outcome", "detail", "logged_mono"}
_COUNTERS: dict = {}  # route -> {"hit", "stale", "unknown", "built", "failed", "refused_cap", "refused_memory"}
_ROUTES: dict = {}  # key -> route
_STATS_LOGGED = [0.0]
_TOKEN = [0]


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "") or default)
    except ValueError:
        return default


def max_concurrent_builds() -> int:
    return max(1, int(_env_float("SWR_MAX_CONCURRENT_BUILDS", DEFAULT_MAX_CONCURRENT_BUILDS)))


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


# ── process / cgroup readers (module-level so tests can replace them) ─────────────────────────────────────────
def rss_kb():
    """VmRSS of this process in kB, or None."""
    try:
        with open("/proc/self/status", encoding="ascii", errors="replace") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1])
    except (OSError, ValueError, IndexError):
        return None
    return None


_CGROUP_DIR: list = []  # cached once: [path or None]


def _cgroup_dir():
    if not _CGROUP_DIR:
        path = None
        try:
            with open("/proc/self/cgroup", encoding="ascii", errors="replace") as fh:
                for line in fh:
                    parts = line.rstrip("\n").split(":", 2)
                    if len(parts) == 3 and parts[0] == "0" and parts[1] == "":  # cgroup v2 unified line
                        cand = "/sys/fs/cgroup" + parts[2]
                        if os.path.isdir(cand):
                            path = cand
                        break
        except OSError:
            path = None
        _CGROUP_DIR.append(path)
    return _CGROUP_DIR[0]


def cgroup_memory():
    """(memory.current, memory.high) in bytes for this process's cgroup, or (None, None) when unreadable or
    memory.high is "max" (no limit). Fail-open: the caller treats None as "allowed"."""
    d = _cgroup_dir()
    if not d:
        return None, None
    try:
        with open(os.path.join(d, "memory.current"), encoding="ascii") as fh:
            cur = int(fh.read().strip())
        with open(os.path.join(d, "memory.high"), encoding="ascii") as fh:
            raw = fh.read().strip()
        high = None if raw == "max" else int(raw)
    except (OSError, ValueError):
        return None, None
    return cur, high


def _memory_refusal():
    """Detail string when the memory guard refuses to start a build, else None (also None when unreadable)."""
    pct = _env_float("SWR_MEMORY_GUARD_PCT", DEFAULT_MEMORY_GUARD_PCT)
    if pct <= 0:
        return None
    try:
        cur, high = cgroup_memory()
    except Exception:  # noqa: BLE001 - fail open
        return None
    if not cur or not high:
        return None
    if cur >= high * pct / 100.0:
        return f"memory.current={cur} >= {pct:g}% of memory.high={high}"
    return None


# ── host-wide slot pool (fcntl flock) ──────────────────────────────────────────────────────────────────────
_SLOT_WARNED = [False]


def slot_dir():
    """The host-wide slot directory, or None (pool off: per-process cap only)."""
    raw = os.environ.get("SWR_SLOT_DIR")
    if raw is not None:
        raw = raw.strip()
        return None if raw.lower() in ("", "off", "0", "none") else raw
    if "PYTEST_CURRENT_TEST" in os.environ:
        return None
    ops = os.path.join(os.path.expanduser("~"), "trade-ai-releases", "persistent-state", "data", "ops")
    return os.path.join(ops, "swr_build_slots") if os.path.isdir(ops) else None


def _flock_nb(path: str):
    """Open path and take a non-blocking exclusive flock. The open file, or None when another holder has it."""
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as e:
        os.close(fd)
        if e.errno in (errno.EAGAIN, errno.EACCES, errno.EWOULDBLOCK):
            return None
        raise
    return fd


def release_slots(fds) -> None:
    for fd in fds or ():
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        try:
            os.close(fd)
        except OSError:
            pass


def acquire_host_slots(key: str, cap: int):
    """(fds, None) on success (fds == [] when the pool is off/unusable), or (None, outcome) when refused:
    REFUSED_DUPLICATE (the same key is building in some process on this host) or REFUSED_CAP (all N slots held)."""
    d = slot_dir()
    if not d:
        return [], None
    try:
        os.makedirs(d, mode=0o700, exist_ok=True)
        kfd = _flock_nb(os.path.join(d, "key-" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:20] + ".lock"))
        if kfd is None:
            return None, "REFUSED_DUPLICATE"
        for i in range(cap):
            sfd = _flock_nb(os.path.join(d, f"slot-{i}.lock"))
            if sfd is not None:
                try:
                    os.ftruncate(sfd, 0)
                    os.write(sfd, f"pid={os.getpid()} at={_iso(time.time())}\n".encode())
                except OSError:
                    pass
                return [kfd, sfd], None
        release_slots([kfd])
        return None, "REFUSED_CAP"
    except OSError as e:  # fail open to the per-process cap; say so once
        if not _SLOT_WARNED[0]:
            _SLOT_WARNED[0] = True
            _emit("swr-build", {"event": "swr_slot_pool_unavailable", "dir": d, "error": f"{type(e).__name__}: {e}"})
        return [], None


# ── logging / counters ────────────────────────────────────────────────────────────────────────────────────────
def _emit(tag: str, doc: dict) -> None:
    try:
        print(f"[{tag}] " + json.dumps(doc, sort_keys=True, default=str), file=sys.stdout, flush=True)
    except Exception:  # noqa: BLE001 - logging never breaks a request
        pass


def _count(route: str, field: str) -> dict:
    """Caller holds _LOCK."""
    c = _COUNTERS.setdefault(route, {"hit": 0, "stale": 0, "unknown": 0, "built": 0, "failed": 0,
                                     "refused_cap": 0, "refused_memory": 0, "refused_duplicate": 0})
    c[field] += 1
    return dict(c)


def _maybe_log_stats() -> None:
    interval = _env_float("SWR_STATS_LOG_INTERVAL_S", DEFAULT_STATS_LOG_INTERVAL_S)
    if interval <= 0:
        return
    now = time.monotonic()
    with _LOCK:
        if now - _STATS_LOGGED[0] < interval:
            return
        _STATS_LOGGED[0] = now
        snap = {r: dict(c) for r, c in _COUNTERS.items()}
        running = len(_RUNNING)
    _emit("swr-stats", {"event": "swr_stats", "at": _iso(time.time()), "running_builds": running, "routes": snap})


def stats() -> dict:
    with _LOCK:
        return {"running_builds": len(_RUNNING), "running_keys": sorted(set(_RUNNING.values())),
                "routes": {r: dict(c) for r, c in _COUNTERS.items()},
                "refused": {k: {"outcome": v["outcome"], "at": _iso(v["wall"]), "detail": v["detail"]}
                            for k, v in _REFUSED.items()}}


# ── build machinery ───────────────────────────────────────────────────────────────────────────────────────────
def _store(key: str, payload, started: float) -> None:
    """Caller holds _LOCK."""
    cur = _ENTRIES.get(key)
    if cur is not None and cur["started"] > started:  # an older (replaced) build never overwrites a newer result
        return
    _ENTRIES.pop(key, None)
    _ENTRIES[key] = {"mono": time.monotonic(), "wall": time.time(), "payload": payload, "started": started}
    cap = int(_env_float("SWR_MAX_ENTRIES", DEFAULT_MAX_ENTRIES))
    while cap > 0 and len(_ENTRIES) > cap:
        _ENTRIES.pop(next(iter(_ENTRIES)))


def _run(key: str, build, started: float, token: int, wall0: float, rss0, slots=None) -> None:
    route = _ROUTES.get(key, key)
    outcome, err_text = "BUILT", None
    try:
        payload = build()
        if isinstance(payload, tuple) and payload and isinstance(payload[0], int) and payload[0] >= 400:
            raise RuntimeError(f"build returned HTTP {payload[0]}")
        with _LOCK:
            _store(key, payload, started)
            _ERRORS.pop(key, None)
            _REFUSED.pop(key, None)
    except BaseException as e:  # noqa: BLE001 - recorded, last-good stays served
        outcome, err_text = "FAILED", f"{type(e).__name__}: {e}"[:300]
        with _LOCK:
            cur = _ENTRIES.get(key)
            if cur is None or cur["started"] <= started:  # a newer success is not shadowed by an old failure
                _ERRORS[key] = {"mono": time.monotonic(), "wall": time.time(), "error": err_text}
    finally:
        with _LOCK:
            cur = _INFLIGHT.get(key)
            if cur is not None and cur["started"] == started:
                _INFLIGHT.pop(key, None)
            _RUNNING.pop(token, None)
            release_slots(slots)
            counters = _count(route, "built" if outcome == "BUILT" else "failed")
            running = len(_RUNNING)
        end = time.time()
        doc = {"event": "swr_build", "key": key, "route": route, "outcome": outcome, "start": _iso(wall0),
               "end": _iso(end), "build_ms": int(round((time.monotonic() - started) * 1000)),
               "rss_kb_before": rss0, "rss_kb_after": rss_kb(), "running_builds_after": running,
               "counters": counters}
        if err_text:
            doc["error"] = err_text
        _emit("swr-build", doc)


def _refuse(key: str, outcome: str, detail: str, now: float):
    """Record a refusal; return the log doc when it should be logged (rate-limited). Caller holds _LOCK."""
    route = _ROUTES.get(key, key)
    counters = _count(route, outcome.lower())
    prev = _REFUSED.get(key)
    interval = _env_float("SWR_REFUSE_LOG_INTERVAL_S", DEFAULT_REFUSE_LOG_INTERVAL_S)
    log_it = prev is None or prev.get("outcome") != outcome or now - prev.get("logged_mono", 0.0) >= interval
    _REFUSED[key] = {"mono": now, "wall": time.time(), "outcome": outcome, "detail": detail,
                     "logged_mono": now if log_it else prev.get("logged_mono", 0.0)}
    if not log_it:
        return None
    return {"event": "swr_build", "key": key, "route": route, "outcome": outcome, "start": _iso(time.time()),
            "end": None, "build_ms": 0, "rss_kb_before": None, "rss_kb_after": None,
            "running_builds_after": len(_RUNNING), "detail": detail, "counters": counters}


def _start(key: str, build, ttl_s: float):
    """Start the build for key unless one is in flight (and not stuck), the last one failed < backoff ago, the
    global cap is reached, or the memory guard refuses. Caller holds _LOCK.

    Returns (started: bool, log_doc or None) — the caller logs outside the lock."""
    now = time.monotonic()
    cur = _INFLIGHT.get(key)
    if cur is not None and now - cur["started"] < STUCK_FACTOR * max(ttl_s, 1.0):
        return False, None
    err = _ERRORS.get(key)
    if err is not None and now - err["mono"] < max(ttl_s, MIN_BACKOFF_S):
        return False, None
    cap = max_concurrent_builds()
    if len(_RUNNING) >= cap:
        return False, _refuse(key, "REFUSED_CAP", f"{len(_RUNNING)} builds running >= cap {cap}", now)
    mem = _memory_refusal()
    if mem:
        return False, _refuse(key, "REFUSED_MEMORY", mem, now)
    slots, refused = acquire_host_slots(key, cap)
    if slots is None:
        detail = ("another process on this host is building this key" if refused == "REFUSED_DUPLICATE"
                  else f"all {cap} host-wide build slots held ({slot_dir()})")
        return False, _refuse(key, refused, detail, now)
    _TOKEN[0] += 1
    token = _TOKEN[0]
    wall0 = time.time()
    t = threading.Thread(target=_run, args=(key, build, now, token, wall0, rss_kb(), slots), daemon=True,
                         name=f"swr-build-{key}"[:60])
    _INFLIGHT[key] = {"thread": t, "started": now}
    _RUNNING[token] = key
    _REFUSED.pop(key, None)
    try:
        t.start()
    except BaseException:  # noqa: BLE001 - never leak a slot or a phantom running build
        _INFLIGHT.pop(key, None)
        _RUNNING.pop(token, None)
        release_slots(slots)
        raise
    return True, None


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


def get(key: str, ttl_s: float, build, *, annotate=None, unknown=None, route: str | None = None):
    """Never blocks on a build. See the module docstring. ``route`` labels the log lines and counters."""
    annotate = annotate or _default_annotate
    unknown = unknown or _unknown_default
    log_doc = None
    with _LOCK:
        if route:
            _ROUTES[key] = route
        r = _ROUTES.get(key, key)
        now = time.monotonic()
        ent = _ENTRIES.get(key)
        age = None if ent is None else now - ent["mono"]
        stale = ent is None or age >= ttl_s
        state = _state_meta(key, ttl_s, now)  # BEFORE _start: the poll that replaces a stuck build still reports it
        if stale:
            _, log_doc = _start(key, build, ttl_s)
            ref = _REFUSED.get(key)
            if ref is not None and key not in _INFLIGHT:
                state["build_refused"] = ref["outcome"]
                state["build_refused_at"] = _iso(ref["wall"])
        _count(r, "unknown" if ent is None else ("stale" if stale else "hit"))
    if log_doc:
        _emit("swr-build", log_doc)
    _maybe_log_stats()
    if ent is None:
        if "last_build_error" in state and "build_running_s" not in state:
            state["reason"] = "build_failed"
        elif state.get("build_stuck"):
            state["reason"] = "build_stuck"
        elif "build_refused" in state and "build_running_s" not in state:
            state["reason"] = "build_deferred"
        else:
            state["reason"] = "building"
        return unknown(key, state)
    meta = {"as_of": _iso(ent["wall"]), "age_s": round(age, 1), "stale": bool(stale)}
    if stale:
        meta.update(state)
    return annotate(ent["payload"], meta)


def peek(key: str, max_age_s: float):
    """The stored payload for key when younger than max_age_s, else None. Never starts a build."""
    with _LOCK:
        ent = _ENTRIES.get(key)
        if ent is None or time.monotonic() - ent["mono"] >= max_age_s:
            return None
        return ent["payload"]


def warm(key: str, ttl_s: float, build) -> bool:
    """Start the background build for key now (boot warm). True when a build was started."""
    with _LOCK:
        ent = _ENTRIES.get(key)
        if ent is not None and time.monotonic() - ent["mono"] < ttl_s:
            return False
        started, log_doc = _start(key, build, ttl_s)
    if log_doc:
        _emit("swr-build", log_doc)
    return started


def clear() -> None:  # tests
    with _LOCK:
        _ENTRIES.clear()
        _ERRORS.clear()
        _INFLIGHT.clear()
        _RUNNING.clear()
        _REFUSED.clear()
        _COUNTERS.clear()
        _ROUTES.clear()
        _STATS_LOGGED[0] = 0.0


def inflight() -> list:
    with _LOCK:
        return sorted(_INFLIGHT)


def running_builds() -> int:
    with _LOCK:
        return len(_RUNNING)
