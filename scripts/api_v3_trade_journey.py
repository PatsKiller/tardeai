"""TradeInView trade journeys — HTTP surface over the read-only ``trade_journey`` projection.

  GET /api/v3/data-broker/trade-journeys[?days=30&symbol=NAVN]   open + recently closed trades (no price bars)
  GET /api/v3/data-broker/trade-journeys/{trade_id}               one journey with its daily price band

The projection (scripts/lib/data_broker/trade_journey.py) reads the CIO prospect record when its store is live and an
interim adapter over today's sources until then, labelled interim. Read-only; zero provider calls; no broker.

Stale-while-revalidate (LQ-20261107-217): the projection is rebuilt inline on every request — 11.4 s warm and 19.5 s
from cold on 2026-11-07 — so /v3/trade-in-view sat on "Loading trade journeys…" until the browser gave up at 30 s.
``scripts/lib/stale_serve.py`` (LQ-20261107-201) already does the right thing for slow desk GETs; this module points it
at the two journey routes. A last good body is served at once while one background refresh recomputes; every served
body carries ``_swr`` (``StaleWhileRevalidate@v1``) saying how old it is.

Two servers, because their key spaces differ:

- **list** — one entry per distinct query (days/symbol), so it persists to disk under the server's SWR store
  (``.../data/runtime/swr_last_good``'s sibling ``trade_journey_last_good``) and survives a restart.
- **detail** — one entry per trade the desk opens, an unbounded key space. Memory only, bounded to ``_DETAIL_ENTRIES``:
  a disk copy per trade would grow without limit for no benefit, as a detail body is only read minutes after it is
  opened.

``?fresh=1`` (the projection's own cache-buster) bypasses the last good body, and ``TRADEAI_SWR=0`` turns the layer
off. If ``lib.stale_serve`` is absent, or the state root cannot be resolved, every function behaves exactly as it did
before this layer existed — no cache, no import error — so this module folds safely before or after
LQ-20261107-201.

The body is not principal-scoped: every field comes from operator-wide stores (holdings accounts, trade
transactions, one global ``ui_prefs`` key), so every authenticated reader gets the same body. If a per-viewer field
is ever added here, its principal must join the key.
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import Any
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

#: ``fresh`` values that must bypass the last good body (the projection reads it the same way).
_BYPASS = ("1", "true")
#: Query keys that do not change the body and must not split the cache.
_IGNORED = ("_", "fresh")
#: Memory-only bound for the per-trade detail cache (one entry per trade the desk opens).
_DETAIL_ENTRIES = 32

_LIST_SWR: Any = None
_DETAIL_SWR: Any = None
_SWR_MODULE: Any = None
_SWR_LOCK = threading.Lock()


def _swr() -> Any:
    """``lib.stale_serve`` when this tree carries it, else None. Resolved once, cached after."""
    global _SWR_MODULE
    if _SWR_MODULE is not None:
        return _SWR_MODULE or None
    with _SWR_LOCK:
        if _SWR_MODULE is None:
            try:
                try:
                    from lib import stale_serve as mod
                except ImportError:
                    from scripts.lib import stale_serve as mod
            except Exception:  # noqa: BLE001 -- no helper: serve computed bodies exactly as before
                mod = False
            _SWR_MODULE = mod
    return _SWR_MODULE or None


def _server(kind: str) -> Any:
    """The StaleServe for a route, or None: list bodies persist to disk, detail bodies stay in memory."""
    global _LIST_SWR, _DETAIL_SWR
    mod = _swr()
    if mod is None:
        return None
    with _SWR_LOCK:
        if kind == "detail":
            if _DETAIL_SWR is None:
                _DETAIL_SWR = mod.StaleServe(store_dir=None, max_entries=_DETAIL_ENTRIES)
            return _DETAIL_SWR
        if _LIST_SWR is None:
            _LIST_SWR = mod.StaleServe(mod.default_store_dir().parent / "trade_journey_last_good")
        return _LIST_SWR


def _reset() -> None:
    """Drop the resolved helper and both servers (tests only; a live server never calls this)."""
    global _LIST_SWR, _DETAIL_SWR, _SWR_MODULE
    with _SWR_LOCK:
        _LIST_SWR = _DETAIL_SWR = _SWR_MODULE = None


def _query_key(query: dict | None) -> str:
    """The query minus what does not change the body, sorted so two spellings share one entry."""
    items = [(str(k), str(v)) for k, v in (query or {}).items() if k not in _IGNORED]
    return "&".join(f"{k}={v}" for k, v in sorted(items))


def _bypass(query: dict | None) -> bool:
    return str((query or {}).get("fresh") or "").strip().lower() in _BYPASS


def _serve(kind: str, key: str, compute, query: dict | None) -> dict[str, Any]:
    """A last good body at once plus one background refresh, or ``compute()`` inline in every other case.

    Errors are never cached (``stale_serve.is_good``), an exception from ``compute`` propagates to the caller's 500,
    and any failure of the cache layer itself degrades to ``compute()`` — the request never fails because the cache
    did.
    """
    mod = _swr()
    if mod is None or _bypass(query):
        return compute()
    try:
        if not mod.enabled():
            return compute()
        server = _server(kind)
    except Exception:  # noqa: BLE001 -- unresolvable state root or a broken helper: serve uncached
        return compute()
    if server is None:
        return compute()
    _status, body = server.get(key, lambda: (200, compute()))
    return body


def get_list(query: dict | None = None) -> dict[str, Any]:
    from lib.data_broker.trade_journey import list_trade_journeys
    return _serve("list", "list|" + _query_key(query), lambda: list_trade_journeys(query or {}), query)


def get_detail(trade_id: str, query: dict | None = None) -> dict[str, Any]:
    from lib.data_broker.trade_journey import detail_trade_journey
    tid = unquote(trade_id)
    return _serve("detail", f"detail|{tid}|{_query_key(query)}",
                  lambda: detail_trade_journey(tid, query or {}), query)


def get_calendar(query: dict | None = None) -> dict[str, Any]:
    from lib.data_broker.trade_calendar import get_calendar as project
    return project(query or {})


def get_history(query: dict | None = None) -> dict[str, Any]:
    from lib.data_broker.holding_history import get_history as project
    return project(query or {})


def get_replay(query: dict | None = None) -> dict[str, Any]:
    """Explicit stored-only delegate; never imports the legacy chart provider."""
    from lib.data_broker.trade_replay import get_replay as project
    return project(query or {})
