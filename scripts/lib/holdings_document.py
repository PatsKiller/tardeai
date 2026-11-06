"""DB-first holdings document for the Home/API readers (Step 3, operator 2026-11-06 "go with all three").

The database is the holdings source of truth (operator 2026-11-03). Readers that used to parse
holdings.json directly get the SAME document the export writes, rendered in memory from
`positions_current` + its enrichment tables (scripts/holdings_export.build_document), with every field
another writer owns carried from the file exactly as the export carries it. One render, two consumers:
the file and the served page cannot drift apart by construction.

Contract
--------
* DB first. `document_source` is "positions_current" when the render succeeded.
* The file is the documented fallback, and only a fallback: when the DB cannot be queried, or it answers
  but the export would REFUSE (no complete promoted run, mixed runs, a failed account in the receipt, an
  unusable number). The served document then says so — `document_source: "holdings_json_fallback"` and
  `document_fallback_reason` — instead of passing the file off as the DB.
* Freshness fails closed (as #2530): the DB document's clocks are the DB's own (row `as_of` /
  `broker_position_as_of` = the sync's capture time, `sync_run_finished_at`); a stale run reads stale.
  A fresher-looking file is never substituted for a stale-but-reachable DB, and the file fallback keeps
  the file's own clocks — no clock is borrowed from the other source.
* An explicitly supplied non-production store never reaches the live DB (fixtures and offline copies stay
  offline). A caller that passes its own `db_query` chooses the DB it reads.
* Read-only: SELECTs only, no write, no broker call, no credential.
"""
from __future__ import annotations

import copy
import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

_SCRIPTS = Path(__file__).resolve().parents[1]
if str(_SCRIPTS) not in sys.path:  # holdings_export / portfolio_repricer live in scripts/
    sys.path.insert(0, str(_SCRIPTS))

DOCUMENT_SOURCE_DB = "positions_current"
DOCUMENT_SOURCE_FILE = "holdings_json_fallback"
#: A non-production store (fixture, offline copy) is read as a file BY DESIGN: not a fallback, no reason.
DOCUMENT_SOURCE_OFFLINE = "holdings_json"
CACHE_TTL_S = 30.0

_CACHE: dict[tuple, tuple[float, dict]] = {}
_CACHE_LOCK = threading.Lock()


class QueryUnavailable(ConnectionError):
    """The DB could not be queried (driver error, USE_DB off, a None from the query helper)."""


class _QueryCursor:
    """A DB-API cursor over a `db_query(sql, params, fetch="all")` callable returning dict rows.

    The served API's helper returns None for every failure. That is UNREACHABLE here — never an empty book
    (a None flattened to [] would read as "no positions").
    """

    def __init__(self, db_query: Callable[..., Any]):
        self._db_query = db_query
        self.description: list[tuple] = []
        self._rows: list[tuple] = []

    def execute(self, sql: str, params: Any = None) -> None:
        try:
            result = self._db_query(sql, params, fetch="all")
        except Exception as exc:  # noqa: BLE001 - a failing helper is an unreachable DB, stated by type
            raise QueryUnavailable(f"db_query raised {type(exc).__name__}") from exc
        if result is None:
            raise QueryUnavailable("db_query returned no result (database unreachable or disabled)")
        rows = [dict(r) for r in result]
        columns = list(rows[0].keys()) if rows else []
        self.description = [(c,) for c in columns]
        self._rows = [tuple(r.get(c) for c in columns) for r in rows]

    def fetchall(self) -> list[tuple]:
        return list(self._rows)

    def fetchone(self) -> Optional[tuple]:
        return self._rows[0] if self._rows else None


class QueryConnection:
    """Just enough of a connection for holdings_export's readers; remembers whether the DB was reachable."""

    def __init__(self, db_query: Callable[..., Any]):
        self._db_query = db_query
        self.unreachable: Optional[str] = None

    def cursor(self) -> _QueryCursor:
        return _TrackingCursor(self)


class _TrackingCursor(_QueryCursor):
    def __init__(self, conn: QueryConnection):
        super().__init__(conn._db_query)
        self._conn = conn

    def execute(self, sql: str, params: Any = None) -> None:
        try:
            super().execute(sql, params)
        except QueryUnavailable as exc:
            self._conn.unreachable = self._conn.unreachable or str(exc)
            raise


def default_db_query() -> Optional[Callable[..., Any]]:
    """The served API's read-only query helper (db_adapter._execute), or None when the DB is disabled."""
    try:
        from db_adapter import USE_DB, _execute  # type: ignore
    except Exception:  # noqa: BLE001 - no adapter is no DB, stated as the fallback reason
        return None
    if not USE_DB:
        return None
    return _execute


def _is_production_store(store: Path) -> bool:
    try:
        from lib.canonical_store_registry import production_state_root  # type: ignore
        from lib.portfolio_positions import STORE_REL  # type: ignore
    except Exception:  # noqa: BLE001
        return False
    try:
        live = Path(production_state_root()).joinpath(*STORE_REL)
        return os.path.realpath(store) == os.path.realpath(live)
    except Exception:  # noqa: BLE001
        return False


def _file_document(store: Path, reason: Optional[str], *, source: str = DOCUMENT_SOURCE_FILE) -> dict[str, Any]:
    from lib.portfolio_positions import read_store_document  # type: ignore

    doc, state = read_store_document(store)
    out: dict[str, Any] = dict(doc) if isinstance(doc, dict) else {}
    out["document_source"] = source
    out["document_fallback_reason"] = reason
    out["document_store_state"] = state
    return out


def load_document(store: Path | str | None = None, *, db_query: Optional[Callable[..., Any]] = None,
                  now: Optional[datetime] = None, use_cache: bool = True) -> dict[str, Any]:
    """The holdings document, DB first. See the module contract. Never raises.

    `store` defaults to the production store; `db_query` defaults to the served API's helper, and only for
    the production store.
    """
    from lib.portfolio_positions import store_path  # type: ignore

    store = Path(store) if store is not None else store_path()
    if db_query is None:
        if not _is_production_store(store):
            return _file_document(store, None, source=DOCUMENT_SOURCE_OFFLINE)
        db_query = default_db_query()
        if db_query is None:
            return _file_document(store, "database disabled or its adapter is unavailable")
    key = (os.path.realpath(store), id(db_query))
    if use_cache:
        with _CACHE_LOCK:
            hit = _CACHE.get(key)
        if hit and time.monotonic() - hit[0] < CACHE_TTL_S:
            return copy.deepcopy(hit[1])
    document = _render(store, db_query, now=now)
    if use_cache:
        with _CACHE_LOCK:
            _CACHE[key] = (time.monotonic(), document)
    return copy.deepcopy(document)


def _render(store: Path, db_query: Callable[..., Any], *, now: Optional[datetime]) -> dict[str, Any]:
    import holdings_export as he  # type: ignore

    conn = QueryConnection(db_query)
    prior, _prior_state = he.read_prior(store)
    try:
        document, _binding = he.build_document(conn, prior=prior, now=now or datetime.now(timezone.utc))
    except he.ExportError as exc:
        why = (f"database unreachable: {conn.unreachable}" if conn.unreachable
               else f"database answered but the render refused: {exc}")
        return _file_document(store, why)
    except Exception as exc:  # noqa: BLE001 - a reader never crashes a page; the reason is served
        return _file_document(store, f"render failed: {type(exc).__name__}")
    document["document_source"] = DOCUMENT_SOURCE_DB
    document["document_fallback_reason"] = None
    return document


def clear_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()
