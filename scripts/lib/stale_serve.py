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

Bounded computes (LQ-20261113-3034). On 2026-11-13 /v3/manual-execution timed out at 45 s:
/api/v2/watchlist/items computed inline for 17 s while the server grew ~0.5 GB, because a key not
read for an hour recomputes on the request path, the re-entry pages' ``symbols=`` lists were a new
key in every order, and nothing bounded how many distinct keys computed at once (5-7 in the slow
log, 50-175 MB each). Now:

- the symbol-set params of a route are canonical in the key (``request_coalesce.CANONICAL_SET_PARAMS``);
- every compute, inline or background, first takes an ``Admission``: a per-process cap, the
  cgroup memory guard and, when ``shared_get_swr`` provides it, the host-wide build-slot pool
  (``SWR_MAX_CONCURRENT_BUILDS``, ``SWR_MEMORY_GUARD_PCT``, ``SWR_SLOT_DIR``) shared with the
  containment layer. Concurrent inline reads of one key share one compute and one slot;
- a refused background refresh keeps the last good body; its stamp names the refusal;
- a refused inline compute answers ``503 {"status": "UNKNOWN", "error": "build_deferred"}`` with
  ``retry_after_sec`` (the name every 503 and useApi.ts use). A last-good body past the route's max stale is NOT served (LQ-20261113-3034b,
  lead decision D1: the pages do not render ``state``/``_swr`` yet, so an old body would read as
  current); the 503 says one exists, how old it is, and ``past_max_stale``. Within the cap,
  last-good is served STALE as before (the background path). An invalidated body is never served.

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

try:
    from .request_coalesce import canonical_query_value
except ImportError:  # loaded as a top-level module (scripts/lib on sys.path)
    from request_coalesce import canonical_query_value

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
#: LQ-20261113-3034: admission. Same env names and defaults as shared_get_swr (the containment layer).
DEFAULT_MAX_BUILDS = 2
DEFAULT_MEMORY_GUARD_PCT = 85.0
REFUSED_CAP = "REFUSED_CAP"
REFUSED_MEMORY = "REFUSED_MEMORY"
REFUSED_DUPLICATE = "REFUSED_DUPLICATE"
BUILD_IN_PROGRESS = "BUILD_IN_PROGRESS"
RETRY_AFTER_S = 5.0
#: how long a second inline read of the same key waits for the first one's compute
INLINE_WAIT_S = float(os.environ.get("TRADEAI_SWR_INLINE_WAIT_S") or 180.0)


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
        v = canonical_query_value(base, k, v)
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


# ── admission (LQ-20261113-3034) ──────────────────────────────────────────────────────────────────────
def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name) or default)
    except ValueError:
        return default


_CGROUP_DIR: list = []  # resolved once: [path or None]


def _cgroup_dir() -> str | None:
    if not _CGROUP_DIR:
        path = None
        try:
            with open("/proc/self/cgroup", encoding="ascii", errors="replace") as fh:
                for line in fh:
                    parts = line.rstrip("\n").split(":", 2)
                    if len(parts) == 3 and parts[0] == "0" and parts[1] == "":  # cgroup v2
                        cand = "/sys/fs/cgroup" + parts[2]
                        path = cand if os.path.isdir(cand) else None
                        break
        except OSError:
            path = None
        _CGROUP_DIR.append(path)
    return _CGROUP_DIR[0]


def _cgroup_memory() -> tuple[int | None, int | None]:
    """(memory.current, memory.high) of this cgroup in bytes; (None, None) when unreadable or unlimited."""
    d = _cgroup_dir()
    if not d:
        return None, None
    try:
        with open(os.path.join(d, "memory.current"), encoding="ascii") as fh:
            cur = int(fh.read().strip())
        with open(os.path.join(d, "memory.high"), encoding="ascii") as fh:
            raw = fh.read().strip()
    except (OSError, ValueError):
        return None, None
    return cur, (None if raw == "max" else int(raw) if raw.isdigit() else None)


def local_memory_refusal() -> str | None:
    """Why the memory guard refuses a compute now, or None. Fails open: unreadable means allowed."""
    pct = _env_float("SWR_MEMORY_GUARD_PCT", DEFAULT_MEMORY_GUARD_PCT)
    if pct <= 0:
        return None
    cur, high = _cgroup_memory()
    if not cur or not high:
        return None
    if cur >= high * pct / 100.0:
        return f"memory.current={cur} >= {pct:g}% of memory.high={high}"
    return None


def _shared():
    """The containment layer (shared_get_swr), or None. Older copies lack the slot functions; callers getattr."""
    try:
        from . import shared_get_swr as mod
    except ImportError:
        try:
            import shared_get_swr as mod  # type: ignore[no-redef]
        except ImportError:
            return None
    except Exception:  # noqa: BLE001 -- an import side effect must not take the read path down
        return None
    return mod


class _Token:
    __slots__ = ("fds", "released")

    def __init__(self, fds) -> None:
        self.fds = fds
        self.released = False


