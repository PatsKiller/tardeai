"""Reconnect-once wrapper for long-running psycopg2 batch jobs.

2026-10-09 stall triage: ``topic_ingestion.py`` holds one connection across a 30-minute run of slow
web searches and LLM ratings. A Postgres restart at 20:45:42 ET closed it ("SSL connection has been
closed unexpectedly"); the article-save handler then tried ``ROLLBACK TO SAVEPOINT`` on the dead cursor
and ``conn.rollback()`` on the dead connection, both raised, and the whole 14-topic run died.

``ReconnectingConnection`` wraps a connection factory:

* A lost connection (``OperationalError`` / ``InterfaceError`` with the connection closed or a
  connection-loss message) triggers ONE reconnect (short bounded backoff for a restarting server).
* ``cursor.execute`` that fails because the connection was lost is retried once on the new connection
  **only when it was the first statement of its transaction** (nothing else to replay, so the retry is
  exactly the failed op). Mid-transaction, the earlier statements are gone with the old connection, so
  the error is re-raised after reconnecting; the caller's handler drops that one unit of work and the
  run continues on the new connection.
* ``rollback()`` of a lost connection reconnects and returns (the dead transaction is already gone).
* ``commit()`` of a lost connection reconnects and re-raises (the work was not committed).
* Cursors from before a reconnect rebind to the new connection on their next ``execute``.
* Reconnects per run are capped (``max_reconnects``). Past the cap, or when the server stays down,
  ``ReconnectExhausted`` is raised and ``exhausted`` is set, so a caller whose handlers swallow
  ``Exception`` can still see that the run must fail.

No new dependency: psycopg2 is imported lazily, and the error classes can be injected for tests.
"""
from __future__ import annotations

import time
from typing import Any, Callable, Iterable

_LOSS_MARKERS = (
    "connection already closed",
    "connection has been closed",
    "server closed the connection",
    "terminating connection",
    "the database system is shutting down",
    "the database system is starting up",
    "could not receive data from server",
    "could not send data to server",
    "ssl syscall error",
    "eof detected",
    "connection not open",
    "cursor already closed",
)

DEFAULT_RECONNECT_DELAYS_S = (1.0, 3.0, 6.0)
DEFAULT_MAX_RECONNECTS = 5


def _default_error_classes() -> tuple[type[BaseException], ...]:
    try:
        import psycopg2  # noqa: PLC0415 — lazy: importing this module must not need a driver

        return (psycopg2.OperationalError, psycopg2.InterfaceError)
    except Exception:  # noqa: BLE001 — no driver: nothing can be a lost connection
        return ()


class ReconnectExhausted(RuntimeError):
    """Raised when the connection could not be re-established or the per-run cap was reached."""


