"""Feature gate + production connection factory for the read-only agent-runtime
Command Center surface.

This module lives OUTSIDE the ``agent_runtime`` package on purpose: it is the one
place allowed to import the PostgreSQL driver, so the zero-authority package
(``scripts/agent_runtime``) stays free of ``psycopg2``/``subprocess``/``requests``/
``keyring`` and cannot escalate.

Safety model:
  * DEFAULT DISABLED. The routes are inert unless ``AGENT_RUNTIME_READ_API`` is a
    truthy value AND ``AGENT_RUNTIME_READ_DSN`` is provided at process start.
  * Only an env-provided DSN reference is read; no DSN or credential is embedded.
  * If the gate is off, the DSN is missing, or building the reader fails, the
    handler resolves to the honest zero-authority 503 envelope — it never raises
    into the host server.
  * The reader itself runs READ ONLY transactions, rolls back, and rejects
    superuser/createdb/createrole/replication/bypassrls roles.
"""
from __future__ import annotations

import os
import threading
from typing import Any, Mapping, Optional, Tuple

READ_GATE_ENV = "AGENT_RUNTIME_READ_API"
READ_DSN_ENV = "AGENT_RUNTIME_READ_DSN"

_TRUTHY = {"1", "true", "yes", "on"}

_LOCK = threading.Lock()
_STATE: dict[str, Any] = {"built": False, "api": None}


def _gate_enabled(env: Mapping[str, str]) -> bool:
    return str(env.get(READ_GATE_ENV, "0")).strip().lower() in _TRUTHY


def build_api(env: Optional[Mapping[str, str]] = None, *, reader_factory=None):
    """Construct the ``ReadOnlyAgentRuntimeAPI`` or return ``None`` (503 path).

    ``reader_factory`` (dsn -> reader) is injectable for tests so the driver is
    never required to exercise the gate logic.
    """
    env = os.environ if env is None else env
    if not _gate_enabled(env):
        return None
    dsn = str(env.get(READ_DSN_ENV, "")).strip()
    if not dsn:
        return None
    try:
        from agent_runtime.read_api import ReadOnlyAgentRuntimeAPI

        if reader_factory is not None:
            reader = reader_factory(dsn)
        else:
            import psycopg2  # driver import isolated to this out-of-package module

            from agent_runtime.read_postgres import PostgresAgentRuntimeReader

            def connection_factory():
                conn = psycopg2.connect(dsn)
                conn.autocommit = False  # read path opens an explicit READ ONLY txn
                return conn

            reader = PostgresAgentRuntimeReader(connection_factory)
        return ReadOnlyAgentRuntimeAPI(reader)
    except Exception:
        # Never let a misconfigured reader crash the host; degrade to honest 503.
        return None


def get_api():
    """Process-lifetime singleton. Built once at first request; None => 503 path."""
    if _STATE["built"]:
        return _STATE["api"]
    with _LOCK:
        if not _STATE["built"]:
            _STATE["api"] = build_api()
            _STATE["built"] = True
    return _STATE["api"]


def reset_for_test() -> None:
    with _LOCK:
        _STATE["built"] = False
        _STATE["api"] = None


def handle(method: str, path: str, query: Mapping[str, Any] | None = None) -> Optional[Tuple[int, dict]]:
    """Dispatch one agent-runtime read request. Returns ``(status, body)`` or None."""
    from agent_runtime.read_http import dispatch

    return dispatch(get_api(), method, path, query or {})
