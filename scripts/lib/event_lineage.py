"""event_lineage.py — carry ``causation_id`` / ``parent_event_id`` across hops.

WHY THIS EXISTS (M5 audit, 2026-09-23)
--------------------------------------
Only ``communication_events`` had lineage columns, and 0 of 35,393 outbound
rows in 7 days carried a real cause. None of the hops an operator question
takes (turn → gap / research request → research completion → outbound reply)
could be joined by event id; the only join was the ticker.

This module is the one place that lineage travels through:

* ``lineage_scope(...)`` — a context (``contextvars``) that a hop opens once.
  Everything written inside it inherits the ids: JSONL rows appended by the
  desk loop and the Hermes research queue, operator/agent turns, and every
  ``CommunicationEvent`` minted in it (``comms/event.py`` reads the context in
  ``_default_lineage`` when the producer set nothing).
* ``lineage_fields(...)`` — the ``{causation_id, parent_event_id}`` pair for a
  JSONL row, from an explicit source or the open scope. Empty when unknown.
* ``resolve_inbound_event(...)`` / ``resolve_event_by_provider_message_id`` —
  the event id of an inbound Telegram message, and the event a reply points at.
  Outbound rows store ``provider_message_id`` comma-joined when one send went
  out as several messages (``"53968,53969"``), so matching is list-aware; the
  exact-match lookup is why the 2026-09-23 reply to 53969 never bound.

RULES
-----
* Additive and optional. Unknown lineage writes nothing; nothing here raises
  into a write path.
* Never launder a non-event id (run_id, wake_id, pending_id, research_id) into
  an event-id field. Only ``communication_events.event_id`` values travel here.
* Root events keep ``causation_id == event_id`` (the comms/event.py convention);
  that marker is set by the event itself, never by this module.
* Under pytest nothing here opens a database connection on its own; a test
  passes ``conn`` explicitly.
"""

from __future__ import annotations

import contextlib
import contextvars
import os
import time
from dataclasses import dataclass
from typing import Any, Iterator, Mapping, Optional

LINEAGE_KEYS = ("causation_id", "parent_event_id")


@dataclass(frozen=True)
class Lineage:
    causation_id: Optional[str] = None
    parent_event_id: Optional[str] = None

    def fields(self) -> dict[str, str]:
        out: dict[str, str] = {}
        if self.causation_id:
            out["causation_id"] = self.causation_id
        if self.parent_event_id:
            out["parent_event_id"] = self.parent_event_id
        return out

    def __bool__(self) -> bool:
        return bool(self.causation_id or self.parent_event_id)


def _shared_var() -> "contextvars.ContextVar[Optional[Lineage]]":
    """One ContextVar per process.

    This module is importable as both ``scripts.lib.event_lineage`` and
    ``lib.event_lineage``; two copies with two variables would let a scope
    opened through one path be invisible to a writer importing the other.
    """
    import sys

    var = getattr(sys, "_tradeai_event_lineage_var", None)
    if var is None:
        var = contextvars.ContextVar("tradeai_event_lineage", default=None)
        setattr(sys, "_tradeai_event_lineage_var", var)
    return var


_CURRENT: contextvars.ContextVar[Optional[Lineage]] = _shared_var()


def _clean(value: Any) -> Optional[str]:
    s = str(value or "").strip()
    return s or None


def current() -> Optional[Lineage]:
    """The lineage of the hop in progress, or None."""
    return _CURRENT.get()


@contextlib.contextmanager
def lineage_scope(
    *,
    causation_id: Any = None,
    parent_event_id: Any = None,
) -> Iterator[Optional[Lineage]]:
    """Open a lineage context for one hop. A scope with no ids is a no-op.

    ``causation_id`` defaults to ``parent_event_id``: the event a hop directly
    answers is also what caused it, unless the caller knows an earlier cause.
    """
    parent = _clean(parent_event_id)
    cause = _clean(causation_id) or parent
    lin = Lineage(causation_id=cause, parent_event_id=parent) if (cause or parent) else None
    if lin is None:
        yield current()
        return
    token = _CURRENT.set(lin)
    try:
        yield lin
    finally:
        _CURRENT.reset(token)


def enter_row_scope(row: Optional[Mapping[str, Any]], token: Any = None) -> Any:
    """Loop helper: leave the previous row's scope (``token``) and open ``row``'s.

    For loops whose bodies ``continue`` out of a try/except, where a ``with``
    block would mean re-indenting the whole body. Pass the returned token back
    on the next iteration, and ``enter_row_scope(None, token)`` after the loop.
    """
    if token is not None:
        try:
            _CURRENT.reset(token)
        except Exception:  # noqa: BLE001
            pass
    if row is None:
        return None
    fields = lineage_fields(row) if isinstance(row, Mapping) and any(row.get(k) for k in LINEAGE_KEYS) else {}
    if not fields:
        return None
    return _CURRENT.set(
        Lineage(
            causation_id=fields.get("causation_id") or fields.get("parent_event_id"),
            parent_event_id=fields.get("parent_event_id"),
        )
    )


def child_of(event_id: Any) -> Lineage:
    """Lineage for something that answers / was caused by ``event_id``."""
    eid = _clean(event_id)
    return Lineage(causation_id=eid, parent_event_id=eid)


def lineage_fields(source: Optional[Mapping[str, Any]] = None) -> dict[str, str]:
    """``{causation_id, parent_event_id}`` from ``source`` if it has them, else the open scope."""
    if isinstance(source, Mapping):
        got = {k: _clean(source.get(k)) for k in LINEAGE_KEYS}
        got = {k: v for k, v in got.items() if v}
        if got:
            return got
    lin = current()
    return lin.fields() if lin else {}


