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
  reason build_stuck; stale: build_stuck true). Operator 13 Nov 2026 (containment point 3): NO replacement build
  starts while the stuck one runs. The replacement is refused REFUSED_DUPLICATE ("this process already runs a build
  of this key") until the stuck build truly ends; a lease or request timeout never releases its slot or key.
* N1 a build that RETURNS an HTTP-error tuple (status >= 400) is a failure, never stored as last-good.

MEM-CONTAIN 2026-11-13 (watchdog SIGKILL 14:30:57 ET, cgroup 2,861,133,824 B > memory.high, after four
parallel reports/analyst/links + cio-card + market-risk/latest builds):
* GLOBAL cap: at most SWR_MAX_CONCURRENT_BUILDS (default 2) builds run across ALL keys, counting stuck
  (replaced) builds that still run. Over the cap nothing is queued: the caller gets last-good / UNKNOWN
  with build_refused "REFUSED_CAP".
* MEMORY guard: a build is not STARTED while this process's cgroup NON-RECLAIMABLE usage >= SWR_MEMORY_GUARD_PCT
  (default 85) % of memory.high (cgroup found via /proc/self/cgroup -> /sys/fs/cgroup/<path>). Usage is
  memory.stat anon + kernel; on a kernel without the "kernel" key, memory.current - inactive_file; with no
  memory.stat at all, memory.current. Raw memory.current is NOT used when memory.stat is readable: under
  memory.high the kernel lets page cache fill up to the limit, so raw current would refuse builds for cache the
  kernel can drop (review N1, live 2026-11-13 15:27 ET: file 716 MB of 2.08 GB). Unreadable files or memory.high
  "max" -> fail open (build allowed): the cap and per-key dedupe still bound concurrency when the guard is blind,
  and failing closed would turn every route permanently UNKNOWN. The refusal is recorded (build_refused
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
* BUILD LEASE / OVERDUE (operator 2026-11-13 evening, supersedes review B3/NB1 reaping): a build older than
  SWR_BUILD_LEASE_S (default 300) is marked OVERDUE at the next build start, once: one ``ABANDONED_LEASE`` line is
  logged and stats() reports it in abandoned_builds (overdue threads still alive) and abandoned_total. An overdue
  build KEEPS its cap token, its host-wide build slot and its per-key lock until its thread really ends: capacity is
  tied to actual work, so a request or lease timeout never frees capacity while computation continues, and the same
  key is never built twice at once (REFUSED_DUPLICATE). When every slot is held by overdue builds, new builds are
  refused (REFUSED_CAP), callers are served last-good / UNKNOWN, and one rate-limited ``ALL_SLOTS_OVERDUE`` line is
  logged; the portfolio-server watchdog restart path (and its escalation) is what clears hung builds.
* LOCKING (review N5): the cgroup / proc reads and the slot-dir open + flock run OUTSIDE _LOCK. A build is first
  RESERVED under the lock (it counts against the cap and dedupes the key at once), the I/O runs unlocked, and the
  reservation is then committed (thread started) or rolled back (refusal recorded) under the lock again.
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
DEFAULT_BUILD_LEASE_S = 300.0

_LOCK = threading.Lock()
_ENTRIES: dict = {}  # key -> {"mono", "wall", "payload", "started"}
_INFLIGHT: dict = {}  # key -> {"thread", "started": mono}
_ERRORS: dict = {}  # key -> {"mono", "wall", "error"}
_RUNNING: dict = {}  # token -> {"key", "started", "slots", "thread"}: builds holding a cap token (incl. stuck)
_ABANDONED: dict = {}  # token -> {"key", "started", "abandoned_wall"}: overdue builds (still in _RUNNING, still holding capacity)
_ABANDONED_TOTAL = [0]
_ABANDON_LIMIT_LOGGED = [0.0]
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


def build_lease_s() -> float:
    return _env_float("SWR_BUILD_LEASE_S", DEFAULT_BUILD_LEASE_S)


def _iso(wall: float) -> str:
    return datetime.fromtimestamp(wall, tz=timezone.utc).isoformat(timespec="seconds")


def _default_annotate(payload, meta: dict):
    if isinstance(payload, dict):
        out = dict(payload)
        out.update(meta)
        return out
    return payload


_FRESHNESS_KEYS = ("as_of", "age_s", "stale")


def cache_annotate(payload, meta: dict):
    """Cache metadata that NEVER touches the payload's own fields (review B1): the cache's as_of / age_s / stale go
    out as cache_as_of / cache_age_s / cache_stale, the build-state fields (build_running_s, build_stuck,
    last_build_error[_at], build_refused[_at]) only where the payload has no key of that name. For payloads whose
    as_of / stale / state are a domain signal (the market-risk projection: engine evaluation time and staleness)."""
    if not isinstance(payload, dict):
        return payload
    out = dict(payload)
    out["cache_as_of"], out["cache_age_s"], out["cache_stale"] = meta.get("as_of"), meta.get("age_s"), meta.get("stale")
    for k, v in meta.items():
        if k not in _FRESHNESS_KEYS and k not in out:
            out[k] = v
    return out


def preserve_annotate(payload, meta: dict):
    """cache_annotate plus the plain as_of / age_s / stale, each only when the payload does not carry its own
    (review B1 audit: today's risk, cio-card and analyst-links payloads have none, so their top level is unchanged;
    a payload that gains one keeps it)."""
    out = cache_annotate(payload, meta)
    if isinstance(out, dict):
        for k in _FRESHNESS_KEYS:
            if k not in payload:
                out[k] = meta.get(k)
    return out


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


def _memory_stat(d: str) -> dict:
    out: dict = {}
    try:
        with open(os.path.join(d, "memory.stat"), encoding="ascii") as fh:
            for line in fh:
                parts = line.split()
                if len(parts) == 2:
                    try:
                        out[parts[0]] = int(parts[1])
                    except ValueError:
                        continue
    except OSError:
        return {}
    return out


def cgroup_memory():
    """(used, memory.high) in bytes for this process's cgroup, or (None, None) when unreadable or memory.high is
    "max" (no limit). ``used`` is the NON-RECLAIMABLE part (review N1): memory.stat anon + kernel, else
    memory.current - inactive_file, else (no memory.stat) memory.current. Fail-open: None means "allowed"."""
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
    st = _memory_stat(d)
    if "anon" in st and "kernel" in st:
        used = st["anon"] + st["kernel"]
    elif "inactive_file" in st:
        used = max(0, cur - st["inactive_file"])
    else:
        used = cur
    return used, high


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
        return f"memory used (anon+kernel, page cache excluded)={cur} >= {pct:g}% of memory.high={high}"
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
    kfd = None
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
        if kfd is not None:  # 3034b review A5: never leak the key lock (it would refuse that key for the process life)
            release_slots([kfd])
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
                                     "refused_cap": 0, "refused_memory": 0, "refused_duplicate": 0,
                                     "abandoned_lease": 0})
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
        abandoned = len(_ABANDONED)
    _emit("swr-stats", {"event": "swr_stats", "at": _iso(time.time()), "running_builds": running,
                        "abandoned_builds": abandoned, "routes": snap})