class ReconnectingConnection:
    """Connection proxy that survives one server-side connection loss per event (see module doc)."""

    def __init__(
        self,
        factory: Callable[[], Any],
        *,
        max_reconnects: int = DEFAULT_MAX_RECONNECTS,
        reconnect_delays_s: Iterable[float] = DEFAULT_RECONNECT_DELAYS_S,
        error_classes: tuple[type[BaseException], ...] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        log: Callable[[str], None] = print,
    ) -> None:
        self._factory = factory
        self._max_reconnects = int(max_reconnects)
        self._delays = tuple(float(d) for d in reconnect_delays_s)
        self._errors = _default_error_classes() if error_classes is None else tuple(error_classes)
        self._sleep = sleep
        self._log = log
        self._conn = factory()
        self.generation = 0
        self.reconnects = 0
        self.retried_ops = 0
        self.dropped_ops = 0
        self.exhausted = False
        self._tx_dirty = False

    # ── classification ───────────────────────────────────────────────────
    def is_connection_lost(self, exc: BaseException) -> bool:
        if not self._errors or not isinstance(exc, self._errors):
            return False
        try:
            if int(getattr(self._conn, "closed", 0) or 0) != 0:
                return True
        except Exception:  # noqa: BLE001 — a broken connection object counts as lost
            return True
        msg = str(exc).lower()
        return any(m in msg for m in _LOSS_MARKERS)

    # ── reconnect ────────────────────────────────────────────────────────
    def reconnect(self, reason: BaseException | str = "") -> None:
        if self.reconnects >= self._max_reconnects:
            self.exhausted = True
            raise ReconnectExhausted(f"reconnect cap {self._max_reconnects} reached ({reason})")
        try:
            self._conn.close()
        except Exception:  # noqa: BLE001 — the old connection is already dead
            pass
        last: BaseException | None = None
        for attempt, delay in enumerate((0.0, *self._delays), start=1):
            if delay:
                self._sleep(delay)
            try:
                self._conn = self._factory()
            except Exception as exc:  # noqa: BLE001 — retried below, surfaced at the end
                last = exc
                continue
            self.reconnects += 1
            self.generation += 1
            self._tx_dirty = False
            self._log(f"  [db] connection lost ({' '.join(str(reason).split())[:120]}); reconnected "
                      f"(attempt {attempt}, reconnect {self.reconnects}/{self._max_reconnects})")
            return
        self.exhausted = True
        raise ReconnectExhausted(f"could not reconnect after {len(self._delays) + 1} attempts: {last}")

    # ── connection API ───────────────────────────────────────────────────
    @property
    def raw(self) -> Any:
        return self._conn

    def cursor(self, *args: Any, **kwargs: Any) -> "ReconnectingCursor":
        return ReconnectingCursor(self, args, kwargs)

    def _raw_cursor(self, args: tuple, kwargs: dict) -> Any:
        """A cursor on the current connection; a connection found dead here is replaced first."""
        try:
            return self._conn.cursor(*args, **kwargs)
        except Exception as exc:
            if not self.is_connection_lost(exc):
                raise
            self.reconnect(exc)
            return self._conn.cursor(*args, **kwargs)

    def commit(self) -> None:
        try:
            self._conn.commit()
        except Exception as exc:
            if self.is_connection_lost(exc):
                self.dropped_ops += 1
                self.reconnect(exc)
            raise
        self._tx_dirty = False

    def rollback(self) -> None:
        try:
            self._conn.rollback()
        except Exception as exc:
            if not self.is_connection_lost(exc):
                raise
            self.reconnect(exc)
        self._tx_dirty = False

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:  # noqa: BLE001 — closing a dead connection is not an error
            pass

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)


class ReconnectingCursor:
    """Cursor proxy: rebinds after a reconnect; retries a lost first-statement once."""

    def __init__(self, owner: ReconnectingConnection, args: tuple, kwargs: dict) -> None:
        self._owner = owner
        self._args = args
        self._kwargs = kwargs
        self._cur = owner._raw_cursor(args, kwargs)
        self._gen = owner.generation

    def _rebind(self) -> None:
        if self._gen != self._owner.generation:
            self._cur = self._owner._raw_cursor(self._args, self._kwargs)
            self._gen = self._owner.generation

    def _run(self, method: str, *a: Any, **kw: Any) -> Any:
        self._rebind()
        first_in_tx = not self._owner._tx_dirty
        try:
            out = getattr(self._cur, method)(*a, **kw)
        except Exception as exc:
            if not self._owner.is_connection_lost(exc):
                self._owner._tx_dirty = True
                raise
            self._owner.reconnect(exc)
            if not first_in_tx:
                self._owner.dropped_ops += 1
                raise
            self._rebind()
            self._owner.retried_ops += 1
            out = getattr(self._cur, method)(*a, **kw)
        self._owner._tx_dirty = True
        return out

    def execute(self, *a: Any, **kw: Any) -> Any:
        return self._run("execute", *a, **kw)

    def executemany(self, *a: Any, **kw: Any) -> Any:
        return self._run("executemany", *a, **kw)

    def close(self) -> None:
        try:
            self._cur.close()
        except Exception:  # noqa: BLE001
            pass

    def __enter__(self) -> "ReconnectingCursor":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def __iter__(self):
        return iter(self._cur)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._cur, name)