class Admission:
    """May a compute start now? A per-process cap, the cgroup memory guard and the host-wide slot pool.

    ``acquire(key)`` returns ``(token, None, "")`` or ``(None, outcome, detail)``; ``release(token)`` is
    idempotent and must run in ``finally``. Defaults come from shared_get_swr when it has them (one pool
    and one cap for both layers), else from the same env names here."""

    def __init__(self, cap: int | None = None, memory_refusal: Callable[[], str | None] | None = None,
                 host_slots: bool | None = None) -> None:
        shared = _shared() if (cap is None or memory_refusal is None or host_slots is not False) else None
        if cap is None:
            fn = getattr(shared, "max_concurrent_builds", None)
            try:
                cap = int(fn()) if callable(fn) else int(_env_float("SWR_MAX_CONCURRENT_BUILDS", DEFAULT_MAX_BUILDS))
            except (TypeError, ValueError):
                cap = DEFAULT_MAX_BUILDS
        self.cap = max(1, int(cap))
        self._memory = memory_refusal or getattr(shared, "_memory_refusal", None) or local_memory_refusal
        acq, rel = getattr(shared, "acquire_host_slots", None), getattr(shared, "release_slots", None)
        self._host = (acq, rel) if host_slots is not False and callable(acq) and callable(rel) else None
        self._lock = threading.Lock()
        self._in_use = 0

    @property
    def in_use(self) -> int:
        with self._lock:
            return self._in_use

    def _undo(self) -> None:
        with self._lock:
            self._in_use -= 1

    def acquire(self, key: str) -> tuple[_Token | None, str | None, str]:
        with self._lock:
            if self._in_use >= self.cap:
                return None, REFUSED_CAP, f"{self._in_use} of {self.cap} builds already running in this process"
            self._in_use += 1
        try:
            detail = self._memory()
        except Exception:  # noqa: BLE001 -- fail open, as the containment guard does
            detail = None
        if detail:
            self._undo()
            return None, REFUSED_MEMORY, str(detail)
        fds: list = []
        if self._host is not None:
            try:
                got, outcome = self._host[0]("stale_serve:" + key, self.cap)
            except Exception:  # noqa: BLE001 -- pool unusable: the per-process cap still holds
                got, outcome = [], None
            if got is None:
                self._undo()
                return None, outcome or REFUSED_CAP, ("the same read is computing in another process"
                                                      if outcome == REFUSED_DUPLICATE
                                                      else f"all {self.cap} host-wide build slots are held")
            fds = got
        return _Token(fds), None, ""

    def release(self, token: _Token | None) -> None:
        if token is None:
            return
        with self._lock:
            if token.released:
                return
            token.released = True
            self._in_use -= 1
        if token.fds and self._host is not None:
            try:
                self._host[1](token.fds)
            except Exception:  # noqa: BLE001 -- a lock fd closes with the process anyway
                pass


_ADMISSION: Admission | None = None


def default_admission() -> Admission:
    global _ADMISSION
    with _DEFAULT_LOCK:
        if _ADMISSION is None:
            _ADMISSION = Admission()
        return _ADMISSION