def stats() -> dict:
    with _LOCK:
        return {"running_builds": len(_RUNNING), "running_keys": sorted({r["key"] for r in _RUNNING.values()}),
                "abandoned_builds": len(_ABANDONED), "abandoned_total": _ABANDONED_TOTAL[0],
                "abandoned_keys": sorted({a["key"] for a in _ABANDONED.values()}),
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


def _run(key: str, build, started: float, token: int, wall0: float, rss0) -> None:
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
            if cur is not None and cur.get("token") == token:
                _INFLIGHT.pop(key, None)
            run = _RUNNING.pop(token, None)  # None only when clear() (tests) already took ownership
            abandoned = _ABANDONED.pop(token, None) is not None
            if run is not None:
                release_slots(run.get("slots"))  # the only owner left: released exactly once
            counters = _count(route, "built" if outcome == "BUILT" else "failed")
            running = len(_RUNNING)
        end = time.time()
        doc = {"event": "swr_build", "key": key, "route": route, "outcome": outcome, "start": _iso(wall0),
               "end": _iso(end), "build_ms": int(round((time.monotonic() - started) * 1000)),
               "rss_kb_before": rss0, "rss_kb_after": rss_kb(), "running_builds_after": running,
               "counters": counters}
        if abandoned:
            doc["abandoned_lease"] = True
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


def _reap_leases() -> list:
    """Mark every started build older than the lease OVERDUE, once. Caller holds _LOCK. Nothing is released: the
    build keeps its cap token, host slot and key lock until its thread ends (_run's finally). Returns log docs."""
    lease = build_lease_s()
    if lease <= 0:
        return []
    now = time.monotonic()
    docs = []
    for token, run in list(_RUNNING.items()):
        if run.get("thread") is None or now - run["started"] < lease or token in _ABANDONED:
            continue
        key = run["key"]
        _ABANDONED[token] = {"key": key, "started": run["started"], "abandoned_wall": time.time()}
        _ABANDONED_TOTAL[0] += 1
        route = _ROUTES.get(key, key)
        docs.append({"event": "swr_build", "key": key, "route": route, "outcome": "ABANDONED_LEASE",
                     "start": _iso(time.time() - (now - run["started"])), "end": None,
                     "running_s": round(now - run["started"], 1), "lease_s": lease, "rss_kb": None,
                     "holds_capacity": True, "running_builds_after": len(_RUNNING),
                     "abandoned_builds": len(_ABANDONED), "counters": _count(route, "abandoned_lease")})
    cap = max_concurrent_builds()
    if _RUNNING and len(_ABANDONED) >= cap and now - _ABANDON_LIMIT_LOGGED[0] >= _env_float(
            "SWR_REFUSE_LOG_INTERVAL_S", DEFAULT_REFUSE_LOG_INTERVAL_S):
        _ABANDON_LIMIT_LOGGED[0] = now
        docs.append({"event": "swr_build", "key": None, "route": None, "outcome": "ALL_SLOTS_OVERDUE",
                     "start": None, "end": None, "lease_s": lease, "rss_kb": None,
                     "abandoned_builds": len(_ABANDONED), "cap": cap, "running_builds_after": len(_RUNNING),
                     "overdue_keys": sorted({a["key"] for a in _ABANDONED.values()})})
    return docs


def _reserve(key: str, ttl_s: float):
    """Reserve a build for key unless one is in flight (and not stuck), the last one failed < backoff ago, or the
    per-process cap is reached. Caller holds _LOCK; nothing here reads a file. The reservation counts against the cap
    and dedupes the key at once; _launch commits or rolls it back. Returns (token or None, [log docs])."""
    docs = _reap_leases()
    now = time.monotonic()
    cur = _INFLIGHT.get(key)
    if cur is not None and now - cur["started"] < STUCK_FACTOR * max(ttl_s, 1.0):
        return None, docs
    err = _ERRORS.get(key)
    if err is not None and now - err["mono"] < max(ttl_s, MIN_BACKOFF_S):
        return None, docs
    if any(r["key"] == key for r in _RUNNING.values()):  # a stuck/overdue build of this key still holds its slot
        docs.append(_refuse(key, "REFUSED_DUPLICATE", "this process already runs a build of this key (stuck or overdue; held until it ends)", now))
        return None, docs
    cap = max_concurrent_builds()
    if len(_RUNNING) >= cap:
        docs.append(_refuse(key, "REFUSED_CAP", f"{len(_RUNNING)} builds running >= cap {cap}", now))
        return None, docs
    _TOKEN[0] += 1
    token = _TOKEN[0]
    _RUNNING[token] = {"key": key, "started": now, "slots": None, "thread": None}
    _INFLIGHT[key] = {"thread": None, "started": now, "token": token, "prev": cur}
    return token, docs


def _rollback(key: str, token: int, outcome: str, detail: str):
    """Undo a reservation and record the refusal (restores a stuck in-flight build it was replacing)."""
    with _LOCK:
        _RUNNING.pop(token, None)
        cur = _INFLIGHT.get(key)
        if cur is not None and cur.get("token") == token:
            prev = cur.get("prev")
            if prev is not None:
                _INFLIGHT[key] = prev
            else:
                _INFLIGHT.pop(key, None)
        return _refuse(key, outcome, detail, time.monotonic())


def _launch(key: str, build, token: int):
    """Called WITHOUT _LOCK (review N5): memory guard, host slots, RSS read, then commit + thread start under the
    lock. Returns (started: bool, log doc or None). Re-raises a Thread.start() failure after full cleanup."""
    cap = max_concurrent_builds()
    mem = _memory_refusal()
    if mem:
        return False, _rollback(key, token, "REFUSED_MEMORY", mem)
    slots, refused = acquire_host_slots(key, cap)
    if slots is None:
        if refused == "REFUSED_DUPLICATE":
            with _LOCK:
                mine = any(r["key"] == key for t, r in _RUNNING.items() if t != token)
            detail = ("this process already runs a build of this key (stuck or overdue; held until it ends)"
                      if mine else "another process on this host is building this key")
        else:
            detail = f"all {cap} host-wide build slots held ({slot_dir()})"
        return False, _rollback(key, token, refused, detail)
    rss0, wall0 = rss_kb(), time.time()
    with _LOCK:
        run = _RUNNING.get(token)
        if run is None:  # cleared meanwhile (tests): give the slots straight back
            release_slots(slots)
            return False, None
        t = threading.Thread(target=_run, args=(key, build, run["started"], token, wall0, rss0), daemon=True,
                             name=f"swr-build-{key}"[:60])
        run["slots"], run["thread"] = slots, t
        cur = _INFLIGHT.get(key)
        if cur is not None and cur.get("token") == token:
            cur["thread"] = t
            cur.pop("prev", None)
        _REFUSED.pop(key, None)
        try:
            t.start()
        except BaseException:  # noqa: BLE001 - never leak a slot or a phantom running build
            _RUNNING.pop(token, None)
            if cur is not None and _INFLIGHT.get(key) is cur:
                _INFLIGHT.pop(key, None)
            release_slots(slots)
            raise
    return True, None


def _emit_build_docs(docs) -> None:
    for d in docs:
        if not d:
            continue
        if d.get("outcome") == "ABANDONED_LEASE":
            d["rss_kb"] = rss_kb()
        _emit("swr-build", d)


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
    docs: list = []
    token = None
    with _LOCK:
        if route:
            _ROUTES[key] = route
        r = _ROUTES.get(key, key)
        now = time.monotonic()
        ent = _ENTRIES.get(key)
        age = None if ent is None else now - ent["mono"]
        stale = ent is None or age >= ttl_s
        state = _state_meta(key, ttl_s, now)  # BEFORE _reserve: the poll that replaces a stuck build still reports it
        if stale:
            token, docs = _reserve(key, ttl_s)
        _count(r, "unknown" if ent is None else ("stale" if stale else "hit"))
    if token is not None:
        _, doc = _launch(key, build, token)
        docs.append(doc)
    if stale:
        with _LOCK:
            ref = _REFUSED.get(key)
            cur = _INFLIGHT.get(key)
            # a refusal newer than the running build is shown too (review N6: the refused stuck replacement)
            if ref is not None and (cur is None or ref["mono"] >= cur["started"]):
                state["build_refused"] = ref["outcome"]
                state["build_refused_at"] = _iso(ref["wall"])
    _emit_build_docs(docs)
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
        token, docs = _reserve(key, ttl_s)
    started = False
    if token is not None:
        started, doc = _launch(key, build, token)
        docs.append(doc)
    _emit_build_docs(docs)
    return started


def clear() -> None:  # tests
    with _LOCK:
        for run in _RUNNING.values():  # ownership moves here: the build's own finally finds nothing to release
            release_slots(run.get("slots"))
            run["slots"] = None
        _ENTRIES.clear()
        _ERRORS.clear()
        _INFLIGHT.clear()
        _RUNNING.clear()
        _ABANDONED.clear()
        _ABANDONED_TOTAL[0] = 0
        _ABANDON_LIMIT_LOGGED[0] = 0.0
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
