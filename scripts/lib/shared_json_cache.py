"""Process-wide, bounded, stat-keyed cache for parsed state files (portfolio-server memory, 2026-10-25).

Why this exists
---------------
The portfolio-server parsed the same multi-megabyte state files into several private caches: the 10 MB
``ticker_enrichment_cache.json`` was held three times (``api_v2._ENRICH_CACHE``,
``holding_family._ENRICH_CACHE``, ``lib.portfolio_benchmarks._enrich``), ~21 MB of RSS per copy, and the
identity registry twice because ``lib.identity_registry`` and ``scripts.lib.identity_registry`` load as two
modules with two ``_CACHE`` dicts (~18 MB each). ``portfolio_benchmarks`` also used ``lru_cache(maxsize=1)``,
so its copy never refreshed after the file was rewritten.

Contract
--------
* One store per process, even when this module is imported under several names (``lib.shared_json_cache``,
  ``scripts.lib.shared_json_cache``, ``shared_json_cache``): the store lives on a private singleton module
  in ``sys.modules``.
* Keyed by the file's resolved path; an entry is valid while ``(st_mtime_ns, st_size)`` is unchanged, so a
  rewrite is picked up on the next read and a stale read is impossible.
* Bounded: at most ``SHARED_JSON_CACHE_MAX_ENTRIES`` entries and ``SHARED_JSON_CACHE_MAX_BYTES`` of on-disk
  size; least-recently-used entries are evicted. A file larger than the byte budget is parsed and returned
  but not retained.
* The returned object is SHARED: callers must treat it as read-only.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import types
from collections import OrderedDict
from pathlib import Path
from typing import Any, Callable

_SINGLETON = "_tradeai_shared_json_cache_store"

DEFAULT_MAX_ENTRIES = 32
DEFAULT_MAX_BYTES = 96 * 1024 * 1024  # on-disk bytes of the retained files


def _store() -> types.ModuleType:
    mod = sys.modules.get(_SINGLETON)
    if mod is None:
        mod = types.ModuleType(_SINGLETON)
        mod.lock = threading.RLock()
        mod.entries = OrderedDict()  # key -> (stamp, nbytes, value)
        mod.bytes = 0
        mod.stats = {"hits": 0, "misses": 0, "evictions": 0, "oversize": 0}
        mod = sys.modules.setdefault(_SINGLETON, mod)
    return mod


def _int_or(raw: str | None, default: int) -> int:
    try:
        v = int(raw or default)
        return v if v >= 0 else default
    except ValueError:
        return default


def max_entries() -> int:
    return _int_or(os.environ.get("SHARED_JSON_CACHE_MAX_ENTRIES"), DEFAULT_MAX_ENTRIES)


def max_bytes() -> int:
    return _int_or(os.environ.get("SHARED_JSON_CACHE_MAX_BYTES"), DEFAULT_MAX_BYTES)


def _evict_locked(st: types.ModuleType) -> None:
    cap_n, cap_b = max_entries(), max_bytes()
    while st.entries and (len(st.entries) > cap_n or st.bytes > cap_b):
        _k, (_stamp, nbytes, _v) = st.entries.popitem(last=False)
        st.bytes -= nbytes
        st.stats["evictions"] += 1


def get_or_load(path: Path | str, loader: Callable[[Path], Any], *, namespace: str = "json", default: Any = None) -> Any:
    """Return ``loader(path)``, cached against the file's (mtime_ns, size). ``default`` when the file is absent.

    ``namespace`` separates different parses of the same file (e.g. a raw JSON parse vs a normalized doc).
    Loader exceptions propagate and nothing is cached.
    """
    p = Path(path)
    try:
        real = os.path.realpath(p)
        stt = os.stat(real)
    except OSError:
        return default
    stamp = (stt.st_mtime_ns, stt.st_size)
    key = (namespace, real)
    st = _store()
    with st.lock:
        hit = st.entries.get(key)
        if hit is not None and hit[0] == stamp:
            st.entries.move_to_end(key)
            st.stats["hits"] += 1
            return hit[2]
    value = loader(p)
    nbytes = int(stt.st_size)
    with st.lock:
        st.stats["misses"] += 1
        old = st.entries.pop(key, None)
        if old is not None:
            st.bytes -= old[1]
        if nbytes > max_bytes() or max_entries() == 0:
            st.stats["oversize"] += 1
            return value
        st.entries[key] = (stamp, nbytes, value)
        st.bytes += nbytes
        _evict_locked(st)
    return value


def json_loader(p: Path) -> Any:
    return json.loads(p.read_text(encoding="utf-8"))


def load_json(path: Path | str, default: Any = None, *, expect: type | None = dict) -> Any:
    """Parsed JSON of ``path`` (shared, read-only). ``default`` when absent, unparsable, or not ``expect``."""
    try:
        val = get_or_load(path, json_loader, namespace="json", default=None)
    except Exception:
        return default
    if val is None or (expect is not None and not isinstance(val, expect)):
        return default
    return val


def clear() -> None:
    st = _store()
    with st.lock:
        st.entries.clear()
        st.bytes = 0
        for k in st.stats:
            st.stats[k] = 0


def stats() -> dict[str, Any]:
    st = _store()
    with st.lock:
        return {**st.stats, "entries": len(st.entries), "bytes": st.bytes,
                "max_entries": max_entries(), "max_bytes": max_bytes()}
