"""pg_attribution — give every Postgres connection a process-level application_name.

Why (2026-10-09, n8nmat/b6): on 2026-10-05 the health agent saw 73/100 connection slots held by
role trade_ai and the TOP holder was application_name '' (19 connections) — nobody could say
which process held them. db_adapter names its own connections, but ~400 modules open raw
``psycopg2.connect(...)`` without ``application_name``. libpq falls back to the ``PGAPPNAME``
environment variable when the caller passes no ``application_name``, so setting it once per
process attributes every raw connect in that process with no per-call change.

Inheritance: a child process inherits the parent's environment. A value this module set records
the owning pid in ``TRADEAI_PGAPPNAME_PID``; a child that imports this module (directly or via
db_adapter / env_bootstrap) sees a foreign pid and re-derives its own name. A ``PGAPPNAME`` the
operator or a unit file set explicitly (no pid marker) is never overwritten.
"""
from __future__ import annotations

import os
import sys

_PID_KEY = "TRADEAI_PGAPPNAME_PID"
_MAX_LEN = 63  # NAMEDATALEN - 1: the server truncates longer names anyway
_GENERIC = {"", "-c", "-m", "__main__.py", "python", "python3", "pytest", "ipython"}


def process_app_name(argv: list[str] | None = None) -> str:
    """Best attribution name for this process: script basename, or the -m module name."""
    argv = sys.argv if argv is None else argv
    base = os.path.basename((argv[0] if argv else "") or "")
    if base in _GENERIC or base.startswith("python"):
        main = sys.modules.get("__main__")
        spec = getattr(main, "__spec__", None)
        mod = getattr(spec, "name", "") or ""
        if mod and mod != "__main__":
            base = mod
    if base in _GENERIC:
        base = base or "python"
    return base[:_MAX_LEN] or "python"


def ensure_pgappname(name: str | None = None) -> str:
    """Set PGAPPNAME for this process unless something outside this module chose it.

    Returns the value in effect. Never raises."""
    try:
        current = os.environ.get("PGAPPNAME")
        owner = os.environ.get(_PID_KEY)
        mine = str(os.getpid())
        if current and (owner is None or owner == mine):
            return current  # explicitly set by operator/unit (no marker), or already ours
        value = (name or process_app_name())[:_MAX_LEN]
        os.environ["PGAPPNAME"] = value
        os.environ[_PID_KEY] = mine
        return value
    except Exception:
        return os.environ.get("PGAPPNAME", "")