def stamp_row(row: dict[str, Any]) -> dict[str, Any]:
    """Add the open scope's lineage to a JSONL row that carries none. Mutates and returns ``row``."""
    try:
        if not isinstance(row, dict) or any(row.get(k) for k in LINEAGE_KEYS):
            return row
        lin = current()
        if lin:
            row.update(lin.fields())
    except Exception:  # noqa: BLE001 — lineage never breaks a write
        pass
    return row


# ── database lookups (best-effort) ───────────────────────────────────────────
def _connect():
    """Short-lived connection from DB_* env, or None. Never under pytest."""
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return None
    try:
        import psycopg2  # noqa: PLC0415

        return psycopg2.connect(
            host=os.environ.get("DB_HOST", "localhost"),
            port=os.environ.get("DB_PORT") or None,
            dbname=os.environ.get("DB_NAME", "trade_ai"),
            user=os.environ.get("DB_USER", "trade_ai"),
            password=os.environ.get("DB_PASSWORD") or os.environ.get("POSTGRES_PASSWORD"),
            connect_timeout=int(os.environ.get("TRADEAI_LINEAGE_DB_TIMEOUT_S") or 3),
        )
    except Exception:  # noqa: BLE001
        return None


def _query_one(conn, sql: str, params: tuple) -> Optional[dict[str, Any]]:
    owned = conn is None
    if owned:
        conn = _connect()
    if conn is None:
        return None
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        row = cur.fetchone()
        if not row:
            return None
        cols = [d[0] for d in (cur.description or [])]
        return dict(zip(cols, row)) if cols and not isinstance(row, Mapping) else dict(row)
    except Exception:  # noqa: BLE001
        try:
            conn.rollback()
        except Exception:  # noqa: BLE001
            pass
        return None
    finally:
        if owned:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass


_INBOUND_SQL = (
    "SELECT event_id, causation_id, parent_event_id, reply_to_event_id\n"
    "  FROM communication_events\n"
    " WHERE direction = 'INBOUND'\n"
    "   AND provider_coordinates->>'message_id' = %s\n"
    "   AND (%s = '' OR COALESCE(provider_coordinates->>'chat_id', '') IN ('', %s))\n"
    " ORDER BY created_at DESC LIMIT 1"
)

_BY_PROVIDER_MSG_SQL = (
    "SELECT event_id, correlation_id, thread_id, causation_id, parent_event_id,\n"
    "       provider_message_id, provider_coordinates\n"
    "  FROM communication_events\n"
    " WHERE (provider_message_id = %s\n"
    "        OR %s = ANY(string_to_array(provider_message_id, ','))\n"
    "        OR provider_coordinates->>'message_id' = %s)\n"
    "   AND (%s = '' OR COALESCE(provider_coordinates->>'chat_id', '') IN ('', %s))\n"
    " ORDER BY (direction = 'OUTBOUND') DESC, created_at DESC LIMIT 1"
)


def resolve_inbound_event(chat_id: Any, message_id: Any, *, conn=None) -> Optional[dict[str, Any]]:
    """The INBOUND communication event for one Telegram message, or None."""
    mid = _clean(message_id)
    if not mid:
        return None
    chat = _clean(chat_id) or ""
    return _query_one(conn, _INBOUND_SQL, (mid, chat, chat))


def resolve_event_by_provider_message_id(
    provider_message_id: Any, *, chat_id: Any = None, conn=None
) -> Optional[dict[str, Any]]:
    """The ledger event that carried a provider message id (list-aware), or None."""
    pmid = _clean(provider_message_id)
    if not pmid:
        return None
    chat = _clean(chat_id) or ""
    return _query_one(conn, _BY_PROVIDER_MSG_SQL, (pmid, pmid, pmid, chat, chat))


def provider_ids(value: Any) -> list[str]:
    """Split a stored ``provider_message_id`` (``"53968,53969"``) into its ids."""
    return [p.strip() for p in str(value or "").split(",") if p.strip()]


# ── additive-column probe ───────────────────────────────────────────────────
_COLUMN_CACHE: dict[tuple[str, str], tuple[bool, float]] = {}


def _negative_ttl() -> float:
    try:
        return float(os.environ.get("TRADEAI_LINEAGE_COLUMN_PROBE_TTL_S") or 600)
    except ValueError:
        return 600.0


def table_has_column(cursor, table: str, column: str) -> bool:
    """True when ``table.column`` exists. Cached; a miss is re-probed after a TTL.

    The lineage/identity columns arrive by migration, and code ships before the
    migration is applied. Writing a column that is not there aborts the caller's
    transaction, so every optional column is probed first. A probe that fails
    or answers nothing counts as absent.
    """
    key = (table, column)
    hit = _COLUMN_CACHE.get(key)
    now = time.monotonic()
    if hit is not None and (hit[0] or now - hit[1] < _negative_ttl()):
        return hit[0]
    present = False
    try:
        cursor.execute(
            "SELECT 1 FROM information_schema.columns WHERE table_name = %s AND column_name = %s",
            (table, column),
        )
        row = cursor.fetchone()
        present = bool(row) and (row[0] if not isinstance(row, Mapping) else next(iter(row.values()), None)) == 1
    except Exception:  # noqa: BLE001
        present = False
    _COLUMN_CACHE[key] = (present, now)
    return present


def reset_column_cache() -> None:
    _COLUMN_CACHE.clear()


__all__ = [
    "LINEAGE_KEYS",
    "Lineage",
    "child_of",
    "current",
    "enter_row_scope",
    "lineage_fields",
    "lineage_scope",
    "provider_ids",
    "reset_column_cache",
    "resolve_event_by_provider_message_id",
    "resolve_inbound_event",
    "stamp_row",
    "table_has_column",
]
