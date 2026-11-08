"""Stale-while-revalidate for slow desk GETs in portfolio-server (LQ-20261107-201).

Why: on 2026-11-07 the desk pages (/v3/agents, defense, portfolio, re-entry, rec-intel,
advisory) showed "unavailable". Their reads took 16-44 s even warm
(``/api/v2/defense/engine`` 44 s, ``/api/v2/portfolio/holdings`` 20 s,
``/api/v2/desks/agents`` 20 s, ``/api/v3/advisory`` 16 s) and the browser gives up at 30 s.
Every request recomputed the projection inside the request.

``StaleServe.get(key, compute, refresh)``:

- A last good body younger than ``fresh_s`` is served as is.
- An older one, up to ``max_stale_s``, is served immediately, marked stale. One background
  refresh for that key is started; a second caller never starts another.
- With no last good body, or one older than ``max_stale_s``, the request computes inline,
  as before.

"Good" means ``(200, dict)`` whose ``ok`` is not False. Errors and non-200 answers are
passed through and never cached. A failed background refresh keeps the last good body and
records the error in the stamp.

Each served body carries ``_swr`` (``StaleWhileRevalidate@v1``):
``as_of`` (when the body was computed), ``age_s``, ``stale``, ``refreshing``, ``source``
(``computed`` | ``memory`` | ``disk``) and ``last_refresh_error``.

Last good bodies are also written, 0600 and atomically, to ``store_dir``, so a restart
serves the previous body instead of a cold 20-40 s compute. The key includes the
authenticated principal, so one identity never receives another's body. A disk copy is
only served to the same key.

Only an allowlist of read routes is wrapped (``SWR_PATHS``; env ``TRADEAI_SWR_GET_PATHS``
replaces it, ``TRADEAI_SWR=0`` turns it off).

Invalidate on write (LQ-20261107-258). ``invalidate(path)`` records the time and drops the
path's bodies; a body whose compute STARTED before that time is never served or stored
again, from memory or from disk, so the next read computes inline with the write included,
and a refresh that was already running when the write landed cannot put the old view back.
``invalidate_for_write(path)`` maps a POST path to the cached reads it can change
(``WRITE_INVALIDATES``); the server calls it after every POST. The times persist in
``store_dir/_invalidated.json``, so a restart honours them.

``PATH_MAX_STALE_S`` caps the stale window per route: the watchlist carries prices, and
the page does not show the ``_swr`` age yet, so it is never served more than an hour old.

Stdlib only. READ_ONLY_ADVISORY: it caches read responses and writes only its own cache
files; MBI=0.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

SCHEMA = "StaleWhileRevalidate@v1"
DEFAULT_SWR_PATHS = (
    "/api/v2/desks/agents",
    "/api/v2/desks/defense",
    "/api/v2/desks/reentry",
    "/api/v2/defense/engine",
    "/api/v2/portfolio/holdings",
    "/api/v3/advisory",
    "/api/v3/cio/home",
    # LQ-20261107-258: 25-35 s cold (per-row decision snapshots, ATR bars, the picked SQL),
    # 3 MB, and the first thing a phone loads. Cleared on every watchlist write below.
    "/api/v2/watchlist/items",
    # LQ-20261107-822: 3.8-4.3 s normally and 16.9 s at load 27, for a body that is a 30-day
    # spend/usage rollup. Nearly every request re-parsed the 114 MB provider-cost events file
    # before answering (anthropic_monitoring._events, 0.6-1.3 s of CPU alone). Bounded to
    # PATH_MAX_STALE_S below because "today" counters move with every LLM call.
    "/api/v2/consumption/overview",
)
#: A cached read older than this is recomputed inline, whatever MAX_STALE_S says.
PATH_MAX_STALE_S = {
    "/api/v2/watchlist/items": 3600.0,
    # LQ-20261107-822: a spend/usage page, not a price page — but its "today" counters and its
    # advisory insights really do move during a session, so never present more than 5 minutes
    # of staleness even when every background refresh fails.
    "/api/v2/consumption/overview": 300.0,
}
#: cached GET path -> substrings of the POST paths that can change it. Over-matching only
#: costs one inline compute; under-matching would show an operator the pre-write list.
_WATCH_WRITE_MARKERS = ("watch", "screener", "discovery", "prospect", "hermes", "star",
                        "directive", "curation")
WRITE_INVALIDATES = {
    "/api/v2/watchlist/items": _WATCH_WRITE_MARKERS,
    "/api/v3/data-broker/watch-curation": _WATCH_WRITE_MARKERS,
    # LQ-20261107-822: the operator's own consumption writes — process-mode, stop-advisory,
    # run-manual, caller-priorities — change the insights and the mode counts this body carries.
    # A read right after one must compute with the write in it, not serve the pre-write view.
    "/api/v2/consumption/overview": ("/api/v2/consumption",),
}
INVALIDATIONS_FILE = "_invalidated.json"
FRESH_S = float(os.environ.get("TRADEAI_SWR_FRESH_S") or 60.0)
MAX_STALE_S = float(os.environ.get("TRADEAI_SWR_MAX_STALE_S") or 6 * 3600.0)
MAX_ENTRIES = 64


def _paths_from_env() -> frozenset[str]:
    raw = os.environ.get("TRADEAI_SWR_GET_PATHS")
    if raw is None:
        return frozenset(DEFAULT_SWR_PATHS)
    return frozenset(p.strip().rstrip("/") for p in raw.split(",") if p.strip())


SWR_PATHS = _paths_from_env()


def enabled() -> bool:
    return os.environ.get("TRADEAI_SWR", "1").strip().lower() not in ("0", "false", "off", "no")


def is_swr_path(path: str) -> bool:
    return enabled() and (path or "").split("?", 1)[0].rstrip("/") in SWR_PATHS


def request_key(path: str, query: dict | None, principal: str = "") -> str:
    """Cache key: principal, path and the query minus the cache-buster ``_``."""
    base = (path or "").split("?", 1)[0].rstrip("/")
    items = []
    for k, v in sorted((query or {}).items()):
        if k == "_":
            continue
        if isinstance(v, (list, tuple)):
            v = ",".join(str(x) for x in v)
        items.append(f"{k}={v}")
    return (principal or "") + "|" + base + "?" + "&".join(items)


def key_path(key: str) -> str:
    """The route part of a ``request_key``: ``principal|/path?query`` -> ``/path``."""
    rest = key.split("|", 1)[1] if "|" in key else key
    return rest.split("?", 1)[0].rstrip("/")


def is_good(result: Any) -> bool:
    return (isinstance(result, tuple) and len(result) == 2 and result[0] == 200
            and isinstance(result[1], dict) and result[1].get("ok") is not False)


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()


class _Entry:
    __slots__ = ("computed_at", "result", "source", "started_at")

    def __init__(self, computed_at: float, result: tuple, source: str,
                 started_at: float | None = None) -> None:
        self.computed_at = computed_at
        self.result = result
        self.source = source
        # when the compute began: what it read can be no newer than this
        self.started_at = computed_at if started_at is None else started_at


class StaleServe:
    def __init__(self, store_dir: Path | str | None = None, *, fresh_s: float = FRESH_S,
                 max_stale_s: float = MAX_STALE_S, max_entries: int = MAX_ENTRIES,
                 clock: Callable[[], float] = time.time,
                 spawn: Callable[[Callable[[], None]], None] | None = None) -> None:
        self.store_dir = Path(store_dir) if store_dir else None
        self.fresh_s = fresh_s
        self.max_stale_s = max_stale_s
        self.max_entries = max_entries
        self.clock = clock
        self._spawn = spawn or _daemon_thread
        self._lock = threading.Lock()
        self._mem: dict[str, _Entry] = {}
        self._refreshing: set[str] = set()
        self._errors: dict[str, str] = {}
        self._invalidated: dict[str, float] | None = None   # loaded from disk on first use
        self.stats = {"computed": 0, "fresh": 0, "stale": 0, "disk": 0, "refreshed": 0,
                      "refresh_failed": 0, "persist_failed": 0, "invalidated": 0,
                      "dropped_pre_write": 0}

    # ------------------------------------------------------------- invalidation
    def _invalid_map(self) -> dict[str, float]:
        if self._invalidated is None:
            loaded: dict[str, float] = {}
            if self.store_dir is not None:
                try:
                    doc = json.loads((self.store_dir / INVALIDATIONS_FILE).read_text(encoding="utf-8"))
                    loaded = {str(k): float(v) for k, v in (doc.get("paths") or {}).items()
                              if isinstance(v, (int, float))}
                except (OSError, ValueError, AttributeError):
                    loaded = {}
            self._invalidated = loaded
        return self._invalidated

    def _valid(self, key: str, entry: _Entry) -> bool:
        with self._lock:
            cut = self._invalid_map().get(key_path(key))
        return cut is None or entry.started_at > cut

    def invalidate(self, path: str) -> None:
        """Every body for ``path`` (any principal, any query) computed from a read that began
        before now is dead: it is dropped here and refused if a refresh or the disk offers it."""
        base = (path or "").split("?", 1)[0].rstrip("/")
        now = self.clock()
        with self._lock:
            inv = self._invalid_map()
            inv[base] = now
            for k in [k for k in self._mem if key_path(k) == base]:
                self._mem.pop(k, None)
            snapshot = dict(inv)
        self.stats["invalidated"] += 1
        self._persist_invalidations(snapshot)

    def _persist_invalidations(self, snapshot: dict[str, float]) -> None:
        if self.store_dir is None:
            return
        try:
            self.store_dir.mkdir(parents=True, exist_ok=True)
            f = self.store_dir / INVALIDATIONS_FILE
            tmp = f.with_name(f"{f.name}.{os.getpid()}.{threading.get_ident()}.tmp")
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump({"schema": SCHEMA, "paths": snapshot}, fh)
            os.replace(tmp, f)
        except Exception:  # noqa: BLE001 -- the in-memory cut still holds for this process; counted
            self.stats["persist_failed"] += 1

    def invalidated_at(self, path: str) -> float | None:
        """When ``path`` was last invalidated (None: never). Callers that share an in-flight
        compute (request_coalesce) put it in their key, so a read after a write never joins a
        compute that began before it."""
        with self._lock:
            return self._invalid_map().get((path or "").split("?", 1)[0].rstrip("/"))

    def _max_stale(self, key: str) -> float:
        cap = PATH_MAX_STALE_S.get(key_path(key))
        return self.max_stale_s if cap is None else min(self.max_stale_s, cap)

    # ------------------------------------------------------------- storage
    def _file(self, key: str) -> Path | None:
        if self.store_dir is None:
            return None
        return self.store_dir / (hashlib.sha256(key.encode()).hexdigest()[:40] + ".json")

    def _disk_read(self, key: str) -> _Entry | None:
        f = self._file(key)
        if f is None:
            return None
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(doc, dict) or doc.get("key") != key or doc.get("schema") != SCHEMA:
            return None
        computed_at, status, body = doc.get("computed_at"), doc.get("status"), doc.get("body")
        if not isinstance(computed_at, (int, float)) or not is_good((status, body)):
            return None
        started_at = doc.get("started_at")
        return _Entry(float(computed_at), (status, body), "disk",
                      float(started_at) if isinstance(started_at, (int, float)) else None)

    def _persist(self, key: str, entry: _Entry) -> None:
        f = self._file(key)
        if f is None:
            return
        try:
            f.parent.mkdir(parents=True, exist_ok=True)
            tmp = f.with_name(f"{f.name}.{os.getpid()}.{threading.get_ident()}.tmp")
            doc = {"schema": SCHEMA, "key": key, "computed_at": entry.computed_at,
                   "started_at": entry.started_at,
                   "as_of": _iso(entry.computed_at), "status": entry.result[0], "body": entry.result[1]}
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(doc, fh, default=str)
            os.replace(tmp, f)
        except Exception:  # noqa: BLE001 -- a cache write must never fail the request; counted in stats
            self.stats["persist_failed"] += 1

    def _remember(self, key: str, result: tuple, started_at: float | None = None) -> _Entry | None:
        """Store a good result, or None when a write landed after its compute began."""
        entry = _Entry(self.clock(), result, "computed", started_at)
        if not self._valid(key, entry):
            self.stats["dropped_pre_write"] += 1
            return None
        with self._lock:
            self._mem.pop(key, None)
            self._mem[key] = entry
            while len(self._mem) > self.max_entries:
                self._mem.pop(next(iter(self._mem)))
            self._errors.pop(key, None)
        self._spawn(lambda: self._persist(key, entry))
        return entry

    # ------------------------------------------------------------- serving
    def _stamp(self, entry: _Entry, *, stale: bool, refreshing: bool, source: str, key: str) -> tuple:
        status, body = entry.result
        out = dict(body)
        if isinstance(out.get("data"), dict):
            out["data"] = dict(out["data"])
        out["_swr"] = {
            "schema": SCHEMA,
            "as_of": _iso(entry.computed_at),
            "age_s": round(max(0.0, self.clock() - entry.computed_at), 1),
            "stale": stale,
            "refreshing": refreshing,
            "source": source,
            "last_refresh_error": self._errors.get(key),
        }
        return status, out

    def _refresh(self, key: str, refresh: Callable[[], Any]) -> None:
        try:
            started = self.clock()
            result = refresh()
            if is_good(result):
                if self._remember(key, result, started) is not None:
                    self.stats["refreshed"] += 1
            else:
                status = result[0] if isinstance(result, tuple) and result else None
                with self._lock:
                    self._errors[key] = f"refresh returned status {status}"
                self.stats["refresh_failed"] += 1
        except Exception as exc:  # noqa: BLE001 -- keep the last good body; the error is named in the stamp
            with self._lock:
                self._errors[key] = type(exc).__name__
            self.stats["refresh_failed"] += 1
        finally:
            with self._lock:
                self._refreshing.discard(key)

    def get(self, key: str, compute: Callable[[], Any], refresh: Callable[[], Any] | None = None) -> Any:
        """``compute`` runs inline on a miss; ``refresh`` (default ``compute``) runs in the background."""
        now = self.clock()
        with self._lock:
            entry = self._mem.get(key)
        if entry is None:
            entry = self._disk_read(key)
            if entry is not None and self._valid(key, entry):
                with self._lock:
                    self._mem.setdefault(key, entry)
                    entry = self._mem[key]
        if entry is not None and not self._valid(key, entry):
            with self._lock:
                if self._mem.get(key) is entry:
                    self._mem.pop(key, None)
            entry = None
        if entry is None or now - entry.computed_at > self._max_stale(key):
            started = self.clock()
            result = compute()
            self.stats["computed"] += 1
            if not is_good(result):
                return result
            kept = self._remember(key, result, started)
            # a write landed mid-compute: serve this caller its answer, keep nothing
            return self._stamp(kept or _Entry(self.clock(), result, "computed", started),
                               stale=False, refreshing=False, source="computed", key=key)
        source = entry.source
        if now - entry.computed_at <= self.fresh_s:
            self.stats["fresh"] += 1
            return self._stamp(entry, stale=False, refreshing=key in self._refreshing, source=source, key=key)
        with self._lock:
            start = key not in self._refreshing
            if start:
                self._refreshing.add(key)
        if start:
            self._spawn(lambda: self._refresh(key, refresh or compute))
        self.stats["disk" if source == "disk" else "stale"] += 1
        return self._stamp(entry, stale=True, refreshing=True, source=source, key=key)


def _daemon_thread(fn: Callable[[], None]) -> None:
    threading.Thread(target=fn, name="swr-refresh", daemon=True).start()


def invalidate_for_write(path: str, server: StaleServe | None = None) -> list[str]:
    """After a POST to ``path``: invalidate every cached read it can change. Returns them."""
    if not enabled():
        return []
    p = (path or "").split("?", 1)[0].lower()
    hit = [get_path for get_path, markers in WRITE_INVALIDATES.items()
           if any(m in p for m in markers)]
    if hit:
        srv = server or default()
        for get_path in hit:
            srv.invalidate(get_path)
    return hit


def default_store_dir() -> Path:
    raw = os.environ.get("TRADEAI_SWR_DIR")
    if raw:
        return Path(raw)
    # No fallback: if the state root cannot be resolved, default() raises and the server's
    # _coalesce_get serves the route uncached, exactly as before this layer existed.
    try:
        from lib.canonical_store_registry import production_state_root
    except ImportError:
        from scripts.lib.canonical_store_registry import production_state_root
    return production_state_root() / "data" / "runtime" / "swr_last_good"


_DEFAULT: StaleServe | None = None
_DEFAULT_LOCK = threading.Lock()


def default() -> StaleServe:
    global _DEFAULT
    with _DEFAULT_LOCK:
        if _DEFAULT is None:
            _DEFAULT = StaleServe(default_store_dir())
        return _DEFAULT
