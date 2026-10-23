"""Single-flight coalescing of identical heavy GETs in portfolio-server (2026-10-23).

Why: on 2026-10-23 portfolio-server was SIGKILLed at its 1.5 GB MemoryHigh while identical
heavy reads ran side by side -- seven concurrent ``GET /api/v2/watchlist/items`` (each
~200 MB peak and 41-49 s), three ``/api/v2/paper-proposals`` per poll, a dozen
``/api/v2/reports/analyst/links`` -- one per open tab, headless validation browser or retry.
Under memory.high throttling every request slowed (paper-proposals 231 s, watch-prospects
464 s), threads piled up to 130 and the watchdog killed the process
(docs/ops/SERVER_MEMORY_SPIKES_2026-10-23.md).

``coalesce(key, fn)``: while a computation for ``key`` is in flight, later callers wait for it
instead of starting their own; a finished result is reused for ``ttl`` seconds (default 2 s,
so near-simultaneous polls also share). Errors are re-raised to the waiters and never cached.
Each caller gets its own top-level dict copy (the HTTP layer stamps ``_serving`` into the top
level and pops ``__etag__`` from ``body`` and ``body["data"]``), so no two threads mutate one
dict. Only an allowlist of read routes is coalesced (``COALESCE_PATHS``; env
``TRADEAI_COALESCE_GET_PATHS`` replaces it, ``TRADEAI_COALESCE_GET=0`` turns it off).

Stdlib only. READ_ONLY_ADVISORY: no state is written; MBI=0.
"""
from __future__ import annotations

import os
import threading
import time
from typing import Any, Callable

DEFAULT_COALESCE_PATHS = (
    "/api/v2/watchlist/items",
    "/api/v2/paper-proposals",
    "/api/v2/reports/analyst/links",
    "/api/v3/data-broker/watch-prospects",
    "/api/v3/data-broker/watch-intelligence",
    "/api/v2/hermes/health",
    "/api/v2/portfolio/performance",
    "/api/v2/open-trades/intelligence",
    "/api/v2/cio/capital-plan",
    "/api/v2/home/do-now",
    "/api/v2/overview",
    "/api/v2/risk",
    "/api/v2/needs-action",
    "/api/v2/defense/posture",
    "/api/v2/portfolio/book-map",
    "/api/v2/system-health",
    "/api/v3/advisory",
    "/api/v3/maturity/memory",
)
TTL_S = float(os.environ.get("TRADEAI_COALESCE_TTL_S") or 2.0)
WAIT_S = float(os.environ.get("TRADEAI_COALESCE_WAIT_S") or 180.0)
MAX_DONE = 128
# Query keys that only bust browser caches; they never change the response.
_IGNORED_QUERY_KEYS = frozenset({"_"})


def _paths_from_env() -> frozenset[str]:
    raw = os.environ.get("TRADEAI_COALESCE_GET_PATHS")
    if raw is None:
        return frozenset(DEFAULT_COALESCE_PATHS)
    return frozenset(p.strip().rstrip("/") for p in raw.split(",") if p.strip())


COALESCE_PATHS = _paths_from_env()


def enabled() -> bool:
    return os.environ.get("TRADEAI_COALESCE_GET", "1").strip().lower() not in ("0", "false", "off", "no")


def request_key(path: str, query: dict | None, principal: str = "") -> str | None:
    """Coalescing key for a GET, or None when the route is not coalesced.

    The authenticated principal is part of the key: two identities never share a body."""
    base = (path or "").split("?", 1)[0].rstrip("/")
    if not enabled() or base not in COALESCE_PATHS:
        return None
    items = []
    for k, v in sorted((query or {}).items()):
        if k in _IGNORED_QUERY_KEYS:
            continue
        if isinstance(v, (list, tuple)):
            v = ",".join(str(x) for x in v)
        items.append(f"{k}={v}")
    return (principal or "") + "|" + base + "?" + "&".join(items)


class _Flight:
    __slots__ = ("event", "value", "error")

    def __init__(self) -> None:
        self.event = threading.Event()
        self.value: Any = None
        self.error: BaseException | None = None


class Coalescer:
    def __init__(self, ttl: float = TTL_S, wait_s: float = WAIT_S, max_done: int = MAX_DONE) -> None:
        self.ttl = ttl
        self.wait_s = wait_s
        self.max_done = max_done
        self._lock = threading.Lock()
        self._inflight: dict[str, _Flight] = {}
        self._done: dict[str, tuple[float, Any]] = {}
        self.stats = {"computed": 0, "joined": 0, "reused": 0}

    def _prune(self, now: float) -> None:
        for k in [k for k, (t, _) in self._done.items() if now - t >= self.ttl]:
            self._done.pop(k, None)
        while len(self._done) > self.max_done:
            self._done.pop(next(iter(self._done)))

    def run(self, key: str, fn: Callable[[], Any]) -> Any:
        now = time.monotonic()
        with self._lock:
            hit = self._done.get(key)
            if hit is not None and now - hit[0] < self.ttl:
                self.stats["reused"] += 1
                return hit[1]
            flight = self._inflight.get(key)
            leader = flight is None
            if leader:
                flight = _Flight()
                self._inflight[key] = flight
            else:
                self.stats["joined"] += 1
        if not leader:
            if flight.event.wait(self.wait_s):
                if flight.error is not None:
                    raise flight.error
                return flight.value
            return fn()  # leader stuck past wait_s: compute independently rather than hang
        try:
            flight.value = fn()
        except BaseException as exc:  # noqa: BLE001 - re-raised to every waiter
            flight.error = exc
        finally:
            with self._lock:
                self._inflight.pop(key, None)
                self.stats["computed"] += 1
                if flight.error is None:
                    done_at = time.monotonic()
                    self._prune(done_at)
                    self._done[key] = (done_at, flight.value)
            flight.event.set()
        if flight.error is not None:
            raise flight.error
        return flight.value


_DEFAULT = Coalescer()


def per_caller_copy(result: Any) -> Any:
    """(status, body) with a fresh top-level body dict and a fresh body["data"] dict."""
    if isinstance(result, tuple) and len(result) == 2 and isinstance(result[1], dict):
        body = dict(result[1])
        if isinstance(body.get("data"), dict):
            body["data"] = dict(body["data"])
        return (result[0], body)
    return result


def coalesce_get(
    path: str,
    query: dict | None,
    fn: Callable[[], Any],
    *,
    principal: str = "",
    coalescer: Coalescer | None = None,
) -> Any:
    """Run ``fn`` (a GET dispatch returning (status, body) or None) single-flight per request key."""
    key = request_key(path, query, principal)
    if key is None:
        return fn()
    return per_caller_copy((coalescer or _DEFAULT).run(key, fn))