class _Flight:
    """One inline compute of one key; later inline reads of that key wait for it instead of computing."""
    __slots__ = ("started_at", "event", "result", "entry", "error", "refusal")

    def __init__(self, started_at: float) -> None:
        self.started_at = started_at
        self.event = threading.Event()
        self.result: Any = None
        self.entry: _Entry | None = None
        self.error: BaseException | None = None
        self.refusal: tuple[str, str] | None = None


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
                 spawn: Callable[[Callable[[], None]], None] | None = None,
                 admission: Admission | None = None, inline_wait_s: float = INLINE_WAIT_S) -> None:
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
        self._admission = admission                          # None: the process-wide default_admission()
        self.inline_wait_s = inline_wait_s
        self._inline: dict[str, _Flight] = {}
        self.stats = {"computed": 0, "fresh": 0, "stale": 0, "disk": 0, "refreshed": 0,
                      "refresh_failed": 0, "persist_failed": 0, "invalidated": 0,
                      "dropped_pre_write": 0, "joined": 0, "refused": 0, "refresh_refused": 0,
                      "refused_past_max_stale": 0, "deferred": 0}

    def _adm(self) -> Admission:
        return self._admission if self._admission is not None else default_admission()

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
    def _stamp(self, entry: _Entry, *, stale: bool, refreshing: bool, source: str, key: str,
               cause: str | None = None) -> tuple:
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
            "past_max_stale": False,          # a body past the route cap is never served (3034b)
        }
        if stale:
            # LQ-20261107-2622 WV-03: a stale body says so at the top level with its age and cause, so a consumer
            # that never reads `_swr` still cannot mistake it for a fresh answer. `status` is only set when the
            # body has none of its own (never clobber a domain field); `state` always names it.
            out["state"] = "STALE"
            out["age_s"] = out["_swr"]["age_s"]
            out["stale_cause"] = cause or self._errors.get(key) or "refresh_in_progress"
            if "status" not in out:
                out["status"] = "STALE"
        return status, out

    def _refresh(self, key: str, refresh: Callable[[], Any]) -> None:
        adm, token = self._adm(), None
        try:
            token, outcome, detail = adm.acquire(key)
            if token is None:
                # LQ-20261113-3034: no slot or no memory: keep serving the last good body and say why
                with self._lock:
                    self._errors[key] = f"{outcome}: {detail}"
                self.stats["refresh_refused"] += 1
                return
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
            adm.release(token)
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
            return self._inline_compute(key, compute, entry)
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


    # ------------------------------------------------------------- bounded inline compute
    def _inline_compute(self, key: str, compute: Callable[[], Any], last: _Entry | None) -> Any:
        """Compute ``key`` on the request path: one compute per key at a time, and only with an admission.
        ``last`` is a valid body past the route's max stale, or None."""
        with self._lock:
            flight = self._inline.get(key)
            cut = self._invalid_map().get(key_path(key))
            # LQ-258: a read after a write never joins a compute that began before the write
            join = flight is not None and (cut is None or flight.started_at > cut)
            if not join:
                flight = _Flight(self.clock())
                self._inline[key] = flight
        if join:
            self.stats["joined"] += 1
            if not flight.event.wait(self.inline_wait_s):
                return self._refused(key, last, BUILD_IN_PROGRESS,
                                     f"the same read has been computing for over {self.inline_wait_s:g} s")
            return self._serve_flight(key, flight, last)
        adm = self._adm()
        token = None
        try:
            token, outcome, detail = adm.acquire(key)
            if token is None:
                flight.refusal = (outcome or REFUSED_CAP, detail)
            else:
                result = compute()
                self.stats["computed"] += 1
                if is_good(result):
                    # a write landed mid-compute: serve this caller its answer, keep nothing
                    flight.entry = (self._remember(key, result, flight.started_at)
                                    or _Entry(self.clock(), result, "computed", flight.started_at))
                flight.result = result
        except BaseException as exc:
            flight.error = exc
            raise
        finally:
            adm.release(token)
            with self._lock:
                if self._inline.get(key) is flight:
                    self._inline.pop(key, None)
            flight.event.set()
        if flight.refusal is None and flight.entry is None:
            return flight.result        # not good: passed through, as before
        return self._serve_flight(key, flight, last)

    def _serve_flight(self, key: str, flight: _Flight, last: _Entry | None) -> Any:
        if flight.error is not None:
            raise flight.error
        if flight.refusal is not None:
            return self._refused(key, last, *flight.refusal)
        if flight.entry is not None:
            return self._stamp(flight.entry, stale=False, refreshing=False, source="computed", key=key)
        return per_caller_result(flight.result)

    def _refused(self, key: str, last: _Entry | None, outcome: str, detail: str) -> tuple:
        """No compute now: always 503 UNKNOWN. ``last`` (a valid body past the route's max stale) is never
        served (D1, 3034b); the 503 names it, with its age, so the reader knows why there is no answer."""
        self.stats["refused"] += 1
        self.stats["deferred"] += 1
        past = last is not None and self._valid(key, last)
        age = round(max(0.0, self.clock() - last.computed_at), 1) if past else None
        if past:
            self.stats["refused_past_max_stale"] += 1
            detail = (f"{detail}; the last good body is {age:.0f} s old, past the {self._max_stale(key):.0f} s "
                      f"max stale for this route, so it is not served")
        return 503, {"ok": False, "status": "UNKNOWN", "state": "UNKNOWN", "error": "build_deferred",
                     "reason": outcome, "detail": detail, "path": key_path(key),
                     "retry_after_sec": RETRY_AFTER_S,
                     "_swr": {"schema": SCHEMA, "as_of": None, "age_s": None, "stale": False,
                              "refreshing": False, "source": "none", "last_refresh_error": self._errors.get(key),
                              "past_max_stale": past, "last_good_age_s": age}}


class Deferred(Exception):
    """A StaleServe answer that is not a body (``503 build_deferred``), raised by an in-process caller that returns
    bodies, not ``(status, body)`` (LQ-20261113-3051, review 3034b C1).

    Such a caller must not drop the status (the route then answers 200 ``ok: false``, a silent failure) or turn
    it into a 500. The route returns ``served_response`` as is, so the page gets the 503 and its retry hint.
    """

    def __init__(self, status: int, body: dict):
        super().__init__(f"{status} {body.get('error')}: {body.get('reason')}")
        self.status = int(status)
        self.body = body

    @property
    def served_response(self) -> tuple[int, dict]:
        return self.status, self.body


def per_caller_result(result: Any) -> Any:
    """(status, body) with its own top-level body dict, so two callers never share one."""
    if isinstance(result, tuple) and len(result) == 2 and isinstance(result[1], dict):
        return result[0], dict(result[1])
    return result


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
