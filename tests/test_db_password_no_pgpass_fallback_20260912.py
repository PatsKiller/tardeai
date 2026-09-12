"""A missing rendered secret must not be reported as a Postgres auth failure.

Observed 2026-09-12 on boot 6f2050e7. `tradeai-watch-decision-scheduler.service`
started at 17:02:27, six seconds before `tradeai-sm-render.service` first wrote
$XDG_RUNTIME_DIR/tradeai/env successfully at 17:02:33. With DB_PASSWORD unset,
`_conn()` passed `password=""` to libpq, libpq silently consulted ~/.pgpass
(last written 2026-07-16, stale), and the unit died with

    FATAL:  password authentication failed for user "trade_ai"

That error names the wrong subsystem. The database was healthy the whole time --
the same credentials from the rendered env connect fine. The journal proves the
boundary: two auth failures inside the boot race window, zero after the render.

The contract under test is the one db_adapter._db_enabled() already keeps -- an
absent DB_PASSWORD means "not configured", and a component that cannot be
configured must say so rather than borrow a credential from somewhere else.
"""

from __future__ import annotations

import importlib
import sys

import pytest


@pytest.fixture()
def wdr(monkeypatch):
    """Import the module with env_bootstrap neutered.

    load_env() would otherwise repopulate DB_PASSWORD from the live tmpfs
    render on this host and the unset case could never be exercised.
    """
    mod = importlib.import_module("scripts.watch_decision_refresh")
    stub = type(sys)("env_bootstrap")
    stub.load_env = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "env_bootstrap", stub)
    return mod


def _no_password(monkeypatch):
    monkeypatch.delenv("DB_PASSWORD", raising=False)


def test_missing_password_refuses_to_connect(wdr, monkeypatch):
    """NEGATIVE CONTROL: fails before the fix, which called connect() anyway."""
    _no_password(monkeypatch)
    called = []
    stub = type(sys)("psycopg2")
    stub.connect = lambda *a, **k: called.append(k) or object()
    monkeypatch.setitem(sys.modules, "psycopg2", stub)

    with pytest.raises(RuntimeError) as exc:
        wdr._conn()

    assert called == [], (
        "connect() was called with no password; libpq will fall back to "
        "~/.pgpass and misreport the cause"
    )
    msg = str(exc.value)
    assert "DB_PASSWORD" in msg
    assert "sm-render" in msg, "the error must name the subsystem to check"
    assert "pgpass" in msg.lower(), "the error must name the trap it avoided"


def test_error_does_not_blame_postgres(wdr, monkeypatch):
    """The wrong diagnosis is the actual harm; assert it is not reproduced."""
    _no_password(monkeypatch)
    stub = type(sys)("psycopg2")
    stub.connect = lambda *a, **k: pytest.fail("must not connect")
    monkeypatch.setitem(sys.modules, "psycopg2", stub)

    with pytest.raises(RuntimeError) as exc:
        wdr._conn()

    assert "authentication failed" not in str(exc.value).lower()


def test_present_password_is_passed_through(wdr, monkeypatch):
    """POSITIVE CONTROL: the fix must not break the working path."""
    monkeypatch.setenv("DB_PASSWORD", "rendered-secret-value")
    monkeypatch.setenv("DB_USER", "trade_ai")
    seen = {}
    sentinel = object()
    stub = type(sys)("psycopg2")

    def _connect(*a, **k):
        seen.update(k)
        return sentinel

    stub.connect = _connect
    monkeypatch.setitem(sys.modules, "psycopg2", stub)

    assert wdr._conn() is sentinel
    assert seen["password"] == "rendered-secret-value"
    assert seen["user"] == "trade_ai"
    assert seen["application_name"] == "watch_decision_refresh"
